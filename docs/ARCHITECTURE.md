# Architecture

Northforge separates the disposable operating system from explicitly authorised
state. Debian 13 Trixie supplies userspace. A pinned Armbian framework supplies
the initial board integration and image assembly. Northforge customisation
remains in this repository rather than in a manually modified upstream tree.

The first target is x86-64 UEFI under QEMU. It is a development reference
platform, not evidence about any Banana Pi, modem, TPM, switch ASIC, or ARM
firmware. Target profiles must state capabilities before code relies on them.

## Build and boot

`build/armbian.sh` stages the pinned framework and supported `userpatches`
customisation, builds inside Armbian's Docker environment, and collects images
with source/build metadata and SHA-256 checksums. Two compilation threads and
disabled BTF/tmpfs limit pressure on the 6 GB build VM. Network package sources
can change even when source commits are pinned; bit-identical reproducibility
is not claimed.

The image identifies itself through `/usr/lib/os-release`. Northforge's
initramfs-tools `local-bottom` integration remounts the lower root read-only
before systemd starts. OverlayFS supplies a disposable writable runtime backed
by a dedicated GPT `NF-RUNTIME` partition. Each boot creates a dm-crypt mapping
with a fresh random key, formats its disposable filesystem, and uses it for
the overlay upper/work directories. The lower root is visible at
`/run/northforge/lower`. The implementation status records whether these paths
have been exercised in QEMU; code existence is not boot-test evidence.

## State boundaries

| Location | Intended treatment |
| --- | --- |
| Lower system image | Read-only after early boot; replaced by image builds |
| `/etc` | Disposable overlay; approved configuration only through explicit binds |
| `/run`, `/tmp`, `/var/tmp` | Disposable; never a hidden persistence mechanism |
| `/var/log` | Bounded volatile journal by default |
| `/persist` | Optional encrypted state; no automatic plaintext fallback |
| `/secure` | Separate future encrypted volume; not automatically unlocked |

A persistence manifest, `/etc/northforge/persistence.conf`, enumerates individual
approved source/target directory pairs. Supported targets are below
`/etc/northforge/config.d`, `/var/lib/northforge`, individual
`/var/lib/docker/volumes/*/_data` directories, and `/srv/northforge`. Broad binds
over the system root, executable directories, or all of `/etc` are rejected.
Directories must already be provisioned. No persistence is requested by default.
The optional LUKS2 mapper `northforge-persist` must be unlocked through an explicit
authorised credential until a hardware-backed policy has been implemented and
validated. Missing required encrypted storage stops activation rather than
silently using plaintext. This is integration with an unlocked mapping, not a
complete Vault provisioning or credential-recovery implementation.

Disk-backed disposable state avoids unbounded tmpfs use on the eventual NVMe
appliance. Fresh per-boot encryption keys make discarded state unreadable under
the dm-crypt key-erasure assumption, rather than relying on SSD overwrite
semantics. This property needs testing the actual runtime backing mode; it is
not supplied by OverlayFS alone. Journald is volatile and bounded to 32 MiB
with a one-day retention limit; there is not yet a persistent audit collector.

## Component boundaries

Base and Ephemeral are the first vertical slice. Later components remain
separate acceptance gates:

- BootGuard will authenticate the boot/root chain and express target-specific
  trust capabilities. Checksums stored beside writable images are insufficient.
- Recovery will integrate RAUC with actual A/B bootloader state and signed
  recovery; no custom imitation of atomic update metadata is needed now.
- Vault will provision LUKS2 state and independent `/secure` credentials. TPM2
  and FIDO2 claims require appropriate firmware, enrollment policy, and tests.
- Network will compile declarative LAN/WAN/VLAN policy to established Linux
  services and nftables, with validation and rollback of management changes.
- Control will expose a narrow authenticated administrative API and CLI.
- Apps will declare volumes, resources, and network attachments; containers
  will not receive the Docker socket, all host storage, or arbitrary host devices.

These components are not implemented merely by listing them here. Refer to the
status document before relying on a property.

## Build and release authority

Lightweight checks run on GitHub-hosted workers. Privileged image compilation
runs only after manual dispatch from reviewed `main` on the dedicated VM.
GitHub environment protection is an external administrative prerequisite, not
something a workflow file can create. Build serialization and bounded timeouts
protect the runner's resources; they do not sandbox privileged build code.

Ordinary build jobs receive no production signing keys. Passing a boot test can
publish short-lived development artifacts, not a production release. Production
signing, protected authorization, full test evidence, and recovery validation
remain separate gates.
