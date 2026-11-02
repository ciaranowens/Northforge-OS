"""Forge input/ownership/output guards exercise failure paths without privileges."""
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("forge", ROOT / "build/forge.py")
forge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(forge)


class ForgeTests(unittest.TestCase):
    def test_pinned_vm_configuration(self):
        pin, profile = forge.config("uefi-x86")
        self.assertEqual(len(pin["revision"]), 40)
        self.assertEqual(profile["debian_release"], "trixie")
        self.assertFalse(profile["capabilities"]["secure_boot_verified"])
        args = forge.arguments(profile)
        self.assertIn("CPUTHREADS=2", args)
        self.assertIn("USE_TMPFS=no", args)
        self.assertIn("CONSOLE_AUTOLOGIN=no", args)

    def test_target_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            forge.config("../config")

    def test_explicit_container_override(self):
        pin, profile = forge.config("uefi-x86")
        with patch.dict(forge.os.environ, {"NORTHFORGE_ARMBIAN_CONTAINER_IMAGE": "northforge-tools:dev"}):
            self.assertEqual(forge.container_reference(pin), "northforge-tools:dev")
            args = forge.direct_arguments(pin, profile, Path("/tmp/build-source"), "sha256:" + "a" * 64)
            self.assertIn("sha256:" + "a" * 64, args)
            self.assertNotIn("northforge-tools:dev", args)
            mounts = [args[i + 1] for i, item in enumerate(args) if item == "--mount"]
            self.assertTrue(all("docker.sock" not in x and ".docker" not in x for x in mounts))

    def test_invalid_container_override_rejected(self):
        pin, _ = forge.config("uefi-x86")
        with patch.dict(forge.os.environ, {"NORTHFORGE_ARMBIAN_CONTAINER_IMAGE": "--mount /etc"}):
            with self.assertRaises(ValueError):
                forge.container_reference(pin)

    def test_plan_defaults_to_safe_single_container(self):
        import contextlib
        import io
        output = io.StringIO()
        with patch.dict(forge.os.environ, {}, clear=True), contextlib.redirect_stdout(output):
            forge.main(["plan"])
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["launch"], "direct")
        self.assertEqual(plan["command"][:4], ["docker", "--host=unix:///var/run/docker.sock", "run", "--rm"])
        self.assertNotIn("docker", plan["command"][4:])

    def test_upstream_launch_is_refused(self):
        with patch.dict(forge.os.environ, {"NORTHFORGE_ARMBIAN_LAUNCH": "upstream"}):
            with self.assertRaisesRegex(ValueError, "host credentials"):
                forge.main(["plan"])

    def test_unknown_target_rejected(self):
        with self.assertRaises(FileNotFoundError):
            forge.config("unvalidated-arm-board")

    def test_unowned_cache_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(forge, "ROOT", Path(folder)):
            cache = Path(folder) / ".cache/armbian"
            cache.mkdir(parents=True)
            user = cache / "valuable.txt"
            user.write_text("preserve")
            with self.assertRaises(ValueError):
                forge.owned_cache()
            self.assertEqual(user.read_text(), "preserve")

    def test_owned_cache_is_repeatable(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(forge, "ROOT", Path(folder)):
            first = forge.owned_cache()
            self.assertEqual(first, forge.owned_cache())
            self.assertTrue((first / ".northforge-managed").is_file())

    def test_symlinked_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside, patch.object(forge, "ROOT", Path(folder)):
            (Path(folder) / ".cache").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlinked"):
                forge.owned_cache()
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_symlinked_source_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            cache = Path(folder)
            (cache / "source").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "outside"):
                forge.prepare({}, {}, cache, "none")
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_staged_source_changes_are_rejected(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            source = cache / "source"
            source.mkdir()
            commands = [
                ["git", "init", "--quiet"],
                ["git", "remote", "add", "origin", "https://github.com/armbian/build.git"],
            ]
            for command in commands:
                subprocess.run(command, cwd=source, check=True)
            (source / "tracked").write_text("initial")
            subprocess.run(["git", "add", "tracked"], cwd=source, check=True)
            subprocess.run(["git", "-c", "user.name=Unit test", "-c", "user.email=test@example.invalid", "commit", "--quiet", "-m", "fixture"], cwd=source, check=True)
            (source / "tracked").write_text("staged work")
            subprocess.run(["git", "add", "tracked"], cwd=source, check=True)
            with self.assertRaisesRegex(ValueError, "tracked edits"):
                forge.prepare({"repository": "https://github.com/armbian/build.git"}, {}, cache, "none")
            self.assertEqual((source / "tracked").read_text(), "staged work")

    def test_no_image_is_not_a_success(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "exactly one"):
                forge.collect(Path(folder), {}, time.time())

    def test_stale_image_is_not_a_success(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            images = source / "output/images"
            images.mkdir(parents=True)
            (images / "stale.img").write_bytes(b"old")
            with self.assertRaisesRegex(ValueError, "exactly one"):
                forge.collect(source, {}, time.time() + 10)

    def test_manifest_records_hash_and_no_security_claim(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(forge, "ROOT", Path(folder)):
            source = Path(folder) / "source"
            images = source / "output/images"
            images.mkdir(parents=True)
            (images / "new.img").write_bytes(b"artifact fixture")
            forge.collect(source, {"target": {"name": "uefi-x86"}}, time.time() - 5)
            out = Path(folder) / "out/armbian"
            manifest = json.loads((out / "release-manifest.json").read_text())
            self.assertFalse(manifest["security"]["verified_boot"])
            self.assertEqual(manifest["artifact"]["sha256"], forge.hashlib.sha256(b"artifact fixture").hexdigest())
            self.assertIn("release-manifest.json", (out / "SHA256SUMS").read_text())

    def test_partition_hook_only_targets_generated_image(self):
        """Run the actual hook with a recording sfdisk, checking its disk/table."""
        import subprocess
        script = ROOT / "build/userpatches/extensions/northforge.sh"
        shell = '''
set -eu
source "$1"
sdsize=4096; OFFSET=4; UEFISIZE=260; rootfs_size=1024
SDCARD=/tmp/northforge-disposable-test; rootpart=2; uefipart=1
PARTITION_TYPE_UUID_ROOT=4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709
sfdisk() { printf 'target=%s\\n' "$1"; cat; }
exit_with_error() { echo "$*" >&2; exit 1; }
create_partition_table__northforge
'''
        result = subprocess.run(["bash", "-c", shell, "bash", str(script)], check=True, text=True, capture_output=True)
        self.assertIn("target=/tmp/northforge-disposable-test.raw", result.stdout)
        self.assertIn('name="NF-RUNTIME"', result.stdout)
        self.assertIn("size=1024MiB", result.stdout)
        self.assertIn('name="NF-ROOT", start=264MiB, size=2807MiB', result.stdout)


if __name__ == "__main__":
    unittest.main()
