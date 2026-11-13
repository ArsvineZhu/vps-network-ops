import shutil
import subprocess

import certificate_check
import pytest


@pytest.mark.skipif(not shutil.which("openssl"), reason="OpenSSL is required")
def test_certificate_hostname_and_validity(tmp_path):
    certificate = tmp_path / "cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "2",
            "-keyout",
            str(tmp_path / "key.pem"),
            "-out",
            str(certificate),
            "-subj",
            "/CN=sub.example.com",
            "-addext",
            "subjectAltName=DNS:sub.example.com",
        ],
        check=True,
        capture_output=True,
    )
    certificate_check.check(certificate, "sub.example.com", 0)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        certificate_check.check(certificate, "other.example.com", 0)
    with pytest.raises(ValueError):
        certificate_check.check(certificate, "sub.example.com", 7)


def test_openssl_zero_exit_with_hostname_mismatch_is_rejected(tmp_path, monkeypatch):
    certificate = tmp_path / "cert.pem"
    certificate.write_text("test", encoding="utf-8")

    def openssl(args, **_kwargs):
        if "-dates" in args:
            return subprocess.CompletedProcess(
                args, 0, "notBefore=Jan  1 00:00:00 2020 GMT\nnotAfter=Jan  1 00:00:00 2099 GMT\n"
            )
        return subprocess.CompletedProcess(
            args, 0, "Hostname other.example.com does NOT match certificate\n"
        )

    monkeypatch.setattr(certificate_check.subprocess, "run", openssl)
    with pytest.raises(ValueError):
        certificate_check.check(certificate, "other.example.com", 0)
