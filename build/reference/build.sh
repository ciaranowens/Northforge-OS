#!/usr/bin/env bash
# Debian-packaged kernel reference target for board-independent QEMU regression tests.
# The production board integration is build/armbian.sh. This target is unsigned.
set -Eeuo pipefail
umask 022

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
output="$repo/out/reference"
work_parent="$repo/.cache/reference"
fixture=no
ephemeral_fixture=no
reuse_root=
reuse_status_sha256=
mirror="${NORTHFORGE_DEBIAN_MIRROR:-https://deb.debian.org/debian}"
while (($#)); do
    case "$1" in
        --output) output=${2:?missing output directory}; shift 2 ;;
        --work-dir) work_parent=${2:?missing work directory}; shift 2 ;;
        --reuse-root) reuse_root=${2:?missing prepared root directory}; shift 2 ;;
        --test-fixture) fixture=yes; shift ;;
        --test-ephemeral) fixture=yes; ephemeral_fixture=yes; shift ;;
        -h|--help)
            printf '%s\n' 'Usage: build/reference/build.sh [--output DIR] [--work-dir DIR] [--test-fixture|--test-ephemeral]' \
                '       [--reuse-root PREPARED_ROOT]  # diagnostic rebuild only; copies the source tree' \
                'Run as root in a disposable privileged build container; never accesses host disks.'
            exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done
if [[ $(id -u) != 0 ]]; then
    echo 'Reference image build requires root inside an isolated build container.' >&2
    exit 1
fi
for tool in debootstrap chroot mount umount mountpoint mkfs.ext4 mkfs.vfat sgdisk mmd mcopy dd truncate python3 git sha256sum; do
    command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 1; }
done
[[ $mirror == https://* ]] || { echo 'The Debian mirror must use HTTPS.' >&2; exit 1; }
[[ -d "$repo/rootfs/etc" ]] || { echo 'Northforge rootfs overlay is missing.' >&2; exit 1; }
if [[ $fixture == yes && ! -d "$repo/tests/qemu/overlay" ]]; then
    echo 'QEMU fixture overlay is missing.' >&2
    exit 1
fi
if [[ $ephemeral_fixture == yes && ! -d "$repo/tests/qemu/ephemeral-overlay" ]]; then
    echo 'QEMU encrypted persistence fixture overlay is missing.' >&2
    exit 1
fi
if [[ -n $reuse_root ]]; then
    [[ -d $reuse_root && ! -L $reuse_root ]] || { echo 'Prepared root must be an existing directory, not a symlink.' >&2; exit 1; }
    reuse_root=$(realpath -e -- "$reuse_root")
    [[ $reuse_root != / ]] || { echo 'Refusing to reuse the running system root.' >&2; exit 1; }
    for path in etc usr var run; do
        [[ -d "$reuse_root/$path" && ! -L "$reuse_root/$path" ]] || {
            echo "Prepared root requires a real $path directory." >&2; exit 1;
        }
    done
    [[ -f "$reuse_root/etc/debian_version" && -f "$reuse_root/usr/bin/dpkg" && -s "$reuse_root/var/lib/dpkg/status" ]] || {
        echo 'Prepared root lacks Debian release and dpkg metadata.' >&2; exit 1;
    }
    for path in "$output" "$work_parent"; do
        resolved=$(realpath -m -- "$path")
        [[ $resolved != "$reuse_root" && $resolved != "$reuse_root/"* ]] || {
            echo 'Output and work directories must be outside the reused source root.' >&2; exit 1;
        }
    done
    reuse_status_sha256=$(sha256sum "$reuse_root/var/lib/dpkg/status")
    reuse_status_sha256=${reuse_status_sha256%% *}
fi
mkdir -p -- "$output" "$work_parent"
output=$(realpath -- "$output")
work_parent=$(realpath -- "$work_parent")
work=$(mktemp -d -- "$work_parent/build.XXXXXXXX")
root="$work/root"
mkdir -p "$root"
cleanup() {
    result=$?
    trap - EXIT
    for path in "$root/dev/pts" "$root/dev" "$root/sys" "$root/proc"; do
        if mountpoint -q "$path"; then umount -R "$path" || result=1; fi
    done
    rm -f -- "$root/run/northforge-build-ca.pem" "$root/usr/sbin/policy-rc.d"
    if ((result == 0)); then
        # work was created exclusively by mktemp. Do not clean unrelated caches.
        rm -rf --one-file-system -- "$work"
    else
        echo "Build failed; diagnostic work directory retained: $work" >&2
    fi
    exit "$result"
}
trap cleanup EXIT

# debootstrap uses wget outside the chroot. Configure its CA through a private
# build-only wgetrc; never disable TLS or Debian Release signature verification.
ca_bundle="${NORTHFORGE_CA_BUNDLE:-${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}}"
[[ -r "$ca_bundle" ]] || { echo 'Build CA bundle is unreadable.' >&2; exit 1; }
printf 'ca_certificate = %s\ncheck_certificate = on\n' "$ca_bundle" > "$work/wgetrc"
export WGETRC="$work/wgetrc"
if [[ -n $reuse_root ]]; then
    echo 'DIAGNOSTIC REBUILD: copying an existing prepared root; this is not a clean bootstrap.'
    cp -a --one-file-system -- "$reuse_root/." "$root/"
else
    debootstrap --arch=amd64 --variant=minbase --include=ca-certificates \
        --keyring=/usr/share/keyrings/debian-archive-keyring.gpg \
        trixie "$root" "$mirror"
fi

mkdir -p "$root/proc" "$root/sys" "$root/dev/pts" "$root/run"
mount -t proc proc "$root/proc"
mount --rbind /sys "$root/sys"
mount --make-rslave "$root/sys"
mount --rbind /dev "$root/dev"
mount --make-rslave "$root/dev"
cp -- "$ca_bundle" "$root/run/northforge-build-ca.pem"
printf '#!/bin/sh\nexit 101\n' > "$root/usr/sbin/policy-rc.d"
chmod 0755 "$root/usr/sbin/policy-rc.d"
printf 'deb %s trixie main\ndeb %s trixie-updates main\ndeb https://security.debian.org/debian-security trixie-security main\n' \
    "$mirror" "$mirror" > "$root/etc/apt/sources.list"
if [[ -z $reuse_root ]]; then
    chroot "$root" apt-get -o Acquire::https::CaInfo=/run/northforge-build-ca.pem update
    chroot "$root" env DEBIAN_FRONTEND=noninteractive apt-get \
        -o Acquire::https::CaInfo=/run/northforge-build-ca.pem \
        -y --no-install-recommends install \
        linux-image-amd64 systemd-sysv systemd-boot-efi initramfs-tools \
        cryptsetup-initramfs cryptsetup-bin e2fsprogs util-linux kmod busybox \
        dbus passwd
fi

cp -a -- "$repo/rootfs/." "$root/"
mkdir -p "$root/var/lib/northforge" "$root/etc/northforge/config.d" \
    "$root/srv/northforge" "$root/persist" "$root/secure"
if [[ $fixture == yes ]]; then cp -a -- "$repo/tests/qemu/overlay/." "$root/"; fi
if [[ $ephemeral_fixture == yes ]]; then cp -a -- "$repo/tests/qemu/ephemeral-overlay/." "$root/"; fi
version=$(cat "$repo/VERSION")
[[ $version =~ ^[A-Za-z0-9][A-Za-z0-9.+~-]*$ ]] || { echo 'VERSION contains unsupported characters.' >&2; exit 1; }
cat > "$root/usr/lib/os-release" <<EOF
PRETTY_NAME="Northforge OS $version (development)"
NAME="Northforge OS"
VERSION_ID="$version"
VERSION="$version (Debian 13 Trixie)"
ID=northforge
ID_LIKE=debian
VERSION_CODENAME=trixie
HOME_URL="https://github.com/ciaranowens/Northforge-OS"
SUPPORT_URL="https://github.com/ciaranowens/Northforge-OS/issues"
EOF
printf 'Northforge OS %s (development, unsigned)\\n\\l\n' "$version" > "$root/etc/issue"
printf 'northforge\n' > "$root/etc/hostname"
printf '127.0.0.1 localhost\n127.0.1.1 northforge\n::1 localhost ip6-localhost ip6-loopback\n' > "$root/etc/hosts"
printf 'LABEL=NF-ROOT / ext4 ro,errors=remount-ro 0 1\n' > "$root/etc/fstab"
# Never bake reusable identity, random seeds or login credentials into the image.
chroot "$root" passwd -l root
: > "$root/etc/machine-id"
rm -f "$root/var/lib/dbus/machine-id" "$root/var/lib/systemd/random-seed"
ln -s /etc/machine-id "$root/var/lib/dbus/machine-id"
chroot "$root" update-initramfs -u -k all
chroot "$root" dpkg-query -W '-f=${Package}\t${Version}\n' > "$work/packages.tsv"
chroot "$root" apt-get clean
rm -f -- "$root/run/northforge-build-ca.pem" "$root/usr/sbin/policy-rc.d"
find "$root/var/lib/apt/lists" -type f -delete

kernel=$(find "$root/boot" -maxdepth 1 -name 'vmlinuz-*' -type f | sort -V | tail -n 1)
[[ -n $kernel ]] || { echo 'Guest kernel was not installed.' >&2; exit 1; }
initrd="$root/boot/initrd.img-${kernel##*/vmlinuz-}"
[[ -f $initrd ]] || { echo 'Guest initramfs was not generated.' >&2; exit 1; }
efi="$root/usr/lib/systemd/boot/efi/systemd-bootx64.efi"
[[ -f $efi ]] || { echo 'Debian systemd-boot EFI loader is missing.' >&2; exit 1; }

image="$work/northforge-reference.img"
esp="$work/esp.fat"
rootpart="$work/root.ext4"
disk_sectors=$((4096 * 1024 * 1024 / 512))
esp_start=2048
esp_sectors=$((512 * 1024 * 1024 / 512))
root_start=$((esp_start + esp_sectors))
root_sectors=$((2560 * 1024 * 1024 / 512))
root_end=$((root_start + root_sectors - 1))
runtime_start=$((root_end + 1))
truncate -s "$((disk_sectors * 512))" "$image"
sgdisk --clear --new="1:$esp_start:$((root_start - 1))" --typecode=1:ef00 \
    --change-name=1:NF-ESP --new="2:$root_start:$root_end" --typecode=2:8300 \
    --change-name=2:NF-ROOT --new="3:$runtime_start:$((disk_sectors - 34))" \
    --typecode=3:8300 --change-name=3:NF-RUNTIME "$image"
truncate -s "$((esp_sectors * 512))" "$esp"
mkfs.vfat -F 32 -n NF-ESP "$esp"
mmd -i "$esp" ::/EFI ::/EFI/BOOT ::/loader ::/loader/entries ::/northforge
mcopy -i "$esp" "$efi" ::/EFI/BOOT/BOOTX64.EFI
mcopy -i "$esp" "$kernel" ::/northforge/vmlinuz
mcopy -i "$esp" "$initrd" ::/northforge/initrd.img
printf 'default northforge.conf\ntimeout 0\neditor no\nauto-entries no\nauto-firmware no\n' > "$work/loader.conf"
printf '%s\n' 'title Northforge OS (development, unsigned)' \
    'linux /northforge/vmlinuz' 'initrd /northforge/initrd.img' \
    'options root=LABEL=NF-ROOT ro rootwait console=ttyS0,115200n8 panic=30' > "$work/northforge.conf"
mcopy -i "$esp" "$work/loader.conf" ::/loader/loader.conf
mcopy -i "$esp" "$work/northforge.conf" ::/loader/entries/northforge.conf
for path in "$root/dev/pts" "$root/dev" "$root/sys" "$root/proc"; do
    if mountpoint -q "$path"; then umount -R "$path"; fi
done
truncate -s "$(((root_end - root_start + 1) * 512))" "$rootpart"
mkfs.ext4 -q -F -L NF-ROOT -d "$root" "$rootpart"
dd if="$esp" of="$image" bs=512 seek="$esp_start" conv=notrunc,sparse status=none
dd if="$rootpart" of="$image" bs=512 seek="$root_start" conv=notrunc,sparse status=none
sgdisk --verify "$image"
mv -- "$image" "$output/northforge-reference.img"
cp -- "$work/packages.tsv" "$output/packages.tsv"
python3 "$repo/build/reference/manifest.py" --repo "$repo" --output "$output" --fixture "$fixture" \
    --ephemeral-fixture "$ephemeral_fixture" --mirror "$mirror" \
    --reused-root-status-sha256 "$reuse_status_sha256"
(cd "$output" && sha256sum northforge-reference.img manifest.json packages.tsv > SHA256SUMS)
echo "Reference image built: $output/northforge-reference.img"
