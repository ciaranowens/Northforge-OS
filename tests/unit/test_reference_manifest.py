"""Exercise provenance against changing images and unsafe-to-follow input symlinks."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[2] / "build/reference/manifest.py"
spec = importlib.util.spec_from_file_location("reference_manifest", MODULE)
manifest_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest_module)


class ReferenceManifestTests(unittest.TestCase):
    def test_image_and_source_are_hashed_from_actual_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            output = Path(temp) / "out"
            (repo / "build/reference").mkdir(parents=True)
            (repo / "rootfs/etc").mkdir(parents=True)
            output.mkdir()
            image = output / "northforge-reference.img"
            image.write_bytes(b"first image bytes")
            (repo / "VERSION").write_text("0.1.0-dev\n")
            source = repo / "rootfs/etc/northforge.conf"
            source.write_bytes(b"deny-plaintext=yes\n")
            (repo / "build/reference/__pycache__").mkdir()
            (repo / "build/reference/__pycache__/manifest.pyc").write_bytes(b"generated cache")
            # A filesystem overlay may contain absolute and broken symlinks.
            # The manifest records links rather than reading host targets.
            (repo / "rootfs/etc/absolute-link").symlink_to("/no/such/secret")
            args = [str(MODULE), "--repo", str(repo), "--output", str(output),
                    "--fixture", "no", "--mirror", "https://deb.debian.org/debian"]
            with patch.object(sys, "argv", args), patch.object(
                manifest_module.subprocess, "check_output", side_effect=["a" * 40 + "\n", " M rootfs/etc/northforge.conf\n"]
            ):
                manifest_module.main()
            first = json.loads((output / "manifest.json").read_text())
            self.assertTrue(first["source_dirty"])
            self.assertEqual(first["version"], "0.1.0-dev")
            self.assertFalse(any("__pycache__" in name for name in first["inputs"]))
            self.assertEqual(first["inputs"]["rootfs/etc/absolute-link"], {"symlink": "/no/such/secret"})
            self.assertEqual(first["inputs"]["rootfs/etc/northforge.conf"]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(first["artifacts"][image.name]["sha256"], hashlib.sha256(image.read_bytes()).hexdigest())
            image.write_bytes(b"changed image bytes")
            with patch.object(sys, "argv", args), patch.object(
                manifest_module.subprocess, "check_output", side_effect=["a" * 40 + "\n", ""]
            ):
                manifest_module.main()
            second = json.loads((output / "manifest.json").read_text())
            self.assertNotEqual(first["artifacts"], second["artifacts"])
            self.assertFalse(second["source_dirty"])
            self.assertFalse(second["secure_boot_verified"])
            self.assertEqual(second["security_mode"], "development-unsigned-integrity-unverified")
            self.assertEqual(second["build_mode"], "clean-debootstrap")
            self.assertFalse(second["prepared_root_reused"])
            reused_args = args + ["--reused-root-status-sha256", "b" * 64]
            with patch.object(sys, "argv", reused_args), patch.object(
                manifest_module.subprocess, "check_output", side_effect=["a" * 40 + "\n", ""]
            ):
                manifest_module.main()
            reused = json.loads((output / "manifest.json").read_text())
            self.assertTrue(reused["prepared_root_reused"])
            self.assertEqual(reused["build_mode"], "diagnostic-reused-prepared-root")
            self.assertEqual(reused["prepared_root_dpkg_status_sha256"], "b" * 64)


if __name__ == "__main__":
    unittest.main()
