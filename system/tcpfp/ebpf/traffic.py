#!/usr/bin/env python3
"""Loop-free, bounded bidirectional HTTP payload checks for the private lab."""
from contextlib import closing
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sys
import time

SIZE = 4 * 1024 * 1024
BLOB = bytes(range(256)) * (SIZE // 256)
DIGEST = hashlib.sha256(BLOB).hexdigest()
ADDRESS = '10.203.0.1'

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *_args):
        pass
    def respond(self, body):
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True
    def do_GET(self):
        self.respond(BLOB)
    def do_POST(self):
        if self.headers.get('Content-Length') != str(SIZE):
            self.send_error(400)
            return
        self.connection.settimeout(10)
        body = self.rfile.read(SIZE)
        self.respond(json.dumps({'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}).encode())


def client(address=ADDRESS, port=8080):
    # Retry only before sending a request, while the private server starts.
    conn = None
    for _ in range(100):
        candidate = http.client.HTTPConnection(address, port, timeout=10)
        try:
            candidate.connect()
            conn = candidate
            break
        except ConnectionRefusedError:
            candidate.close()
            time.sleep(0.05)
    if conn is None:
        raise RuntimeError('Private server readiness timed out')
    with closing(conn):
        conn.request('GET', '/blob')
        response = conn.getresponse()
        if response.status != 200:
            raise RuntimeError('GET failed')
        body = response.read()
    downloaded = {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
    expected = {'bytes': SIZE, 'sha256': DIGEST}
    if downloaded != expected:
        raise RuntimeError('Download length/hash mismatch')
    with closing(http.client.HTTPConnection(address, port, timeout=10)) as conn:
        conn.request('POST', '/upload', body=BLOB)
        response = conn.getresponse()
        if response.status != 200:
            raise RuntimeError('POST failed')
        uploaded = json.loads(response.read())
    if uploaded != expected:
        raise RuntimeError('Upload length/hash mismatch')
    return {'download': downloaded, 'upload': uploaded}

if __name__ == '__main__':
    if sys.argv[1:] == ['serve']:
        HTTPServer((ADDRESS, 8080), Handler).serve_forever()
    elif sys.argv[1:] == ['client']:
        print(json.dumps(client()))
    else:
        raise SystemExit('Usage: traffic.py serve|client')
