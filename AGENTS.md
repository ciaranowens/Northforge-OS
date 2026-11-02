# Northforge engineering

Read `docs/IMPLEMENTATION_STATUS.md` first. It records evidence and unfinished
acceptance gates; do not infer readiness from a component name or planned feature.
The architecture and threat model are in `docs/ARCHITECTURE.md` and
`docs/THREAT_MODEL.md`.

Northforge is an appliance-style Debian 13/Armbian system for a 5G router.
The production ARM64 board remains undecided. Develop board-independent behavior
against the UEFI x86-64 reference target. Never infer hardware security support.

Run `python3 tools/check.py` for source/unit checks. See `docs/BUILDING.md` and
`tests/qemu/README.md` for real image/boot tests. Treat a zero-test run, an open
port, or an incomplete set of serial markers as a failure. Keep failed, unrun,
hardware-pending and passing outcomes distinct. Update implementation status
alongside substantive changes.

Use the existing isolated cloud checkout; do not create worktrees unless asked.
Builds on the dedicated 6 GB VM must use conservative settings and one heavyweight
build at a time. Do not run privileged self-hosted CI for arbitrary PRs/forks.
Never expose the Docker socket or host credentials to build/test containers.

Storage operations must target generated image files or explicitly selected
disposable guest disks. Never partition or erase the build host's disks. Keep
TLS verification, package signatures and pinned artifact checks intact. Do not
embed credentials, private signing keys or session CAs in shipped images.

The current ephemeral root is **not authenticated verified boot**. Later gates
include dm-verity, an authenticated boot chain, atomic A/B updates and trusted
recovery. Do not describe read-only mounts or checksums as those guarantees.
