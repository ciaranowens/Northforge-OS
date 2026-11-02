#!/bin/sh
# Shared by the initramfs and unit tests. Do not source writable configuration.

northforge_valid_component_path()
{
    case "$1" in
        ''|/*|*/|*//*|*[!A-Za-z0-9_./-]*) return 1 ;;
    esac
    case "/$1/" in */./*|*/../*) return 1 ;; esac
    return 0
}

northforge_valid_persistence_pair()
{
    northforge_valid_component_path "$1" || return 1
    case "$2" in
        /etc/northforge/config.d|/etc/northforge/config.d/*|\
        /var/lib/northforge|/var/lib/northforge/*|\
        /var/lib/docker/volumes/*/_data|\
        /srv/northforge|/srv/northforge/*) ;;
        *) return 1 ;;
    esac
    northforge_valid_component_path "${2#/}" || return 1
}

# Print normalized declarations. Reject malformed/duplicate/overlapping mounts.
# This function intentionally never creates or mounts anything.
northforge_validate_manifest()
{
    manifest=$1
    declarations=
    [ -f "$manifest" ] || return 1
    while IFS=' ' read -r source target remainder || [ -n "${source:-}" ]; do
        case "$source" in ''|\#*) continue ;; esac
        [ -n "$target" ] && [ -z "$remainder" ] || return 1
        northforge_valid_persistence_pair "$source" "$target" || return 1
        old_ifs=$IFS
        IFS='
'
        for declaration in $declarations; do
            old_source=${declaration%% *}
            old_target=${declaration#* }
            case "$source/" in "$old_source/"|"$old_source/"*) IFS=$old_ifs; return 1 ;; esac
            case "$old_source/" in "$source/"*) IFS=$old_ifs; return 1 ;; esac
            case "$target/" in "$old_target/"|"$old_target/"*) IFS=$old_ifs; return 1 ;; esac
            case "$old_target/" in "$target/"*) IFS=$old_ifs; return 1 ;; esac
        done
        IFS=$old_ifs
        declarations="${declarations}${declarations:+
}$source $target"
    done < "$manifest"
    [ -z "$declarations" ] || printf '%s\n' "$declarations"
}
