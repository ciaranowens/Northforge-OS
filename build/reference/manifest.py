#!/usr/bin/env python3
"""Record actual inputs and outputs; this is provenance metadata, not an attestation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", choices=("yes", "no"), required=True)
    parser.add_argument("--ephemeral-fixture", choices=("yes", "no"), default="no")
    parser.add_argument("--mirror", required=True)
    parser.add_argument("--reused-root-status-sha256", default="")
    args = parser.parse_args()
    git = ["git", "-c", f"safe.directory={args.repo}", "-C", str(args.repo)]
    paths = [args.repo / "build/reference", args.repo / "rootfs", args.repo / "VERSION"]
    if args.fixture == "yes":
        paths.append(args.repo / "tests/qemu/overlay")
    if args.ephemeral_fixture == "yes":
        paths.append(args.repo / "tests/qemu/ephemeral-overlay")
    inputs = {}
    for directory in paths:
        entries = directory.rglob("*") if directory.is_dir() and not directory.is_symlink() else [directory]
        for path in sorted(entries):
            if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                continue
            if path.is_symlink():
                inputs[str(path.relative_to(args.repo))] = {"symlink": str(path.readlink())}
            elif path.is_file():
                inputs[str(path.relative_to(args.repo))] = {"sha256": sha256(path)}
    manifest = {
        "schema_version": 1,
        "target": "reference-uefi-x86_64",
        "distribution": "Northforge OS",
        "version": (args.repo / "VERSION").read_text().strip() if (args.repo / "VERSION").is_file() else "unversioned-development",
        "base": "Debian 13 trixie",
        "build_framework": "debootstrap (reference test target, not Armbian)",
        "build_mode": "diagnostic-reused-prepared-root" if args.reused_root_status_sha256 else "clean-debootstrap",
        "prepared_root_reused": bool(args.reused_root_status_sha256),
        "prepared_root_dpkg_status_sha256": args.reused_root_status_sha256 or None,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_revision": subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip(),
        "source_dirty": bool(subprocess.check_output([*git, "status", "--porcelain"], text=True).strip()),
        "package_sources": {
            "mirror": args.mirror,
            "suites": ["trixie", "trixie-updates"],
            "security_mirror": "https://security.debian.org/debian-security",
            "security_suite": "trixie-security",
            "versions": "packages.tsv",
        },
        "security_mode": "development-unsigned-integrity-unverified",
        "partitions": [
            {"label": "NF-ESP", "format": "fat32", "purpose": "unsigned UEFI loader, kernel and initramfs"},
            {"label": "NF-ROOT", "format": "ext4", "purpose": "read-only base system"},
            {"label": "NF-RUNTIME", "format": "none", "purpose": "ephemeral encrypted runtime, reset at boot"},
        ],
        "secure_boot_verified": False,
        "test_fixture": args.fixture == "yes",
        "ephemeral_test_fixture": args.ephemeral_fixture == "yes",
        "inputs": inputs,
        "artifacts": {"northforge-reference.img": {"sha256": sha256(args.output / "northforge-reference.img")}},
        "reproducibility": "source and package versions recorded; byte identity not established",
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
