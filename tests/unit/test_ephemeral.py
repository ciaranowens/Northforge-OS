"""Exercise the exact manifest parser shipped in the initramfs."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PARSER = ROOT / "rootfs/usr/lib/northforge/persistence.sh"


class ManifestValidation(unittest.TestCase):
    def parse(self, content):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as manifest:
            manifest.write(content)
            manifest.flush()
            return subprocess.run(
                ["sh", "-eu", "-c", '. "$1"; northforge_validate_manifest "$2"',
                 "northforge-manifest-test", str(PARSER), manifest.name],
                text=True, capture_output=True, check=False,
            )

    def test_empty_manifest_needs_no_persistence(self):
        result = self.parse("# opt-in encrypted persistence\n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_approved_paths(self):
        content = "state/northforge /var/lib/northforge\nconfig/router /etc/northforge/config.d/router\n"
        result = self.parse(content)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, content)

    def test_container_volume_requires_specific_data_directory(self):
        good = self.parse("volumes/dns /var/lib/docker/volumes/dns/_data\n")
        self.assertEqual(good.returncode, 0, good.stderr)
        bad = self.parse("volumes /var/lib/docker\n")
        self.assertNotEqual(bad.returncode, 0)

    def test_privileged_system_directories_rejected(self):
        for target in ("/", "/etc", "/usr", "/boot", "/dev", "/run", "/persist", "/secure", "/var/lib"):
            with self.subTest(target=target):
                self.assertNotEqual(self.parse(f"state {target}\n").returncode, 0)

    def test_path_traversal_rejected(self):
        for source in ("../escape", "one/../../escape", "./state", "one/./state", "one//state", "/state", "state/"):
            with self.subTest(source=source):
                self.assertNotEqual(self.parse(f"{source} /var/lib/northforge\n").returncode, 0)
        for target in ("/var/lib/northforge/../../etc", "/var/lib/northforge/./config", "/var/lib/northforge//config"):
            with self.subTest(target=target):
                self.assertNotEqual(self.parse(f"state {target}\n").returncode, 0)

    def test_duplicate_and_nested_binds_rejected_both_orders(self):
        declarations = (
            "one /var/lib/northforge\ntwo /var/lib/northforge\n",
            "one /var/lib/northforge\ntwo /var/lib/northforge/child\n",
            "one /var/lib/northforge/child\ntwo /var/lib/northforge\n",
            "one /var/lib/northforge\none /srv/northforge\n",
            "one /var/lib/northforge\none/child /srv/northforge\n",
            "one/child /var/lib/northforge\none /srv/northforge\n",
        )
        for content in declarations:
            with self.subTest(content=content):
                self.assertNotEqual(self.parse(content).returncode, 0)

    def test_manifest_is_data_not_executable(self):
        for source in ("$(id)", "state;id", "state`id`", "state\\nother"):
            with self.subTest(source=source):
                result = self.parse(f"{source} /var/lib/northforge\n")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("uid=", result.stdout)

    def test_extra_fields_and_inline_comments_rejected(self):
        for line in ("state", "state /var/lib/northforge extra", "state /var/lib/northforge #comment"):
            with self.subTest(line=line):
                self.assertNotEqual(self.parse(line + "\n").returncode, 0)

    def test_unterminated_final_declaration(self):
        result = self.parse("state /var/lib/northforge")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "state /var/lib/northforge\n")


if __name__ == "__main__":
    unittest.main()
