#!/usr/bin/env python3
"""Private Unix-socket observed-usage sampler. No traffic logs or external network."""

import datetime
import http.client
import json
import logging
import os
import pathlib
import signal
import sqlite3
import stat
import threading
import time

from .observed_usage import (
    UsageRecord,
    ingest,
    mihomo_records,
    private_db,
    record_state,
    validate_records,
)
from .transport import UnixHTTP

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
        "scope",
        "inbounds",
        "wireguard_snapshot",
        "instance",
        "users",
        "user_labels",
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
    for key in ("scope", "instance"):
        if not isinstance(c[key], str) or not c[key] or len(c[key]) > 128:
            raise ValueError("scope")
    if c["wireguard_snapshot"] not in (None, "/run/vps-ops/wireguard-usage.json"):
        raise ValueError("snapshot path")
    if (
        not isinstance(c["inbounds"], list)
        or not c["inbounds"]
        or any(not isinstance(v, str) or not v for v in c["inbounds"])
    ):
        raise ValueError("inbounds")
    users = c["users"]
    if (
        not isinstance(users, list)
        or any(not isinstance(x, str) or not x or len(x) > 128 for x in users)
        or len(set(users)) != len(users)
    ):
        raise ValueError("users")
    labels = c["user_labels"]
    if (
        not isinstance(labels, dict)
        or any(
            not isinstance(user, str)
            or not user
            or len(user) > 128
            or not isinstance(label, str)
            or not label
            or len(label) > 256
            for user, label in labels.items()
        )
        or not set(users) <= set(labels)
    ):
        raise ValueError("user labels")
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


def wireguard_records(path, users):
    file = pathlib.Path(path)
    info = file.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o640:
        raise ValueError("snapshot permissions")
    if info.st_size > MAX_RESPONSE:
        raise ValueError("snapshot oversized")
    payload = json.loads(file.read_text())
    age = time.time() - payload["time"]
    if not 0 <= age <= 20:
        raise ValueError("snapshot stale")
    epoch = payload["epoch"]
    if not isinstance(epoch, str) or not epoch or len(epoch) > 64:
        raise ValueError("snapshot epoch")
    records = [
        UsageRecord(
            "wg:" + epoch + ":" + row["user"],
            row["user"],
            row["upload"],
            row["download"],
            "wireguard",
            False,
        )
        for row in payload["users"]
        if row["user"] in users
    ]
    validate_records(records)
    return records


def sample(db, c, at):
    records, ignored, sources = [], 0, set()
    errors = False
    try:
        parsed, ignored = mihomo_records(fetch(c["socket"]), set(c["inbounds"]), set(c["users"]))
        records.extend(parsed)
        sources.add("mihomo")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, http.client.HTTPException):
        errors = True
    if c["wireguard_snapshot"]:
        try:
            records.extend(wireguard_records(c["wireguard_snapshot"], set(c["users"])))
            sources.add("wireguard")
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            http.client.HTTPException,
        ):
            errors = True
    if not sources:
        record_state(db, at, c["scope"], c["instance"], "gap/error")
        return False
    try:
        ingest(
            db,
            records,
            at,
            c["scope"],
            c["instance"],
            sources,
            ignored=ignored,
            state="partial/gap" if errors else "observed",
        )
    except (ValueError, sqlite3.Error):
        record_state(db, at, c["scope"], c["instance"], "gap/error")
        return False
    return not errors


def loop(db, path, stop):
    c = load_config(path)
    record_state(db, stamp(), c["scope"], c["instance"], "startup/gap")
    previous = None
    healthy = None
    while not stop.is_set():
        c = load_config(path)
        delay = c["interval"]
        start = time.monotonic()
        if previous is not None and start - previous > delay * 1.5:
            record_state(db, stamp(), c["scope"], c["instance"], "gap/delayed")
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
    record_state(db, stamp(), c["scope"], c["instance"], "stopped")


def report(db, c):
    scope = db.execute("SELECT instance,inbound FROM scope WHERE singleton=1").fetchone()
    if scope != (c["instance"], c["scope"]):
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
                "SELECT user,count(*) FROM watermarks WHERE active=1 AND source='mihomo' GROUP BY user"
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
                "label": c["user_labels"].get(u, u),
                "active": u in c["users"],
                "ever_observed": u in totals,
                "upload_bytes": totals.get(u, (0, 0))[0],
                "download_bytes": totals.get(u, (0, 0))[1],
                "active_connections": active.get(u, 0) if fresh else None,
            }
            for u in dict.fromkeys([*c["users"], *totals])
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
            loop(db, path, stop)
        finally:
            db.close()
