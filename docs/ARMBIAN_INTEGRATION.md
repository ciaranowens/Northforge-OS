# Armbian integration evidence

The initial profile uses Armbian's generic `uefi-x86` board and its supported
GRUB extension with Debian's generic `linux-image-amd64` kernel. This avoids
compiling a large PC kernel on the 6 GB build VM. It does not establish support
for a particular ARM64 board. An ARM profile must select and validate its own
Armbian board/kernel/firmware and boot mechanism.

## Pinned framework

`config/armbian.json` pins release tag `v26.5.1` to commit
`8de11a017f7f05a82c77850f8322928cb6a3b70c` from
<https://github.com/armbian/build>. The commit, not the tag, controls checkout.

Authoritative source references at that exact revision:

| Contract | Source |
| --- | --- |
| Generic UEFI amd64 board; `legacy` is a listed branch | [`config/boards/uefi-x86.conf`](https://github.com/armbian/build/blob/8de11a017f7f05a82c77850f8322928cb6a3b70c/config/boards/uefi-x86.conf) |
| Trixie is supported and includes amd64/arm64 | [`config/distributions/trixie/`](https://github.com/armbian/build/tree/8de11a017f7f05a82c77850f8322928cb6a3b70c/config/distributions/trixie) |
| `DISTRO_GENERIC_KERNEL=yes` selects signed Debian kernel packages and no source kernel build | [`extensions/grub.sh`](https://github.com/armbian/build/blob/8de11a017f7f05a82c77850f8322928cb6a3b70c/extensions/grub.sh) |
| Named user configuration `./compile.sh northforge`; `lib.config` late overrides | [`lib/functions/cli/entrypoint.sh`](https://github.com/armbian/build/blob/8de11a017f7f05a82c77850f8322928cb6a3b70c/lib/functions/cli/entrypoint.sh), [`lib/functions/configuration/main-config.sh`](https://github.com/armbian/build/blob/8de11a017f7f05a82c77850f8322928cb6a3b70c/lib/functions/configuration/main-config.sh) |
| `customize-image.sh` runs inside image; overlay read-only mounted at `/tmp/overlay` | [`lib/functions/rootfs/customize.sh`](https://github.com/armbian/build/blob/8de11a017f7f05a82c77850f8322928cb6a3b70c/lib/functions/rootfs/customize.sh) |
| Custom partition table and final filesystem hooks | [`lib/functions/image/partitioning.sh`](https://github.com/armbian/build/blob/8de11a017f7f05a82c77850f8322928cb6a3b70c/lib/functions/image/partitioning.sh), [`lib/functions/image/rootfs-to-image.sh`](https://github.com/armbian/build/blob/8de11a017f7f05a82c77850f8322928cb6a3b70c/lib/functions/image/rootfs-to-image.sh) |
| Docker launcher and `host_pre_docker_launch` extension hook | [`lib/functions/host/docker.sh`](https://github.com/armbian/build/blob/8de11a017f7f05a82c77850f8322928cb6a3b70c/lib/functions/host/docker.sh) |

## Resource settings checked against the pin

| Setting | Verified implementation and meaning |
| --- | --- |
| `KERNEL_BTF=no` | `lib/functions/compilation/armbian-kernel.sh`, `armbian_kernel_config__600_enable_ebpf_and_btf_info`: disables debug/BTF generation; does not disable eBPF. Has no kernel compilation to affect in the generic Debian-kernel VM profile. |
| `CPUTHREADS=2` | `lib/functions/configuration/compilation-config.sh`, `prepare_compilation_vars`: positive integer overrides `CTHREADS` to `-j2`. |
| `USE_TMPFS=no` | `lib/functions/host/tmpfs-utils.sh`, `prepare_tmpfs_for`: skips the large host build tmpfs mounts. This does not remove the guest's ordinary `/run` tmpfs. |
| `BUILD_MINIMAL=yes` | `lib/functions/main/config-prepare.sh`: selects `cli_minimal` configuration, excluding additional nonminimal packages. |
| `RELEASE=trixie` | Distribution metadata above identifies Debian 13 Trixie as supported. |
| `KERNEL_CONFIGURE=no` | `lib/functions/configuration/interactive.sh` accepts an explicit value and skips the interactive menu. `artifact-kernel.sh` reserves `yes` for the dedicated kernel-config workflow. |

The image configuration also sets `BUILD_DESKTOP=no`, `CONSOLE_AUTOLOGIN=no`,
`INSTALL_ARMBIAN_FIRMWARE=no`, and `EXTRAWIFI=no` for the VM. Hardware profiles
must not copy the firmware choices without checking their actual requirements.

## Wrapper and output contract

From the repository root:

```sh
build/armbian.sh plan uefi-x86       # offline JSON of pin, profile and arguments
build/armbian.sh check uefi-x86      # prerequisites; does not start a build
build/armbian.sh prepare uefi-x86    # fetch exact commit and stage userpatches
build/armbian.sh build uefi-x86      # direct Armbian container build, then manifest
build/armbian.sh container-plan     # inspect single-container argv without running
```

The wrapper owns `.cache/armbian/` and refuses to overwrite an existing unmarked
cache. It locks this checkout's cache, refuses tracked changes in the cached
upstream checkout, and creates the complete userpatches tree from repository
source on each invocation. It does not require manual edits to upstream files.
GitHub Actions separately serializes heavyweight jobs on the dedicated VM.

Final outputs are `out/armbian/northforge-uefi-x86.img`,
`out/armbian/release-manifest.json`, and `out/armbian/SHA256SUMS`. Collection
requires exactly one raw image produced by the current build. An upstream
failure or a stale cached image cannot produce a successful new manifest.
Manifests record source commit/dirty status, framework pin, selected profile,
test-fixture mode, and image SHA-256. The guest includes
`/usr/lib/northforge/build.json` and a package/version inventory in
`/usr/lib/northforge/packages.tsv`.

The VM partition hook creates GPT with an EFI System partition, immutable-base
root partition, and a 1 GiB `NF-RUNTIME` partition. The runtime partition starts
unformatted and is used by the ephemeral initramfs mechanism. Approved persistent
storage is provisioned separately; no plaintext persistence is manufactured.
The default root account has no usable password, SSH is masked, and console
autologin is disabled. The current image has no general administration
provisioning path; QEMU tests run a narrowly scoped opt-in system service.

### QEMU test images

```sh
NORTHFORGE_TEST_MODE=smoke build/armbian.sh build uefi-x86
NORTHFORGE_TEST_MODE=ephemeral build/armbian.sh build uefi-x86
```

The default `none` mode excludes test fixtures. `smoke` adds the shared test
service; `ephemeral` additionally adds the test persistence manifest and unlock
hook. The latter reads a test credential from QEMU fw_cfg at runtime, rather
than baking keys into images. These are development images and must not be
promoted into a production trust policy.

### Host requirements and managed-cloud trust

The dedicated runner needs Linux x86-64, at least 5 GiB RAM (6 GB VM intended),
40 GiB free workspace disk, Python 3.11+, Git, Bash, local Docker socket access,
and privileged container loop/mount support. Only the wrapper's small host-side
dependency set is needed; all Armbian build dependencies stay inside the builder:

```sh
sudo apt-get update
sudo apt-get install --no-install-recommends git python3
```

Install Docker from its supported installation process. Only trusted code may
access this daemon: the image build uses privileged mount and loop operations.
The wrapper explicitly selects the local Docker daemon and clears inherited
Docker context/TLS endpoint selectors while retaining registry configuration.
It never wipes host disks or performs global Docker pruning.

The wrapper always uses a single-container launch:

```sh
NORTHFORGE_BUILD_CA=/etc/ssl/certs/ca-certificates.crt \
  NORTHFORGE_TEST_MODE=smoke build/armbian.sh build uefi-x86
```

It needs only Git, Python, Bash and Docker on the host. It invokes the
official Armbian build image from `config/armbian.json` as root with
`ARMBIAN_RUNNING_IN_CONTAINER=yes`, then runs the normal `./compile.sh northforge`
image command rather than recursively requesting Docker. This is the same
in-container build path used by Armbian's own launcher; see
`lib/functions/cli/utils-cli.sh`, `cli_standard_relaunch_docker_or_sudo`.
The only mounts are its generated source cache and optional public CA bundle.
It never mounts the Docker socket, Docker configuration or registry credentials
into the builder. The single image-building container still requires privileged
loop/mount access; it must only run reviewed code in the dedicated build VM.
Registry authentication remains with the host Docker client/daemon. The upstream
Docker launcher is deliberately not used: under GitHub Actions it can mount the
host's Docker configuration inside the builder. Setting the obsolete
`NORTHFORGE_ARMBIAN_LAUNCH=upstream` is rejected rather than enabling that route.

An explicitly selected lean builder can be used in direct mode, for example
`NORTHFORGE_ARMBIAN_CONTAINER_IMAGE=northforge-tools:dev` after building this
repository's `build/Containerfile.tools`. The pinned framework's
`lib/functions/host/host-release.sh` accepts Debian Trixie, and its
`prepare-host.sh` selects Trixie host dependencies; no unsupported-host override
is used. Upstream comments still identify Ubuntu as the primary fully supported
host, so a successful Trixie configuration check alone is not a completed build.
Armbian installs any remaining host dependencies inside that disposable builder
through its normal signed-package process. The wrapper resolves the selected
reference to its immutable local Docker image ID before running, then records
both values in the guest build metadata and final release manifest. This can
avoid the large unpacked official builder consuming most of a Docker `vfs`
filesystem. The 40 GiB free-disk preflight is unchanged.

In this managed cloud, supply the public combined CA bundle when its proxy
requires additional trust:

```sh
NORTHFORGE_BUILD_CA=/etc/ssl/certs/ca-certificates.crt \
  NORTHFORGE_TEST_MODE=smoke build/armbian.sh build uefi-x86
```

The wrapper bind-mounts the CA bundle read-only into the build container and
configures Git, curl, TLS consumers and APT to use it. It retains the inherited
proxy and supplies its host resolution to the build container. It does not
copy the session CA into the target filesystem or disable signature/TLS checks.
Docker daemon pulls still rely on the daemon's/platform's existing trust
configuration. An access denial needs an
environment policy change, not a proxy bypass.

## Validation evidence and limits

During implementation the wrapper fetched and checked out the exact pin. The
following command completed against that checkout and loaded the actual
Northforge configuration and extension:

```sh
cd .cache/armbian/source
CONFIG_DEFS_ONLY=yes ./compile.sh config-dump-json northforge \
  BOARD=uefi-x86 BRANCH=legacy RELEASE=trixie BUILD_MINIMAL=yes \
  BUILD_DESKTOP=no KERNEL_CONFIGURE=no KERNEL_BTF=no CPUTHREADS=2 USE_TMPFS=no
```

Its output confirmed `ARCH=amd64`, `DISTRO_GENERIC_KERNEL=yes`,
`DISTRO_KERNEL_PACKAGES=linux-image-amd64`, `KERNELSOURCE=none`,
`BOOTCONFIG=none`, `UEFI_GRUB_TARGET=x86_64-efi`, `SERIALCON=ttyS0`, and the
Northforge package additions. This is configuration validation, not an image
build or boot test. Current build and QEMU outcomes are recorded separately in
`IMPLEMENTATION_STATUS.md`.

The framework commit and Northforge source are recorded. The default upstream
container is pinned by registry digest in `config/armbian.json`; an explicit
local image override records its resolved image ID. Debian package repositories
are not snapshot pinned and can change. Package inventories expose the resolved versions, but
byte-identical reproducibility has not been established. There is no verified
boot, dm-verity, release signature, rollback counter or hardware security claim
in this initial profile. Production signing and trust enrollment remain separate
work, with private keys excluded from ordinary builders.
