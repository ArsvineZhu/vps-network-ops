#!/usr/bin/env python3
"""Adapt the existing tested estimator to one private database per inbound."""
import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import signal
import stat
import threading
import usage_daemon as daemon
from observed_usage import UnixHTTP, private_db

SOCKET = Path('/run/vps-mihomo/control.sock')

def fetch():
    owner = pwd.getpwnam('vps-mihomo').pw_uid
    group = grp.getgrnam('vps-controller').gr_gid
    directory = SOCKET.parent.lstat(); socket = SOCKET.lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != owner or directory.st_gid != group or stat.S_IMODE(directory.st_mode) != 0o750:
        raise ValueError('Unsafe controller directory')
    # Mihomo v1.19.33 deliberately chmods Unix sockets to 0666. The
    # non-traversable 0750 parent is the actual access boundary.
    if not stat.S_ISSOCK(socket.st_mode) or socket.st_uid != owner:
        raise ValueError('Unsafe controller socket')
    connection = UnixHTTP(str(SOCKET))
    try:
        connection.request('GET', '/connections'); response = connection.getresponse()
        if response.status != 200: raise ValueError('Controller failed')
        raw = response.read(daemon.MAX_RESPONSE + 1)
        if len(raw) > daemon.MAX_RESPONSE: raise ValueError('Oversized response')
        return json.loads(raw)
    finally: connection.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    stop = threading.Event(); failed = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, lambda *_: stop.set())
    def worker(c):
        db = None
        try:
            db = private_db(Path(c['db']))
            size = db.execute('PRAGMA page_size').fetchone()[0]
            db.execute('PRAGMA max_page_count=' + str(daemon.MAX_DATABASE // size))
            daemon.loop(db, c, stop, fetch)
        except Exception:
            failed.set(); stop.set()
        finally:
            if db is not None: db.close()
    if args.report:
        import sqlite3
        for c in config['collectors']:
            with sqlite3.connect('file:' + c['db'] + '?mode=ro', uri=True) as db:
                print(json.dumps(daemon.report(db, c)))
        return
    threads = [threading.Thread(target=worker, args=(c,)) for c in config['collectors']]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    if failed.is_set(): raise SystemExit('Sampling stopped; inspect storage and private configuration. No raw data logged.')

if __name__ == '__main__': main()
