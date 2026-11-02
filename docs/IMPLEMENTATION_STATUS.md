# Implementation status

This file distinguishes source implementation from executed acceptance tests.
The initial vertical slice is a **development, unsigned, integrity-unverified**
x86-64 UEFI system. It is not a production router image or a verified boot chain.

## Feature evidence

| Feature | Status | Evidence / remaining gate |
| --- | --- | --- |
| Debian 13 UEFI reference image | Implemented; clean-built and QEMU tested | Real debootstrap image, Debian packaged kernel and systemd-boot; clean final build evidence below |
| Northforge identity | Implemented; QEMU tested | Guest `/usr/lib/os-release`, running systemd, and serial assertions |
| Armbian source integration | Implemented; configuration tested; full build blocked | Pin `8de11a017f7f05a82c77850f8322928cb6a3b70c`; prepare/config-dump tests passed; current network blocker below |
| Read-only lower root and disposable overlay | Implemented; QEMU tested | Lower write rejected; undeclared `/etc` file disappeared on second boot |
| Approved persistent directory binds | Implemented; QEMU tested with test fixture | Manifest parser and LUKS2-backed directory survived reboot; production enrollment/unlock still pending |
| Encrypted disposable runtime | Implemented; QEMU tested | Fresh random-key plain dm-crypt mapping on dedicated `NF-RUNTIME`; actual encrypted ext4 backing and disk-based `/tmp` verified |
| Locked `/secure` | Read-only unavailable mount implemented; QEMU tested | Writes rejected; a separately encrypted FIDO2 volume is **not** implemented |
| Manifest/build provenance and SHA-256 | Implemented; unit tested | Records exact source revision, dirty state, inputs, packages and output hash; no signing/attestation claim |
| GitHub Actions | Implemented; Actionlint tested; remote execution unrun | Hosted checks and manual protected-runner build, selectable QEMU suite, bounded concurrency/artifact retention |
| dm-verity and authenticated boot | Planned | M2; writable boot storage and offline root modifications are not authenticated |
| RAUC A/B, health confirmation, rollback, recovery | Planned | Actual bootloader/storage integration and interrupted-update tests required |
| Production LUKS provisioning, TPM2 and FIDO2 | Planned / hardware pending | Test fixture uses a random QEMU-host credential and is not production provisioning |
| Network policy, management CLI/API, apps | Planned | No router isolation, modem, VLAN or managed-app guarantees yet |
| ARM64 board and hardware security | Hardware pending | Production board not selected; no Secure Boot, TPM, watchdog or hardware-firewall claims |
| Production release, SBOM signing and reproducibility | Planned | Package inventory exists; full SBOM/attestation and byte-identical reproducibility not established |

## Executed validation

- `python3 tools/check.py`: shell/Python syntax plus unit tests exercising
  persistence validation, safe cache handling, provenance and strict QEMU evidence.
  **35 tests passed**, plus syntax checks for 13 shell scripts.
- Actionlint v1.7.7: both workflow files passed (downloaded binary checksum verified).
- First real QEMU run failed at the formatter: BusyBox shadowed `mkfs.ext4`.
  The initramfs now copies the actual e2fsprogs binary to a unique path.
- A diagnostic rebuild reused the already prepared Debian root, regenerated the
  initramfs, and passed all 10 then-required two-boot assertions under UEFI/TCG
  in 72.86 seconds. Evidence:
  [reference-ephemeral-reused-root.json](evidence/reference-ephemeral-reused-root.json).
  This is explicitly not evidence of a clean rebuild.
- The first expanded clean-image test correctly failed because the early-boot
  wrong-key result shared a line with an initramfs message. Its output now starts
  a new console line; the strict parser was not relaxed.
- The final **clean-debootstrap build exited 0**. Its expanded UEFI/TCG test
  **passed all 13 required assertions across two boots in 75.28 seconds**,
  QEMU exited 0, no assertions were missing/failed, and the source disk hash
  remained unchanged. Evidence:
  [reference-ephemeral-clean.json](evidence/reference-ephemeral-clean.json).
- `sha256sum --check SHA256SUMS` verified image, manifest and package inventory.
  Image SHA-256:
  `4569aec73306015a783ad2b797170f2586690a18361190aedc22dfd313454ec2`.
  [Image input manifest](evidence/reference-image-manifest.json) and
  [actual guest package versions](evidence/reference-packages.tsv) are committed.
  All 25 recorded input files/symlinks were checked against the final source.
  The build accurately records a dirty development tree based on the initial
  repository commit; it is not a signed attestation of the later milestone commit.
- `bash tools/setup-dev.sh` completed using the managed Docker daemon and CA.
  It built the pinned-base tools container and passed the source/unit checks.

The final clean build/test commands, from the repository root, were:

```sh
docker --host=unix:///var/run/docker.sock run --rm --privileged \
  --mount type=bind,src="$PWD",dst=/src \
  --mount type=bind,src=/etc/ssl/certs/ca-certificates.crt,dst=/run/build-ca.pem,readonly \
  -e SSL_CERT_FILE=/run/build-ca.pem -e NORTHFORGE_CA_BUNDLE=/run/build-ca.pem \
  northforge-tools:dev bash build/reference/build.sh --test-ephemeral
docker --host=unix:///var/run/docker.sock run --rm --user "$(id -u):$(id -g)" \
  --mount type=bind,src="$PWD",dst=/src northforge-tools:dev \
  python3 tests/qemu/run.py --image out/reference/northforge-reference.img \
  --mode ephemeral --work-dir artifacts/qemu/reference-final --timeout 900
```

Use a new QEMU results directory when repeating the test; the harness refuses
to overwrite existing evidence. The image is an opt-in test image, with no
production credentials and a guest fixture that reboots and powers off.

The first packaging command also failed because a build script was edited while
its shell was still reading it. The subsequent stable-source full build exited
successfully; no partial packaging output was counted as a successful build.

## Armbian environment blocker

An actual build was attempted with the accepted Debian Trixie tools container
(direct launch, no Docker socket or credential mounts). Host dependency setup
completed. It then exited **56** downloading
`https://bootstrap.pypa.io/get-pip.py`: `CONNECT tunnel failed, response 403`.
The environment's restricted outbound policy does not allow that destination.
Adding `bootstrap.pypa.io` was saved to the environment configuration draft;
the draft does not apply the runtime change. No bypass or TLS disabling was used.

Reproduce from the repository root after applying that domain in environment
settings (further required destinations may be discovered by the next stage):

```sh
NORTHFORGE_ARMBIAN_CONTAINER_IMAGE=northforge-tools:dev \
NORTHFORGE_BUILD_CA=/etc/ssl/certs/ca-certificates.crt \
NORTHFORGE_TEST_MODE=smoke build/armbian.sh build uefi-x86
```

The tools image is built from `build/Containerfile.tools`. The default pinned
official Armbian container also exists as a supported build choice. Its layers
consumed approximately 34 GiB on this machine's Docker `vfs` driver, leaving
only 22 GiB and correctly failing the unchanged 40 GiB preflight. Only that
newly pulled unused image was removed to recover space; no global pruning ran.

Automatic approval review rejected a proposed nested build container carrying
the Docker socket and registry configuration. The implemented direct launcher
avoids those mounts; that safer launch was executed and reached the network
blocker above. The rejected design was not used.

## Milestone acceptance and next work

M0's reference image and build/test foundation are implemented, but M0's complete
Armbian and GitHub-runner acceptance remains blocked/unrun. M1's core disposable
root and explicit persistence behavior has real QEMU evidence on the reference
target; it is not yet validated on the Armbian-generated or physical ARM image.

Next: unblock and boot-test the Armbian image on the VM; configure the dedicated
runner's labels and required environment reviewers as described in BUILDING.
Then implement M2 with RAUC, an actual A/B bootloader layout, authenticated root
images and trusted recovery, including tamper and power-interruption tests.
No production release or remote workflow was triggered from this session.
