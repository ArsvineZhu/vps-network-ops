#!/usr/bin/env python3
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from certificate_check import check

class CertificateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cert = Path(cls.tmp.name) / 'cert.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(Path(cls.tmp.name) / 'test-only-key.pem'),
                        '-out', str(cls.cert), '-days', '2', '-subj', '/CN=sub.example.com',
                        '-addext', 'subjectAltName=DNS:sub.example.com'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
    def test_valid(self):
        check(self.cert, 'sub.example.com', 0)
    def test_wrong_host(self):
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            check(self.cert, 'other.example.com', 0)
    def test_zero_exit_hostname_mismatch_rejected(self):
        original_run = subprocess.run
        def old_openssl(args, **kwargs):
            if '-checkhost' in args:
                return subprocess.CompletedProcess(args, 0,
                    stdout='Hostname other.example.com does NOT match certificate\n', stderr='')
            return original_run(args, **kwargs)
        with mock.patch('certificate_check.subprocess.run', side_effect=old_openssl):
            with self.assertRaises(ValueError):
                check(self.cert, 'other.example.com', 0)
    def test_zero_exit_unrecognized_hostname_result_rejected(self):
        original_run = subprocess.run
        for output in ('', 'unexpected output\n',
                       'Hostname other.example.com does match certificate\n'):
            with self.subTest(output=output):
                def unexpected_openssl(args, **kwargs):
                    if '-checkhost' in args:
                        return subprocess.CompletedProcess(args, 0, stdout=output, stderr='')
                    return original_run(args, **kwargs)
                with mock.patch('certificate_check.subprocess.run', side_effect=unexpected_openssl):
                    with self.assertRaises(ValueError):
                        check(self.cert, 'sub.example.com', 0)
    def test_short_validity(self):
        with self.assertRaises(ValueError):
            check(self.cert, 'sub.example.com', 7)
    def test_missing(self):
        with self.assertRaises(ValueError):
            check('/not-a-real-certificate', 'sub.example.com')
    def test_hostname_option_rejected(self):
        with self.assertRaises(ValueError):
            check(self.cert, '-help', 0)

if __name__ == '__main__':
    unittest.main()
