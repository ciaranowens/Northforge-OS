"""Acceptance evidence must be complete, current, and free of failures."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "qemu" / "run.py"
SPEC = importlib.util.spec_from_file_location("northforge_qemu", MODULE_PATH)
qemu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qemu)


class QemuEvidenceTests(unittest.TestCase):
    nonce = "a" * 32

    def line(self, case, outcome="PASS", nonce=None):
        return f"NORTHFORGE_TEST {nonce or self.nonce} {case} {outcome}\r\n"

    def test_zero_test_boot_is_failure(self):
        self.assertFalse(qemu.parse_markers("Booted Debian successfully\n", self.nonce, "smoke")["complete"])

    def test_stale_nonce_cannot_supply_passes(self):
        log = "".join(self.line(case, nonce="b" * 32) for case in qemu.SUITES["smoke"])
        self.assertFalse(qemu.parse_markers(log, self.nonce, "smoke")["complete"])

    def test_suite_completion_marker_alone_is_insufficient(self):
        result = qemu.parse_markers(self.line("ephemeral.complete"), self.nonce, "ephemeral")
        self.assertFalse(result["complete"])
        self.assertIn("persist.survives", result["missing"])

    def test_failure_cannot_be_hidden_by_later_pass(self):
        log = self.line("identity", "FAIL")
        log += "".join(self.line(case) for case in qemu.SUITES["smoke"])
        result = qemu.parse_markers(log, self.nonce, "smoke")
        self.assertFalse(result["complete"])
        self.assertEqual(["identity"], result["failed"])

    def test_complete_ephemeral_suite(self):
        log = "firmware and kernel output\r\n"
        log += "".join(self.line(case) for case in qemu.SUITES["ephemeral"])
        result = qemu.parse_markers(log, self.nonce, "ephemeral")
        self.assertTrue(result["complete"])
        self.assertEqual([], result["missing"])

    def test_ephemeral_requires_negative_credential_and_runtime_controls(self):
        omitted = {"persist.reject-wrong-key", "runtime.encrypted", "secure.locked"}
        log = "".join(self.line(case) for case in qemu.SUITES["ephemeral"] - omitted)
        result = qemu.parse_markers(log, self.nonce, "ephemeral")
        self.assertFalse(result["complete"])
        self.assertEqual(sorted(omitted), result["missing"])

    def test_marker_must_be_a_complete_console_line(self):
        log = "x" + self.line("identity")
        result = qemu.parse_markers(log, self.nonce, "smoke")
        self.assertIn("identity", result["missing"])

    def test_host_devices_are_rejected(self):
        with self.assertRaises(ValueError):
            qemu.regular_file(Path("/dev/null"))

    def test_regular_test_image_is_accepted(self):
        with tempfile.NamedTemporaryFile() as image:
            self.assertEqual(Path(image.name).resolve(), qemu.regular_file(Path(image.name)))


if __name__ == "__main__":
    unittest.main()
