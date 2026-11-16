#!/usr/bin/env python3
"""Private Unix-socket observed-usage sampler. No traffic logs or external network."""

import datetime
import json
import logging
import os
import pathlib
import signal
import sqlite3
import stat
import threading
import time

from .observed_usage import UnixHTTP, ingest, private_db, record_state

MAX_RESPONSE = 8 * 1024 * 1024
MAX_DATABASE = 512 * 1024 * 1024
SOCKET = "/var/lib/mihomo/controller/control.sock"
DB = "/var/lib/mihomo-observed/usage.sqlite"


def stamp():
    return datetime.datetime.now(datetime.UTC).isoformat()


def validate_config(c):
    if not isinstance(c, dict) or set(c) != {
        "socket",
        "db",
        "inbound",
        "instance",
        "users",
        "interval",
    }:
        raise ValueError("schema")
    if c["socket"] != SOCKET or c["db"] != DB:
        raise ValueError("paths")
    if (
        not isinstance(c["interval"], (int, float))
        or isinstance(c["interval"], bool)
        or not 1 <= c["interval"] <= 10
    ):
        raise ValueError("interval")
    for key in ("inbound", "instance"):
        if not isinstance(c[key], str) or not c[key] or len(c[key]) > 128:
            raise ValueError("scope")
    users = c["users"]
    if (
        not isinstance(users, list)
        or not users
        or any(not isinstance(x, str) or not x or len(x) > 128 for x in users)
        or len(set(users)) != len(users)
    ):
        raise ValueError("users")
    return c


def check_socket(path, check_file=True):
    path = pathlib.Path(path)
    parent = path.parent
    if parent.is_symlink():
        raise ValueError("socket directory symlink")
    info = parent.stat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("socket boundary unsafe")
    if check_file:
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("socket file unsafe")


def fetch(path):
    check_socket(path)
    connection = UnixHTTP(path)
    try:
        connection.request("GET", "/connections")
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("controller status")
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("snapshot oversized")
        return json.loads(raw)
    finally:
        connection.close()


def sample(db, c, at):
    try:
        payload = fetch(c["socket"])
        ingest(db, payload, at, c["inbound"], set(c["users"]), c["instance"])
        return True
    except Exception:
        record_state(db, at, c["inbound"], c["instance"], "gap/error")
        return False


def loop(db, c, stop):
    record_state(db, stamp(), c["inbound"], c["instance"], "startup/gap")
    previous = None
    healthy = None
    delay = c["interval"]
    while not stop.is_set():
        start = time.monotonic()
        if previous is not None and start - previous > delay * 1.5:
            record_state(db, stamp(), c["inbound"], c["instance"], "gap/delayed")
        previous = start
        # Bounded storage without automatically deleting statistics or watermarks.
        pages = db.execute("PRAGMA page_count").fetchone()[0]
        size = db.execute("PRAGMA page_size").fetchone()[0]
        if pages * size >= MAX_DATABASE:
            raise ValueError("storage cap")
        ok = sample(db, c, stamp())
        if ok != healthy:
            logging.getLogger(__name__).warning(
                "sampling resumed; approximate observed bytes only"
                if ok
                else "sampling gap/error; no raw response logged"
            )
            healthy = ok
        stop.wait(max(0, delay - (time.monotonic() - start)))
    record_state(db, stamp(), c["inbound"], c["instance"], "stopped")


def report(db, c):
    scope = db.execute("SELECT instance,inbound FROM scope WHERE singleton=1").fetchone()
    if scope != (c["instance"], c["inbound"]):
        raise ValueError("scope mismatch")
    latest = db.execute("SELECT time,state FROM polls ORDER BY rowid DESC LIMIT 1").fetchone()
    last_ok = db.execute(
        "SELECT time FROM polls WHERE state='observed' ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    age = (
        (
            datetime.datetime.now(datetime.UTC) - datetime.datetime.fromisoformat(last_ok[0])
        ).total_seconds()
        if last_ok
        else None
    )
    fresh = age is not None and age <= max(15, c["interval"] * 3) and latest[1] == "observed"
    totals = {row[0]: row[1:] for row in db.execute("SELECT user,up,down FROM totals")}
    active = (
        {
            row[0]: row[1]
            for row in db.execute(
                "SELECT user,count(*) FROM watermarks WHERE active=1 GROUP BY user"
            )
        }
        if fresh
        else {}
    )
    return {
        "latest_state": latest,
        "last_success": last_ok[0] if last_ok else None,
        "fresh": fresh,
        "users": [
            {
                "user": u,
                "ever_observed": u in totals,
                "upload_bytes": totals.get(u, (0, 0))[0],
                "download_bytes": totals.get(u, (0, 0))[1],
                "active_connections": active.get(u, 0) if fresh else None,
            }
            for u in c["users"]
        ],
    }


def load_config(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("configuration permissions")
    return validate_config(json.loads(path.read_text()))


def read_report(path):
    config = load_config(path)
    database = pathlib.Path(config["db"])
    info = database.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("database permissions")
    db = sqlite3.connect("file:" + str(database) + "?mode=ro", uri=True)
    try:
        return report(db, config)
    finally:
        db.close()


def serve(path):
    import fcntl

    c = load_config(path)
    check_socket(c["socket"], check_file=False)
    lockpath = pathlib.Path(c["db"]).parent / "collector.lock"
    fd = os.open(lockpath, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = private_db(pathlib.Path(c["db"]))
        try:
            pagesize = db.execute("PRAGMA page_size").fetchone()[0]
            db.execute("PRAGMA max_page_count=" + str(MAX_DATABASE // pagesize))
            stop = threading.Event()
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *args: stop.set())
            loop(db, c, stop)
        finally:
            db.close()
