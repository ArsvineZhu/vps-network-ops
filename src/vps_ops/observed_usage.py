#!/usr/bin/env python3
"""Approximate observed traffic, NOT billing. Scoped cumulative accounting. Never stores destinations/IPs/node credentials; retains connection IDs for deduplication."""

import http.client
import os
import socket
import sqlite3
import stat


def ensure_schema(db, instance, inbound):
    if not instance or not inbound:
        raise ValueError("scope required")
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables and "scope" not in tables:
        raise ValueError("database scope is missing")
    db.execute(
        "CREATE TABLE IF NOT EXISTS scope (singleton INTEGER PRIMARY KEY CHECK(singleton=1), instance TEXT, inbound TEXT)"
    )
    scope = db.execute("SELECT instance,inbound FROM scope WHERE singleton=1").fetchone()
    if scope is not None and scope != (instance, inbound):
        raise ValueError("scope mismatch")
    if scope is None:
        db.execute("INSERT INTO scope VALUES (1,?,?)", (instance, inbound))
    db.execute(
        "CREATE TABLE IF NOT EXISTS watermarks (id TEXT PRIMARY KEY, user TEXT, up INTEGER, down INTEGER, active INTEGER)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS totals (user TEXT PRIMARY KEY, up INTEGER, down INTEGER)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS polls (time TEXT, state TEXT, active INTEGER, disappeared INTEGER, resets INTEGER)"
    )
    db.execute("CREATE TABLE IF NOT EXISTS ignored_polls (time TEXT, ignored INTEGER)")


def record_state(db, at, inbound, instance, state):
    if state not in {"startup/gap", "gap/error", "gap/delayed", "stopped"}:
        raise ValueError("invalid state")
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db, instance, inbound)
        db.execute("INSERT INTO polls VALUES (?,?,?,?,?)", (at, state, None, None, None))
        db.commit()
    except Exception:
        db.rollback()
        raise


def ingest(db, payload, at, inbound, users, instance):
    if not isinstance(payload, dict) or "connections" not in payload:
        raise ValueError("connections missing")
    rows = payload["connections"]
    if rows is None:
        rows = []  # Official Go Snapshot marshals an idle nil slice as null.
    if not isinstance(rows, list):
        raise ValueError("connections malformed")
    # Validate all records before committing any changes.
    parsed = []
    ignored = 0
    for r in rows:
        user = r.get("metadata", {}).get("inboundUser", "")
        if r.get("metadata", {}).get("inboundName") != inbound or user not in users:
            ignored += 1
            continue
        ident = r.get("id")
        up, down = r.get("upload"), r.get("download")
        if not isinstance(user, str) or not user or len(user) > 128:
            continue
        if not isinstance(ident, str) or not ident or len(ident) > 128:
            raise ValueError()
        if any(
            not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 2**63 - 1
            for v in (up, down)
        ):
            raise ValueError()
        parsed.append((ident, user, up, down))
    if len({r[0] for r in parsed}) != len(parsed):
        raise ValueError("duplicate ids")

    if not instance or not inbound:
        raise ValueError("scope required")
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db, instance, inbound)
        db.execute("INSERT INTO ignored_polls VALUES (?,?)", (at, ignored))
        current = {r[0] for r in parsed}
        prior_active = {r[0] for r in db.execute("SELECT id FROM watermarks WHERE active=1")}
        db.execute("UPDATE watermarks SET active=0")
        resets = 0
        for ident, user, up, down in parsed:
            old = db.execute("SELECT user,up,down FROM watermarks WHERE id=?", (ident,)).fetchone()
            if old:
                if old[0] != user:
                    raise ValueError("connection identity changed")
                # Per-direction high-water marks prevent stale samples and counter falls
                # from inflating either direction. Never discard marks on disappearance.
                du, dd = max(0, up - old[1]), max(0, down - old[2])
                if up < old[1] or down < old[2]:
                    resets += 1
                up, down = max(up, old[1]), max(down, old[2])
            else:
                du, dd = up, down
            db.execute(
                "INSERT INTO totals VALUES (?,?,?) ON CONFLICT(user) DO UPDATE SET up=up+excluded.up, down=down+excluded.down",
                (user, du, dd),
            )
            db.execute(
                "INSERT INTO watermarks VALUES (?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET up=excluded.up,down=excluded.down,active=1",
                (ident, user, up, down),
            )
        db.execute(
            "INSERT INTO polls VALUES (?,?,?,?,?)",
            (at, "observed", len(parsed), len(prior_active - current), resets),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def private_db(path):
    # POSIX only: fail closed rather than pretending chmod secures a Windows ACL.
    if os.name != "posix":
        raise ValueError("use POSIX collector")
    parent = path.parent.stat()
    if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise ValueError("private owner-only directory required")
    if path.is_symlink():
        raise ValueError("symlink")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("unsafe database permissions")
    return sqlite3.connect(path)


class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=8)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)
