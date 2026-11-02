#!/usr/bin/env python3
"""Boot an opt-in Northforge test image under UEFI; preserve fresh-run evidence.

The original image is never writable to QEMU. All guest writes go to disposable
qcow2 overlays or newly created fixture disks in a private results directory.
No network or interactive root login is provided to the guest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
import uuid


SUITES = {
    "smoke": {"identity", "userspace", "smoke.complete"},
    "ephemeral": {
        "identity", "userspace", "root.readonly", "runtime.encrypted", "secure.locked",
        "persist.encrypted", "persist.reject-wrong-key",
        "persist.approved", "ephemeral.first-boot", "ephemeral.discard",
        "persist.survives", "root.unchanged", "ephemeral.complete",
    },
}
MAX_LOG_BYTES = 64 * 1024 * 1024


def parse_markers(serial: str, nonce: str, mode: str) -> dict:
    """A complete current-run suite and a clean VM exit are both required."""
    markers = re.findall(
        r"^NORTHFORGE_TEST " + re.escape(nonce)
        + r" ([a-z][a-z0-9.-]*) (PASS|FAIL)\r?$", serial, re.MULTILINE,
    )
    passed = {name for name, outcome in markers if outcome == "PASS"}
    failed = {name for name, outcome in markers if outcome == "FAIL"}
    missing = SUITES[mode] - passed
    return {
        "passed": sorted(passed), "failed": sorted(failed),
        "missing": sorted(missing), "complete": not failed and not missing,
    }


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"required tool not found: {name}")
    return path


def regular_file(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError(f"a regular file is required, never a host device: {path}")
    return resolved


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ovmf_pair(code: Path | None, variables: Path | None) -> tuple[Path, Path]:
    if bool(code) != bool(variables):
        raise ValueError("--ovmf-code and --ovmf-vars must be supplied together")
    if code and variables:
        return regular_file(code), regular_file(variables)
    for directory, suffix in [
        ("/usr/share/OVMF", "_4M"),
        ("/usr/share/OVMF", ""),
        ("/usr/share/edk2/ovmf", ""),
    ]:
        candidate = Path(directory)
        code_path = candidate / f"OVMF_CODE{suffix}.fd"
        vars_path = candidate / f"OVMF_VARS{suffix}.fd"
        if code_path.is_file() and vars_path.is_file():
            return code_path.resolve(), vars_path.resolve()
    raise RuntimeError("OVMF firmware not found; install ovmf or select an explicit code/vars pair")


def partition_names(path: Path) -> list[str]:
    result = subprocess.run(
        [require_tool("sfdisk"), "--json", str(path)], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    table = json.loads(result.stdout)["partitiontable"]
    if table["label"] != "gpt":
        raise ValueError(f"UEFI test image must have a GPT partition table: {path}")
    return [part.get("name", "") for part in table["partitions"]]


def create_fixture_disk(path: Path, label: str, size_mib: int) -> None:
    # The path is new and private, never a user-selected host block device.
    with path.open("xb") as stream:
        stream.truncate(size_mib * 1024 * 1024)
    subprocess.run(
        [require_tool("sfdisk"), "--wipe", "never", str(path)],
        input=f'label: gpt\nunit: sectors\n\nstart=2048, type=L, name="{label}"\n',
        check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def qcow_overlay(source: Path, target: Path) -> None:
    subprocess.run(
        [require_tool("qemu-img"), "create", "-f", "qcow2", "-F", "raw",
         "-b", str(source), str(target)], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def drive_option(path: Path, options: str) -> str:
    # QEMU's legacy option parser escapes a comma in a filename by doubling it.
    return f"file={str(path).replace(',', ',,')},{options}"


def acceleration(requested: str) -> str:
    usable = os.access("/dev/kvm", os.R_OK | os.W_OK)
    if requested == "kvm" and not usable:
        raise RuntimeError("KVM explicitly requested but /dev/kvm is unavailable")
    return ("kvm" if usable else "tcg") if requested == "auto" else requested


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True, help="uncompressed raw GPT test image")
    parser.add_argument("--mode", choices=SUITES, default="smoke")
    parser.add_argument("--work-dir", type=Path, help="new or empty results directory")
    parser.add_argument("--timeout", type=int, default=600, help="whole-run seconds, including reboot")
    parser.add_argument("--memory", type=int, default=1536, help="guest RAM MiB")
    parser.add_argument("--accel", choices=("auto", "kvm", "tcg"), default="auto")
    parser.add_argument("--ovmf-code", type=Path)
    parser.add_argument("--ovmf-vars", type=Path)
    parser.add_argument("--runtime-disk", type=Path, help="raw fixture with NF-RUNTIME if image lacks it")
    parser.add_argument("--persist-disk", type=Path, help="raw disposable test LUKS disk (overlay used)")
    parser.add_argument("--test-key-file", type=Path, help="test-only LUKS key supplied through fw_cfg")
    return parser.parse_args()


def run(args: argparse.Namespace, result: dict, work: Path) -> None:
    qemu = require_tool("qemu-system-x86_64")
    require_tool("qemu-img")
    image = regular_file(args.image)
    firmware, variables = ovmf_pair(args.ovmf_code, args.ovmf_vars)
    if not 1 <= args.timeout <= 7200 or not 512 <= args.memory <= 8192:
        raise ValueError("timeout must be 1..7200 seconds; guest RAM must be 512..8192 MiB")
    if args.mode != "ephemeral" and (args.persist_disk or args.test_key_file):
        raise ValueError("persistence inputs apply only to --mode ephemeral")
    names = partition_names(image)
    if names.count("NF-RUNTIME") > 1:
        raise ValueError("image contains ambiguous NF-RUNTIME partitions")
    if "NF-RUNTIME" in names and args.runtime_disk:
        raise ValueError("image already contains NF-RUNTIME; refusing a duplicate runtime disk")

    image_hash = hash_file(image)
    result.update(image=str(image), image_sha256_before=image_hash)
    boot_disk = work / "system.qcow2"
    qcow_overlay(image, boot_disk)
    vars_copy = work / "OVMF_VARS.fd"
    shutil.copyfile(variables, vars_copy)
    accel = acceleration(args.accel)
    result.update(acceleration=accel, firmware=str(firmware))
    serial_path = work / "serial.log"
    qemu_log = work / "qemu.log"
    nonce = result["nonce"]
    command = [
        qemu, "-name", f"northforge-{result['run_id']}",
        "-machine", f"q35,accel={accel}", "-cpu", "host" if accel == "kvm" else "max",
        "-m", str(args.memory), "-smp", "2", "-display", "none", "-monitor", "none",
        "-serial", f"file:{serial_path}", "-nic", "none", "-no-user-config",
        "-drive", drive_option(firmware, "if=pflash,format=raw,readonly=on"),
        "-drive", drive_option(vars_copy, "if=pflash,format=raw"),
        "-drive", drive_option(boot_disk, "if=virtio,format=qcow2"),
        "-device", "virtio-rng-pci",
        "-fw_cfg", f"name=opt/org.northforge/test-mode,string={args.mode}",
        "-fw_cfg", f"name=opt/org.northforge/test-nonce,string={nonce}",
    ]
    if "NF-RUNTIME" not in names:
        runtime = work / "runtime.raw"
        if args.runtime_disk:
            source = regular_file(args.runtime_disk)
            if partition_names(source).count("NF-RUNTIME") != 1:
                raise ValueError("runtime disk must contain exactly one NF-RUNTIME partition")
            runtime = work / "runtime.qcow2"
            qcow_overlay(source, runtime)
            disk_format = "qcow2"
        else:
            create_fixture_disk(runtime, "NF-RUNTIME", 1024)
            disk_format = "raw"
        command += ["-drive", drive_option(runtime, f"if=virtio,format={disk_format}")]
    if args.mode == "ephemeral":
        if args.test_key_file:
            key_file = regular_file(args.test_key_file)
            if key_file.stat().st_size < 32:
                raise ValueError("test key must contain at least 32 bytes")
        else:
            key_file = work / "TEST-ONLY-persist.key"
            descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(secrets.token_bytes(64))
        persist = work / "persist.raw"
        if args.persist_disk:
            source = regular_file(args.persist_disk)
            persist = work / "persist.qcow2"
            qcow_overlay(source, persist)
            disk_format = "qcow2"
        else:
            create_fixture_disk(persist, "NF-TEST-PERSIST", 256)
            disk_format = "raw"
        command += [
            "-drive", drive_option(persist, f"if=virtio,format={disk_format}"),
            "-fw_cfg", "name=opt/org.northforge/test-key,file=" + str(key_file).replace(",", ",,"),
        ]

    start = time.monotonic()
    process = None
    reason = None
    try:
        with qemu_log.open("xb") as output:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            while process.poll() is None:
                if time.monotonic() - start > args.timeout:
                    reason = f"VM exceeded {args.timeout}s timeout"
                    break
                if any(path.exists() and path.stat().st_size > MAX_LOG_BYTES for path in (serial_path, qemu_log)):
                    reason = "VM exceeded 64 MiB per-log limit"
                    break
                # A fixture assertion failure is terminal; no boot retry can hide it.
                if serial_path.exists():
                    with serial_path.open("rb") as stream:
                        stream.seek(max(0, serial_path.stat().st_size - 65536))
                        tail = stream.read().decode("utf-8", errors="replace")
                    if parse_markers(tail, nonce, args.mode)["failed"]:
                        reason = "guest fixture assertion failed"
                        break
                time.sleep(0.2)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)

    result["duration_seconds"] = round(time.monotonic() - start, 2)
    result["qemu_exit_code"] = process.returncode if process else None
    serial = serial_path.read_text(errors="replace") if serial_path.exists() else ""
    result.update(parse_markers(serial, nonce, args.mode))
    result["image_sha256_after"] = hash_file(image)
    result["source_image_unchanged"] = result["image_sha256_after"] == image_hash
    result["success"] = (
        reason is None and result["qemu_exit_code"] == 0
        and result["complete"] and result["source_image_unchanged"]
    )
    if reason:
        result["error"] = reason
    elif not result["success"]:
        result["error"] = "VM exited without a complete passing suite or changed the source image"


def main() -> int:
    args = arguments()
    run_id = uuid.uuid4().hex
    work = (args.work_dir or Path("artifacts/qemu") / run_id).resolve()
    if work.exists() and (not work.is_dir() or any(work.iterdir())):
        print(f"refusing to overwrite nonempty results directory: {work}", file=sys.stderr)
        return 2
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(work, 0o700)
    result = {"run_id": run_id, "nonce": secrets.token_hex(16), "mode": args.mode, "success": False}
    try:
        run(args, result, work)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError) as error:
        result["error"] = str(error)
    except KeyboardInterrupt:
        result["error"] = "interrupted by operator"
    (work / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print(f"Evidence: {work}")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
