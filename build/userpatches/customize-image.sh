#!/bin/bash
set -euo pipefail
test "$1" = trixie
test "${5:-}" = amd64
cp -a /tmp/overlay/northforge-rootfs/. /
mkdir -p /var/lib/northforge /etc/northforge/config.d /srv/northforge /persist /secure
if [ -d /tmp/overlay/northforge-tests ]; then
    cp -a /tmp/overlay/northforge-tests/. /
fi
version=$(cat /tmp/overlay/northforge-version)
install -d /usr/lib/northforge
install -m 0644 /tmp/overlay/northforge-build.json /usr/lib/northforge/build.json
dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n' > /usr/lib/northforge/packages.tsv
cat > /usr/lib/os-release <<EOF
NAME="Northforge OS"
PRETTY_NAME="Northforge OS $version (Debian 13 Trixie)"
ID=northforge
ID_LIKE=debian
VERSION="$version"
VERSION_ID="$version"
VERSION_CODENAME=trixie
HOME_URL="https://github.com/ciaranowens/Northforge-OS"
EOF
ln -sf ../usr/lib/os-release /etc/os-release
printf 'Northforge OS %s (development; verified boot not established)\n' "$version" > /etc/issue
printf 'northforge\n' > /etc/hostname
# No upstream default root password, first-run credential wizard or remote daemon.
usermod --password '!' root
systemctl disable armbian-firstrun.service armbian-resize-filesystem.service 2>/dev/null || true
systemctl mask ssh.service ssh.socket 2>/dev/null || true
rm -f /root/.not_logged_in_yet
# The pinned grub extension's generic-kernel path does not regenerate initramfs
# after customize-image.sh. Explicitly include Northforge's early-boot files.
update-initramfs -u -k all
