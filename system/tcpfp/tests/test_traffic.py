"""Actual 4 MiB HTTP up/down over ephemeral loopback, no namespaces or BPF."""
import importlib.util
from http.server import HTTPServer
from pathlib import Path
import threading
import unittest

spec = importlib.util.spec_from_file_location('traffic',Path(__file__).resolve().parents[1]/'ebpf/traffic.py')
traffic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(traffic)

class TrafficTests(unittest.TestCase):
    def test_loopback_download_and_upload(self):
        with HTTPServer(('127.0.0.1',0),traffic.Handler) as server:
            worker=threading.Thread(target=server.serve_forever,daemon=True)
            worker.start()
            try:
                result=traffic.client('127.0.0.1',server.server_port)
                expected={'bytes':4194304,'sha256':traffic.DIGEST}
                self.assertEqual(result,{'download':expected,'upload':expected})
            finally:
                server.shutdown();worker.join(timeout=5)
                self.assertFalse(worker.is_alive())

if __name__=='__main__':unittest.main()
