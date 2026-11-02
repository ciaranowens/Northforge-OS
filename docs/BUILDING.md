# Building and testing Northforge

Use `docs/IMPLEMENTATION_STATUS.md` for executed results. A documented command,
source check, generated workflow, or queued job is not evidence of a successful
image build. No workflow creates a production release.

## Dedicated build VM

The intended image builder is the existing Debian VM on the Ubuntu Intel NUC:
Linux x86-64, 6 GB RAM, optional swap, Docker, Git, and a systemd-operated
GitHub Actions runner. Reserve at least 40 GiB free disk space before an Armbian
build. Swap can help tolerate peaks, but does not make an under-sized filesystem
safe. Keep only a small number of images and do one heavyweight build at a time.

Install the host prerequisites using Debian's signed repositories:

```sh
sudo apt-get update
sudo apt-get install --no-install-recommends \
  git python3 docker.io util-linux fdisk qemu-system-x86 qemu-utils ovmf \
  dialog psmisc uuid-runtime curl gnupg gawk linux-base locales
```

The runner account needs access to the existing Docker daemon. Docker access is
effectively host-root authority; use the dedicated VM and do not offer it to
unreviewed pull requests. KVM access accelerates QEMU tests, but the harness can
use TCG when nested virtualization is unavailable. Boot tests allocate their
own disposable image overlays and firmware-variable copies.

No command in this repository should partition the build VM's boot disk. Image
assembly and tests must use generated files, containers, loop devices, and
explicitly selected disposable guest disks.

## Armbian image

```sh
build/armbian.sh check
build/armbian.sh plan
build/armbian.sh prepare
build/armbian.sh build uefi-x86
```

`prepare` is optional; `build` prepares its own pinned source and customisation.
The build wrapper is the source of truth for supported arguments and resource
checks. See [Armbian integration](ARMBIAN_INTEGRATION.md) for the pinned upstream
revision, target selection, exact flag verification, and supported hooks.

The conservative profile uses `KERNEL_BTF=no`, `CPUTHREADS=2`, `USE_TMPFS=no`,
`BUILD_MINIMAL=yes`, `RELEASE=trixie`, and `KERNEL_CONFIGURE=no`. These are
validated against the pinned framework rather than guessed for a future version.
Do not start another kernel/image build alongside this job on the 6 GB VM.

Outputs are:

- `out/armbian/northforge-uefi-x86.img` — development disk image.
- `out/armbian/release-manifest.json` — source revision, configuration, and artifact metadata.
- `out/armbian/SHA256SUMS` — artifact checksums; not a signature or authenticated boot policy.

Source revisions and configuration are pinned. Package mirrors and timestamps
are not fully normalized; bit-for-bit reproducibility has not been established.
The term "release manifest" names an artifact format, not production approval.

## Faster Debian reference image

The complementary reference builder exercises the board-independent Northforge
rootfs and boot mechanism without compiling a kernel. It uses Debian's signed
Trixie package archive, `debootstrap`, the Debian-packaged amd64 kernel, and
systemd-boot. It does not replace or validate the Armbian board-support build.
Its UEFI image is unsigned and is not a production verified-boot image.

From the repository root on the dedicated Docker-capable host:

```sh
DOCKER_BUILDKIT=1 docker build -f build/Containerfile.tools \
  --tag northforge-tools:dev .
docker run --rm --privileged \
  --mount "type=bind,src=$PWD,dst=/src" \
  northforge-tools:dev bash build/reference/build.sh --test-ephemeral
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$PWD,dst=/src" \
  northforge-tools:dev python3 tests/qemu/run.py \
  --image out/reference/northforge-reference.img --mode ephemeral \
  --work-dir artifacts/qemu/reference-ephemeral --timeout 900
```

`bash tools/setup-dev.sh` is the tested convenience setup for the local Docker
daemon; it builds the tools image, supplies the managed proxy CA when present,
and runs the lightweight checks. It does not start a background service.

The tools container's base image is pinned by digest. The build container needs
privileged mount/chroot capability; the QEMU TCG command does not need host disk
devices or privileged mode. For accelerated tests, explicitly expose only
`/dev/kvm` if it is available. Do not expose the Docker socket to the guest.

In a managed cloud environment, retain its configured proxy and use the runtime
skill's CA guidance. Supply the public CA bundle through BuildKit's
`--secret id=proxy_ca,src=...` and a read-only runtime mount with
`SSL_CERT_FILE=/run/build-ca.pem` as appropriate. Do not disable TLS or package
signature checks and do not bake the session CA into a shipped image.

The reference image is a 4 GiB GPT disk containing an EFI system partition,
`NF-ROOT`, and a disposable `NF-RUNTIME` partition. Outputs are
`out/reference/northforge-reference.img`, `manifest.json`, `packages.tsv`, and
`SHA256SUMS`. Run `sha256sum --check SHA256SUMS` in that output directory to
check the generated artifacts. The manifest records that the kernel provider
is Debian packages, not Armbian.

Omit `--test-ephemeral` for an image without guest test fixtures, or use
`--test-fixture` for smoke-only tests. The persistence fixture uses disposable
test storage and a runtime-generated credential, never an embedded production
key. [QEMU test instructions](../tests/qemu/README.md) explain fixture handling
and evidence. Do not upload entire QEMU work directories containing test keys
and disks. Refer to implementation status for which commands actually ran.

## Local checks and QEMU

```sh
python3 tools/check.py
NORTHFORGE_TEST_MODE=smoke build/armbian.sh build uefi-x86
python3 tests/qemu/run.py \
  --image out/armbian/northforge-uefi-x86.img \
  --mode smoke --work-dir artifacts/qemu/smoke --timeout 600
```

The explicit test-image build installs the guest fixture. A normal image must
not run a power-off/reboot test service on every boot. The smoke harness checks
serial evidence from the running guest rather than treating an open process or
zero-test suite as success. `--accel tcg` forces software emulation. Use a new
work directory for each test run and retain `results.json` and serial logs as
evidence.

The ephemeral test mode requires an explicitly provisioned persistence fixture
and the disposable-runtime configuration. Do not report persistence, LUKS,
tamper rejection, A/B rollback, or hardware unlock tests as passed merely because
a base smoke test succeeded. The current status document identifies which
scenarios have actually run.

Test-fixture images deliberately reboot/power off under the harness. Normal
images omit that fixture, lock the root account and expose no default password
or remote root service. Production administrator enrollment and a controlled
management interface remain unimplemented; these images are not ready for
deployment as a working router.

## GitHub Actions and runner protection

`Source checks` runs on GitHub-hosted runners for pull requests and `main`.
`Development image` is manually dispatched from `main`, checks source and the
build VM, compiles a test image, boots it with UEFI QEMU, and uploads short-lived
development artifacts only after the boot test passes. Logs are retained on
failure. Workflows use pinned action commits and read-only repository tokens.
The dispatch input selects `ephemeral` (default, including a reboot and encrypted
persistence assertions) or `smoke` (identity and userspace only). Guest fixtures
and the harness must use the same selected mode.

Before enabling the image workflow, the repository administrator must:

1. Protect `main` with required reviews and required source checks. Review changes
   to workflows, build code, rootfs hooks, and upstream pins as privileged code.
2. Configure the `northforge-build` GitHub environment with required reviewers,
   prevent self-review, and allow deployment only from protected
   `main`. Creating an environment name in YAML does not create these controls.
3. Give the existing dedicated runner the labels `self-hosted`, `linux`, `x64`,
   and `northforge`. Restrict that runner or runner group to the intended trusted
   repository/workflow where the GitHub plan supports it.
4. Install the host dependencies and verify the runner account can reach Docker.

The scheduler requires every listed label. A missing/offline runner leaves the
job queued before its environment checks can run; inspect the repository's
Actions runner settings if the job never starts. The job itself validates the
selected runner's OS/architecture, required tools, memory, disk, and Docker.

Do not enable the image workflow without these external protections. GitHub
creates a referenced environment with no reviewers if it does not already
exist; the YAML alone cannot establish that an administrator configured it.
If the GitHub plan cannot enforce environment review, an appropriate protected
runner/repository authorization arrangement is still required before use.

The repository-wide `northforge-heavyweight` concurrency group serializes jobs
from this workflow; avoid independently launching manual builds outside that
lock. A job has a bounded timeout. Cleanup must stay within each build's owned
paths and containers; do not use global `docker system prune` or broad disk wipes.

## Production release boundary

This first pipeline publishes development CI artifacts, not signed production
releases. Production signing keys must remain outside the ordinary build VM.
Production release authorization, authenticated manifests, verified boot,
rollback-safe update/recovery tests, and protected signing infrastructure remain
separate gates. Do not relabel a test image as production or install a guest test
credential into production trust.
