# Initial threat model

This document describes the intended trust boundaries and current residual
risks. It does not assert that planned controls are implemented. Executed
evidence belongs in [implementation status](IMPLEMENTATION_STATUS.md).

## Assets and authority

Assets are the trusted operating-system image, device identity, network policy,
approved configuration, application data, encryption credentials, build inputs,
and release authority. Normal persistent state and `/secure` must use distinct
authorization; possession of a booted device is not authorization to unlock
the high-security volume.

Trust initially includes the build VM administrator, reviewed repository
maintainers, the pinned upstream build source, package-signing authorities,
the hypervisor, and the boot firmware. Builds run upstream code with substantial
privilege. A dedicated VM limits damage to other infrastructure but does not
make unreviewed build code safe.

## Threats and controls

| Threat | Required control | Current limit |
| --- | --- | --- |
| Unapproved runtime edits survive reboot | Immutable lower root, disposable upper, explicit persistence | Test reboot behavior; read-only mounts alone do not resist privileged writes |
| Storage image replaced offline | Authenticated boot chain and verified root | Development UEFI/unsigned images do not authenticate the OS |
| Broken or interrupted update removes working system | Inactive-slot install, verified artifacts, boot attempts, health confirmation, trusted recovery | A/B/RAUC integration is a later gate |
| Stolen disk reveals identity or application state | LUKS2, explicit unlock/recovery policy | Hardware-sealed unlock is not assumed |
| Boot automatically exposes high-security data | Independent physical credential for `/secure` | FIDO2 provisioning requires implementation and device tests |
| Compromised application crosses networks | Least-privilege container deployment plus host/hardware policy | Container namespaces cannot constrain fully compromised host root |
| IPv6 bypasses IPv4 firewall policy | Joint IPv4/IPv6 policy and isolation tests | Networking policy is a later milestone |
| Malicious pull request uses build host | Hosted PR checks; manually gated reviewed-main privileged builds | Repository and environment administrators remain trusted |
| Build job steals signing authority | Signing separated from build VM with protected release authorization | No production signing is provided by the initial pipeline |
| Logs exhaust storage or disappear after incident | Bounded runtime logs; opt-in encrypted/remote audit destination | Volatile logs lose previous-boot forensic evidence |

## Failure behavior

Integrity failure must eventually select verified fallback/recovery or stop
boot. An unauthenticated root shell is not a recovery mechanism. Early-boot
failure handling must not bypass required encrypted persistence or silently
remount a failed verified image read-write. Development fixtures must be
explicitly selected and excluded from production trust.

## Root compromise and hardware limits

Read-only mounts, namespaces, containers, software firewall rules, and a switch
ACL programmed by host root do not establish protection against that same
root account. A root attacker can alter runtime state, access unlocked data,
and reprogram available network hardware. Hardware-independent management
requires a separate authority and a protected configuration path.

Hardware-rooted boot claims require checking firmware keys, rollback state,
bootloader verification, kernel policy, authenticated root hashes, and recovery
on the selected physical board. The production board is undecided; no switch,
TPM, watchdog, secure-element, or modem capabilities are inferred.

## Out of scope for the initial slice

The first build/boot slice does not solve invasive physical attacks, malicious
firmware, compromised build administrators, traffic analysis, denial of service,
hardware side channels, or persistent compromise of external modem firmware.
These need explicit future analysis rather than blanket security claims.
