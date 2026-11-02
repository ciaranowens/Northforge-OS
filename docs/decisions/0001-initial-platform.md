# ADR 0001: Establish the virtual reference platform first

Status: accepted for initial development.

Use Debian 13 Trixie and a pinned Armbian framework revision, with an x86-64
UEFI QEMU target as the initial boot-test platform. Keep the hardware profile
separate from Northforge rootfs customisation. The production ARM64 board is
undecided, so hardware-derived claims remain unavailable.

Use Armbian's supported Docker/userpatches interfaces instead of maintaining
local source edits or requiring developers to customize an upstream checkout.
Build source revision and configuration accompany each artifact. Package
archives are not fully frozen, so repeatable source inputs do not yet imply
byte-identical images.

Use initramfs-tools and OverlayFS for the first disposable-runtime mechanism.
Retain only manifest-listed state from encrypted persistence. This establishes
a testable reboot property before adding dm-verity, verified boot, or A/B
updates. OverlayFS and read-only mounts are not a complete trust chain.

Evaluate RAUC for future updates rather than inventing a signing/slot protocol.
Do not assign production partitioning or verified-boot guarantees until its
bootloader integration and recovery are tested.

Builds are serialized on the dedicated 6 GB VM. Production signing is outside
that VM. Pull requests run lightweight hosted checks and do not execute
privileged image builds.
