#!/usr/bin/env python3
"""Approximate observed traffic, NOT billing. Scoped cumulative accounting. Never stores destinations/IPs/node credentials; retains connection IDs for deduplication."""

import os
import sqlite3
import stat
from dataclasses import dataclass

from .mihomo import connection_rows


@dataclass(frozen=True)
class UsageRecord:
    identity: str
    user: str
    upload: int
    download: int
    source: str = "mihomo"
    active: bool = True


def mihomo_records(payload, inbounds, users):
    rows = connection_rows(payload)
    records = []
    ignored = 0
    for row in rows:
        metadata = row.get("metadata", {})
        if metadata.get("inboundName") not in inbounds or metadata.get("inboundUser") not in users:
            ignored += 1
            continue
        records.append(
            UsageRecord(
                row.get("id"), metadata["inboundUser"], row.get("upload"), row.get("download")
            )
        )
    validate_records(records)
    return records, ignored


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
    columns = {row[1] for row in db.execute("PRAGMA table_info(watermarks)")}
    if "source" not in columns:
        db.execute("ALTER TABLE watermarks ADD COLUMN source TEXT NOT NULL DEFAULT 'mihomo'")
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


def validate_records(records):
    for record in records:
        if record.source not in {"mihomo", "wireguard"}:
            raise ValueError("invalid source")
        if any(
            not isinstance(v, str) or not v or len(v) > 128 for v in (record.identity, record.user)
        ):
            raise ValueError("invalid identity")
        if any(
            not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 2**63 - 1
            for v in (record.upload, record.download)
        ):
            raise ValueError("invalid counters")
    if len({r.identity for r in records}) != len(records):
        raise ValueError("duplicate ids")


def ingest(db, records, at, scope, instance, sources, *, ignored=0, state="observed"):
    if state not in {"observed", "partial/gap"} or not sources <= {"mihomo", "wireguard"}:
        raise ValueError("invalid sample state")
    validate_records(records)
    if any(record.source not in sources for record in records):
        raise ValueError("Unexpected sample source")
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db, instance, scope)
        db.execute("INSERT INTO ignored_polls VALUES (?,?)", (at, ignored))
        current = {r.identity for r in records if r.active}
        prior_active = set()
        for source in sources:
            prior_active.update(
                r[0]
                for r in db.execute(
                    "SELECT id FROM watermarks WHERE active=1 AND source=?", (source,)
                )
            )
            db.execute("UPDATE watermarks SET active=0 WHERE source=?", (source,))
        resets = 0
        for record in records:
            ident, user, up, down = record.identity, record.user, record.upload, record.download
            old = db.execute(
                "SELECT user,up,down,source FROM watermarks WHERE id=?", (ident,)
            ).fetchone()
            if old:
                if old[0] != user or old[3] != record.source:
                    raise ValueError("connection identity changed")
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
                "INSERT INTO watermarks (id,user,up,down,active,source) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET up=excluded.up,down=excluded.down,active=excluded.active",
                (ident, user, up, down, int(record.active), record.source),
            )
        db.execute(
            "INSERT INTO polls VALUES (?,?,?,?,?)",
            (at, state, len(current), len(prior_active - current), resets),
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
