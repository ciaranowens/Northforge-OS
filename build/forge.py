#!/usr/bin/env python3
"""Pinned Armbian integration; operates only in its owned cache and output tree."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse

ROOT = Path(__file__).resolve().parent.parent
OPTIONS = {
    "KERNEL_BTF": "no", "CPUTHREADS": "2", "USE_TMPFS": "no",
    "BUILD_MINIMAL": "yes", "BUILD_DESKTOP": "no", "KERNEL_CONFIGURE": "no",
    "ROOTFS_TYPE": "ext4", "COMPRESS_OUTPUTIMAGE": "no",
    "CONSOLE_AUTOLOGIN": "no",
    "ARMBIAN_DOCKER_AUTO_PULL": "no", "DOCKER_PRUNE": "no",
    "INSTALL_ARMBIAN_FIRMWARE": "no", "EXTRAWIFI": "no",
}


def run(args, *, cwd=None, capture=False):
    return subprocess.run([str(x) for x in args], cwd=cwd, check=True,
                          text=True, stdout=subprocess.PIPE if capture else None).stdout


def config(target):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", target):
        raise ValueError("Invalid target name")
    pin = json.loads((ROOT / "config/armbian.json").read_text())
    profile = json.loads((ROOT / f"config/targets/{target}.json").read_text())
    if not re.fullmatch(r"[0-9a-f]{40}", pin["revision"]):
        raise ValueError("Armbian must be pinned to a full 40-character commit")
    if profile["name"] != target or profile["architecture"] != "amd64":
        raise ValueError("Only the explicit amd64 VM profile is currently implemented")
    if profile["kernel_provider"] != "debian-generic":
        raise ValueError("Unsupported kernel provider; add and validate a target first")
    if not isinstance(profile["runtime_partition_mib"], int) or profile["runtime_partition_mib"] < 256:
        raise ValueError("Runtime partition must be an integer of at least 256 MiB")
    return pin, profile


def arguments(profile):
    opts = dict(OPTIONS, BOARD=profile["board"], BRANCH=profile["branch"],
                RELEASE=profile["debian_release"])
    return ["northforge", *[f"{k}={v}" for k, v in sorted(opts.items())], "ALLOW_ROOT=yes"]


def check():
    missing = [tool for tool in ("git", "bash", "python3", "docker") if not shutil.which(tool)]
    if missing:
        raise ValueError("Missing tools: " + ", ".join(missing))
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        raise ValueError("This build target requires a Linux x86-64 runner")
    memory = next(int(x.split()[1]) * 1024 for x in Path("/proc/meminfo").read_text().splitlines()
                  if x.startswith("MemTotal:"))
    limit = Path("/sys/fs/cgroup/memory.max")
    if limit.exists() and limit.read_text().strip().isdigit():
        memory = min(memory, int(limit.read_text()))
    if memory < 5 * 1024**3:
        raise ValueError("At least 5 GiB RAM is required; the intended build VM has 6 GB")
    if shutil.disk_usage(ROOT).free < 40 * 1024**3:
        raise ValueError("At least 40 GiB free workspace storage is required")
    run(["docker", "--host=unix:///var/run/docker.sock", "info", "--format", "{{.ServerVersion}}"])
    print("Runner prerequisites passed. Image build additionally needs privileged loop/mount support.")


def container_reference(pin):
    image = os.environ.get("NORTHFORGE_ARMBIAN_CONTAINER_IMAGE", pin["container_image"])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@+-]*", image):
        raise ValueError("Invalid explicit Armbian build container image reference")
    return image


def resolve_container(image):
    inspect = ["docker", "--host=unix:///var/run/docker.sock", "image", "inspect", "--format", "{{.Id}}", image]
    result = subprocess.run(inspect, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        run(["docker", "--host=unix:///var/run/docker.sock", "pull", image])
        result = subprocess.run(inspect, text=True, check=True, stdout=subprocess.PIPE)
    image_id = result.stdout.strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("Docker did not resolve the builder to an immutable image ID")
    return {"reference": image, "image_id": image_id}


def direct_arguments(pin, profile, source, image_id=None):
    """Single upstream builder container: no daemon socket or credential mounts."""
    command = ["docker", "--host=unix:///var/run/docker.sock", "run", "--rm", "--privileged",
               "--user=0", "--mount", f"type=bind,src={source},dst=/armbian",
               "--workdir=/armbian", "--env", "ARMBIAN_RUNNING_IN_CONTAINER=yes"]
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"):
        if name in os.environ:
            command.extend(["--env", name])
    proxy = os.environ.get("HTTPS_PROXY", os.environ.get("https_proxy", ""))
    host = urllib.parse.urlparse(proxy).hostname
    if host:
        command.extend(["--add-host", f"{host}:{socket.gethostbyname(host)}"])
    ca_path = os.environ.get("NORTHFORGE_BUILD_CA")
    if ca_path:
        ca = Path(ca_path).resolve(strict=True)
        command.extend(["--mount", f"type=bind,src={ca},dst=/run/northforge-build-ca.pem,readonly"])
        for name in ("SSL_CERT_FILE", "CURL_CA_BUNDLE", "GIT_SSL_CAINFO", "REQUESTS_CA_BUNDLE"):
            command.extend(["--env", f"{name}=/run/northforge-build-ca.pem"])
        command.extend(["--env", "APT_CONFIG=/armbian/userpatches/northforge-apt.conf"])
    return [*command, image_id or container_reference(pin), "bash", "./compile.sh",
            *arguments(profile), f"SET_OWNER_TO_UID={os.getuid()}"]


def owned_cache():
    cache_root = ROOT / ".cache"
    cache = cache_root / "armbian"
    if cache_root.is_symlink() or cache.is_symlink():
        raise ValueError("Refusing a symlinked build cache")
    cache.mkdir(parents=True, exist_ok=True)
    if cache.resolve().parent != cache_root.resolve() or not cache_root.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Build cache must remain within this checkout")
    marker = cache / ".northforge-managed"
    if not marker.exists():
        if any(cache.iterdir()):
            raise ValueError(f"Refusing to use nonempty unowned cache: {cache}")
        marker.write_text("Northforge Armbian build cache\n")
    return cache


def prepare(pin, profile, cache, test_mode, container=None):
    source = cache / "source"
    if source.is_symlink() or source.resolve().parent != cache.resolve():
        raise ValueError("Refusing a source checkout outside its owned cache")
    if not source.exists():
        source.mkdir()
        run(["git", "init", "--quiet", source])
        run(["git", "remote", "add", "origin", pin["repository"]], cwd=source)
    remote = run(["git", "remote", "get-url", "origin"], cwd=source, capture=True).strip()
    if remote != pin["repository"]:
        raise ValueError("Cache origin differs from pinned Armbian source; preserve it and use a fresh cache")
    has_head = subprocess.run(["git", "rev-parse", "--verify", "HEAD^{commit}"], cwd=source,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    diff = ["git", "diff", "HEAD", "--name-only"] if has_head else ["git", "diff", "--cached", "--name-only"]
    if run(diff, cwd=source, capture=True).strip():
        raise ValueError("Armbian cache has tracked edits; preserve them before rebuilding")
    have = subprocess.run(["git", "cat-file", "-e", pin["revision"] + "^{commit}"],
                          cwd=source, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not have:
        run(["git", "fetch", "--depth", "1", "origin", pin["revision"]], cwd=source)
    run(["git", "checkout", "--detach", pin["revision"]], cwd=source)
    actual = run(["git", "rev-parse", "HEAD"], cwd=source, capture=True).strip()
    if actual != pin["revision"]:
        raise ValueError("Armbian cache revision mismatch")
    patches = source / "userpatches"
    if patches.exists():
        # userpatches is generated solely by this wrapper inside our marked cache.
        shutil.rmtree(patches)
    shutil.copytree(ROOT / "build/userpatches", patches)
    with (patches / "config-northforge.conf").open("a") as conf:
        conf.write(f"\nNORTHFORGE_RUNTIME_MIB={profile['runtime_partition_mib']}\n")
    ca_path = os.environ.get("NORTHFORGE_BUILD_CA")
    if ca_path:
        ca = Path(ca_path).resolve(strict=True)
        if not ca.is_file():
            raise ValueError("NORTHFORGE_BUILD_CA must name a readable public CA bundle")
        # Public trust metadata only. The external CA is mounted read-only, never
        # copied into the resulting rootfs or a Docker layer.
        with (patches / "config-northforge.conf").open("a") as conf:
            import shlex
            conf.write("\nNORTHFORGE_BUILD_CA=" + shlex.quote(str(ca)) + "\n")
        (patches / "northforge-apt.conf").write_text('Acquire::https::CaInfo "/run/northforge-build-ca.pem";\n')
    overlay = patches / "overlay"
    overlay.mkdir()
    rootfs = ROOT / "rootfs"
    if rootfs.exists():
        shutil.copytree(rootfs, overlay / "northforge-rootfs", symlinks=True)
    else:
        (overlay / "northforge-rootfs").mkdir()
    if test_mode != "none":
        shutil.copytree(ROOT / "tests/qemu/overlay", overlay / "northforge-tests", symlinks=True)
        if test_mode == "ephemeral":
            shutil.copytree(ROOT / "tests/qemu/ephemeral-overlay", overlay / "northforge-tests", dirs_exist_ok=True, symlinks=True)
    metadata = {"version": (ROOT / "VERSION").read_text().strip(),
                "source_revision": run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture=True).strip(),
                "source_dirty": bool(run(["git", "status", "--porcelain"], cwd=ROOT, capture=True).strip()),
                "armbian_revision": pin["revision"], "target": profile,
                "test_fixture": test_mode, "signing_mode": "unsigned-development"}
    if container:
        metadata["build_container"] = container
    (overlay / "northforge-build.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (overlay / "northforge-version").write_text(metadata["version"] + "\n")
    print(f"Prepared pinned Armbian checkout: {source}")
    return source, metadata


def collect(source, metadata, started):
    images = [p for p in (source / "output/images").glob("*.img") if p.stat().st_mtime >= started]
    if len(images) != 1:
        raise ValueError(f"Expected exactly one new raw image, found {len(images)}; no old artifact will be published")
    output = ROOT / "out/armbian"
    output.mkdir(parents=True, exist_ok=True)
    image = output / f"northforge-{metadata['target']['name']}.img"
    temporary = image.with_suffix(".img.tmp")
    shutil.copyfile(images[0], temporary)
    temporary.replace(image)
    with image.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    metadata = dict(metadata, artifact={"file": image.name, "sha256": digest, "size_bytes": image.stat().st_size},
                    security={"verified_boot": False, "dm_verity": False, "production_signed": False},
                    inputs_note="Framework commit is pinned; Debian repositories and build container are not snapshot-pinned. Byte-identical reproducibility is not established.")
    manifest = output / "release-manifest.json"
    manifest.write_text(json.dumps(metadata, indent=2) + "\n")
    mdigest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {image.name}\n{mdigest}  {manifest.name}\n")
    print(f"Built {image}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "container-plan", "check", "prepare", "build"))
    parser.add_argument("target", nargs="?", default="uefi-x86")
    args = parser.parse_args(argv)
    # This wrapper is for the dedicated local build daemon. Never inherit a
    # context/TLS selector that might redirect a privileged run elsewhere.
    for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        os.environ.pop(name, None)
    os.environ["DOCKER_HOST"] = "unix:///var/run/docker.sock"
    pin, profile = config(args.target)
    if os.environ.get("NORTHFORGE_ARMBIAN_LAUNCH", "direct") != "direct":
        raise ValueError("Only direct single-container launch is supported; the upstream Docker launcher can mount host credentials")
    mode = os.environ.get("NORTHFORGE_TEST_MODE", "none")
    if mode not in ("none", "smoke", "ephemeral"):
        raise ValueError("NORTHFORGE_TEST_MODE must be none, smoke or ephemeral")
    if args.action == "plan":
        print(json.dumps({"pin": pin, "target": profile, "launch": "direct", "command": direct_arguments(pin, profile, ROOT / ".cache/armbian/source"), "test_fixture": mode}, indent=2))
        return
    if args.action == "container-plan":
        print(json.dumps(direct_arguments(pin, profile, ROOT / ".cache/armbian/source"), indent=2))
        return
    if args.action == "check":
        check()
        return
    cache = owned_cache()
    with (cache / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another Northforge Armbian build is already running in this checkout") from exc
        container = None
        if args.action == "build":
            check()
            container = resolve_container(container_reference(pin))
        source, metadata = prepare(pin, profile, cache, mode, container)
        if args.action == "build":
            started = time.time()
            run(direct_arguments(pin, profile, source, container["image_id"]), cwd=source)
            collect(source, metadata, started)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"Northforge Forge: {error}", file=sys.stderr)
        sys.exit(1)
