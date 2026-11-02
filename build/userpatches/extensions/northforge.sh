#!/usr/bin/env bash
# Supported Armbian extension hooks; no upstream source patching.
function extension_prepare_config__northforge_packages() {
    add_packages_to_image initramfs-tools cryptsetup-initramfs cryptsetup-bin e2fsprogs util-linux busybox kmod systemd
}

function host_pre_docker_launch__northforge_build_trust() {
    if [[ -n "${NORTHFORGE_BUILD_CA:-}" ]]; then
        [[ -r "$NORTHFORGE_BUILD_CA" ]] || exit_with_error "Missing Northforge build CA bundle"
        DOCKER_EXTRA_ARGS+=(--mount "type=bind,src=${NORTHFORGE_BUILD_CA},dst=/run/northforge-build-ca.pem,readonly")
        DOCKER_EXTRA_ARGS+=(--env SSL_CERT_FILE=/run/northforge-build-ca.pem)
        DOCKER_EXTRA_ARGS+=(--env CURL_CA_BUNDLE=/run/northforge-build-ca.pem)
        DOCKER_EXTRA_ARGS+=(--env GIT_SSL_CAINFO=/run/northforge-build-ca.pem)
        DOCKER_EXTRA_ARGS+=(--env REQUESTS_CA_BUNDLE=/run/northforge-build-ca.pem)
        DOCKER_EXTRA_ARGS+=(--env APT_CONFIG=/armbian/userpatches/northforge-apt.conf)
    fi
    # Upstream explicitly forwards the outer proxy variables. Its hostname may
    # only exist in the outer container's hosts file; reproduce that resolution
    # without replacing or bypassing the proxy.
    local proxy_host proxy_ip
    proxy_host=$(python3 -c 'import os,urllib.parse; print(urllib.parse.urlparse(os.environ.get("HTTPS_PROXY", os.environ.get("https_proxy", ""))).hostname or "")')
    if [[ -n "$proxy_host" ]]; then
        proxy_ip=$(getent ahostsv4 "$proxy_host" | awk 'NR==1 { print $1; exit }')
        [[ -z "$proxy_ip" ]] || DOCKER_EXTRA_ARGS+=(--add-host "${proxy_host}:${proxy_ip}")
    fi
}

function pre_prepare_partitions__northforge() {
    # This initial target is UEFI-only; rootpart must stay at upstream's index 2.
    [[ "${BOARD}" == uefi-x86 && "${ARCH}" == amd64 ]] || exit_with_error "Northforge partition hook only supports uefi-x86 amd64"
    declare -g IMAGE_PARTITION_TABLE=gpt BIOSSIZE=0 BOOTSIZE=0
    declare -g USE_HOOK_FOR_PARTITION=yes
    declare -g EXTRA_ROOTFS_MIB_SIZE=$(( ${EXTRA_ROOTFS_MIB_SIZE:-0} + ${NORTHFORGE_RUNTIME_MIB:-1024} ))
}

function create_partition_table__northforge() {
    # sdsize/rootpart/uefipart are provided by Armbian prepare_partitions' scope.
    [[ "$rootpart" == 2 && "$uefipart" == 1 ]] || exit_with_error "Unexpected Armbian partition numbering"
    local runtime_mib=${NORTHFORGE_RUNTIME_MIB:-1024}
    local root_mib=$((sdsize - OFFSET - UEFISIZE - runtime_mib - 1))
    (( root_mib > rootfs_size )) || exit_with_error "Northforge root partition would be too small"
    local root_start=$((OFFSET + UEFISIZE)) runtime_start=$((OFFSET + UEFISIZE + root_mib))
    sfdisk "${SDCARD}.raw" <<EOF
label: gpt
1: name="NF-BOOT", start=${OFFSET}MiB, size=${UEFISIZE}MiB, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B
2: name="NF-ROOT", start=${root_start}MiB, size=${root_mib}MiB, type=${PARTITION_TYPE_UUID_ROOT}
3: name="NF-RUNTIME", start=${runtime_start}MiB, size=${runtime_mib}MiB, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4
EOF
    # Deliberately unformatted: NF-RUNTIME gets a fresh random-key encrypted
    # mapping each boot. Persistent storage requires separate explicit provisioning.
}

function pre_umount_final_image__northforge_readonly_fstab() {
    # The root is the overlay at runtime; underlying base and ESP remain read-only.
    # Armbian writes fstab after customize-image, so apply this at the final hook.
    awk 'BEGIN { OFS="\t" } /^[[:space:]]*#/ || NF < 4 { print; next }
         $2 == "/" || $2 == "/boot" || $2 == "/boot/efi" { $4="defaults,ro"; $6=0 }
         $2 != "/tmp" { print }' "$MOUNT/etc/fstab" > "$MOUNT/etc/fstab.northforge"
    mv "$MOUNT/etc/fstab.northforge" "$MOUNT/etc/fstab"
}
