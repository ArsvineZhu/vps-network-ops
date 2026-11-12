"""Offline tests: no Ansible connections, service execution or real credentials."""

import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location("validate_bundle", Path(__file__).with_name("validate_bundle.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = Path(self.tmp.name) / "bundle"
        self.bundle.mkdir(mode=0o700)
        (self.bundle / "artifacts").mkdir(mode=0o700)
        self.manifest = {"schema": 1, "files": [], "services": ["vps-mihomo", "vps-guard"],
                         "prerequisites": [], "enabled_protocols": ["vless"], "tcpfp_enabled": False}
        self.add_file("/etc/vps-network/mihomo.json", mode="0640", group="vps-mihomo")
        self.add_file("/etc/vps-network/guard.nft", mode="0600")
        self.add_file("/etc/systemd/system/vps-mihomo.service")
        self.add_file("/etc/systemd/system/vps-guard.service")
        self.add_file("/usr/local/lib/vps-network/guard.py", mode="0755")

    def add_file(self, target, *, mode="0644", owner="root", group="root"):
        source = f"artifacts/file-{len(self.manifest['files'])}"
        (self.bundle / source).write_text("synthetic\n", encoding="utf-8")
        item = {"source": source, "target": target, "owner": owner, "group": group, "mode": mode,
                "sha256": hashlib.sha256(b"synthetic\n").hexdigest()}
        self.manifest["files"].append(item)
        return item

    def validate(self):
        (self.bundle / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        return MODULE.validate(str(self.bundle))

    def rejected(self):
        with self.assertRaises(MODULE.InvalidBundle):
            self.validate()

    def test_valid_bundle_adds_normalized_services_and_safe_directories(self):
        result = self.validate()
        self.assertEqual(result["services"], ["vps-mihomo.service", "vps-guard.service"])
        self.assertIn("/usr/local/lib/vps-network", [d["path"] for d in result["directories"]])

    def test_rejects_non_private_bundle(self):
        self.bundle.chmod(0o755)
        self.rejected()

    def test_rejects_source_escape(self):
        self.manifest["files"][0]["source"] = "artifacts/../../outside"
        self.rejected()

    def test_rejects_absolute_source(self):
        self.manifest["files"][0]["source"] = "/etc/passwd"
        self.rejected()

    def test_rejects_source_symlink(self):
        source = self.bundle / self.manifest["files"][0]["source"]
        source.unlink()
        source.symlink_to("file-1")
        self.rejected()

    def test_rejects_source_directory_symlink(self):
        (self.bundle / "artifacts").rename(self.bundle / "real-artifacts")
        (self.bundle / "artifacts").symlink_to("real-artifacts")
        self.rejected()

    def test_rejects_manifest_symlink(self):
        self.validate()
        (self.bundle / "manifest.json").rename(self.bundle / "real-manifest.json")
        (self.bundle / "manifest.json").symlink_to("real-manifest.json")
        with self.assertRaises(MODULE.InvalidBundle):
            MODULE.validate(str(self.bundle))

    def test_rejects_prefix_confusion(self):
        self.manifest["files"][0]["target"] = "/etc/vps-network-elsewhere/stolen"
        self.rejected()

    def test_rejects_non_canonical_target(self):
        self.manifest["files"][0]["target"] = "/etc/vps-network//mihomo.json"
        self.rejected()

    def test_rejects_target_traversal(self):
        self.manifest["files"][0]["target"] = "/etc/vps-network/../ssh/sshd_config"
        self.rejected()

    def test_rejects_unrelated_systemd_units(self):
        self.add_file("/etc/systemd/system/sshd.service")
        self.rejected()

    def test_rejects_target_file_directory_collision(self):
        self.add_file("/etc/vps-network/mihomo.json/nested", mode="0600")
        self.rejected()

    def test_rejects_unknown_service(self):
        self.manifest["services"].append("sshd")
        self.rejected()

    def test_rejects_duplicate_alias_service(self):
        self.manifest["services"].append("vps-mihomo.service")
        self.rejected()

    def test_rejects_duplicate_target(self):
        self.add_file("/etc/vps-network/mihomo.json", mode="0600")
        self.rejected()

    def test_rejects_missing_required_guard(self):
        self.manifest["services"].remove("vps-guard")
        self.rejected()

    def test_rejects_writable_executable_tree(self):
        self.add_file("/usr/local/lib/vps-network/run.py", mode="0775")
        self.rejected()

    def test_rejects_non_root_executable_tree_owner(self):
        self.add_file("/usr/local/lib/vps-network/run.py", owner="vps-mihomo")
        self.rejected()

    def test_rejects_world_readable_private_config(self):
        self.manifest["files"][0]["mode"] = "0644"
        self.rejected()

    def test_rejects_setuid_or_numeric_mode(self):
        for mode in ("4755", 644):
            with self.subTest(mode=mode):
                self.manifest["files"][0]["mode"] = mode
                self.rejected()

    def test_rejects_false_string_boolean(self):
        self.manifest["tcpfp_enabled"] = "false"
        self.rejected()

    def test_rejects_tls_protocol_without_certificates(self):
        self.manifest["enabled_protocols"] = ["vless", "hysteria2"]
        self.rejected()

    def test_rejects_certificate_without_key(self):
        self.add_file("/etc/vps-network/tls/fullchain.pem", mode="0640", group="vps-tls")
        self.rejected()

    def test_host_bbr_path_is_exact_and_opt_in(self):
        self.add_file("/etc/sysctl.d/80-vps-network-bbr.conf")
        self.rejected()
        self.manifest["bbr_host"] = True
        self.validate()
        self.add_file("/etc/sysctl.d/99-other.conf")
        self.rejected()

    def test_rejects_unverified_binary(self):
        self.validate()
        binary = Path(self.tmp.name) / "mihomo"
        binary.write_bytes(b"not the upstream executable")
        with self.assertRaisesRegex(MODULE.InvalidBundle, "SHA256 mismatch"):
            MODULE.validate(str(self.bundle), str(binary))

    def test_rejects_changed_artifact(self):
        (self.bundle / self.manifest["files"][0]["source"]).write_text("modified\n")
        self.rejected()

    def test_rejects_missing_artifact_hash(self):
        self.manifest["files"][0].pop("sha256")
        self.rejected()

    def test_rejects_missing_guard_runtime_before_installation(self):
        self.manifest["files"] = [f for f in self.manifest["files"] if f["target"] != "/usr/local/lib/vps-network/guard.py"]
        self.rejected()

    def test_private_directory_groups_allow_only_needed_service_traversal(self):
        self.add_file("/etc/vps-network/tls/fullchain.pem", mode="0640", group="vps-tls")
        self.add_file("/etc/vps-network/tls/privkey.pem", mode="0640", group="vps-tls")
        result = self.validate()
        for directory in result["directories"]:
            if directory["path"].startswith("/etc/vps-network"):
                self.assertEqual((directory["owner"], directory["group"], directory["mode"]),
                                 ("root", "vps-tls", "0750"))


class GeneratedBundleCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        system = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("system_test_fixture", system / "tests/test_system.py")
        cls.fixture_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.fixture_module)
        sys.path.insert(0, str(system / "runtime"))

    def test_minimal_real_generated_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            site, secret = self.fixture_module.fixture()
            output = Path(directory) / "bundle"
            self.fixture_module.build.compile_bundle(site, secret, output)
            result = MODULE.validate(str(output))
            self.assertFalse(result["tcpfp_enabled"])
            self.assertIn("vps-guard.service", result["services"])

    def test_full_generated_manifest_with_test_only_self_signed_tls(self):
        import certificate
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cert, key = root / "cert.pem", root / "key.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-keyout", str(key), "-out", str(cert), "-days", "30",
                            "-subj", "/CN=sub.example.com", "-addext", "subjectAltName=DNS:sub.example.com"],
                           check=True, capture_output=True)
            cert.chmod(0o600)
            key.chmod(0o600)
            site, secret = self.fixture_module.fixture(full=True)
            site["subscription"]["enabled"] = True
            site["bbr"]["host"] = True
            output = root / "bundle"
            # This test verifies manifest integration, not CA trust or a deployment.
            # Never relax the product's certificate verification for fixture needs.
            with mock.patch.object(certificate, "check"):
                self.fixture_module.build.compile_bundle(site, secret, output, cert, key)
            result = MODULE.validate(str(output))
            self.assertTrue(result["tcpfp_enabled"])
            self.assertTrue(result["bbr_host"])
            for service in ("vps-network.service", "vps-tcpfp-windows.service", "vps-tcpfp-ios.service",
                            "vps-guard.service", "vps-mihomo.service", "caddy.service",
                            "vps-usage.service", "vps-cert-check.timer"):
                self.assertIn(service, result["services"])


if __name__ == "__main__":
    unittest.main()
