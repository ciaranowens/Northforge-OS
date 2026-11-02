# Northforge OS

Northforge OS is a Debian 13 (Trixie) appliance distribution for networking
devices and a future ARM64 5G router. Its goal is to reconstruct a clean system
on every boot and retain only explicitly approved encrypted state.

Development starts with an x86-64 UEFI virtual-machine target, a fast Debian
reference builder, and pinned Armbian integration for the board-support path.
The production ARM64 board is not selected. See
[implementation status](docs/IMPLEMENTATION_STATUS.md) for the distinction
between implemented code, executed tests, and pending hardware work.

## Build and test

Use a dedicated Linux x86-64 build VM with Docker, Git, Python 3, at least 6 GB
RAM, and at least 40 GiB free disk space. QEMU tests also require
`qemu-system-x86`, `qemu-utils`, `fdisk`, and `ovmf`.

```sh
build/armbian.sh check
build/armbian.sh plan
build/armbian.sh build uefi-x86
python3 tools/check.py
```

Builds use the pinned Armbian revision and repository-owned customisations;
do not manually patch a separate Armbian checkout. Images, checksums, and
manifests are generated under `out/armbian/`.

[Build instructions](docs/BUILDING.md) describe the self-hosted runner, optional
test fixtures, resource limits, outputs, and reproducibility limitations.
[Architecture](docs/ARCHITECTURE.md), the [threat model](docs/THREAT_MODEL.md), and
[decisions](docs/decisions/0001-initial-platform.md) describe the security
boundaries and planned milestones.

These are development images. Read-only storage and discarded runtime changes
do not authenticate firmware, bootloaders, kernels, or root images. Secure Boot,
dm-verity, atomic A/B recovery, TPM/FIDO2 provisioning, and hardware firewall
guarantees require their own implementation and validation gates.

Northforge-specific source is licensed under GPL-2.0-only; see [LICENSE](LICENSE).
Debian, Armbian and other upstream components retain their respective licenses.
