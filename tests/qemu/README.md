# QEMU acceptance tests

These tests boot an actual uncompressed GPT image with UEFI firmware. They use
KVM when `/dev/kvm` is accessible, otherwise QEMU TCG. They do not open a root
shell, attach a physical disk, or enable guest networking.

Required host tools: Python 3, `qemu-system-x86_64`, `qemu-img`, `sfdisk`, and
OVMF. Debian provides these in `python3 qemu-system-x86 qemu-utils fdisk ovmf`.

Build an explicitly labelled **test image** with `tests/qemu/overlay` installed.
For the ephemeral suite also install `tests/qemu/ephemeral-overlay` and rebuild
the initramfs. Test fixtures must not be installed in production releases.

```sh
python3 tests/qemu/run.py --image out/reference/northforge-reference.img \
    --mode smoke --work-dir artifacts/qemu/smoke --timeout 600
python3 tests/qemu/run.py --image out/reference/northforge-reference.img \
    --mode ephemeral --work-dir artifacts/qemu/ephemeral --timeout 900
```

Each work directory must be new or empty. `results.json`, `serial.log`, and
`qemu.log` belong to that run. A matching per-run nonce, every required assertion,
no failure markers, and a clean QEMU exit are required for success. A guest that
boots without running the tests fails. A previous run's logs cannot pass a new
run. The source image SHA-256 must remain unchanged; all guest writes go into a
qcow2 overlay.

The harness copies OVMF variables for every run. The default firmware is
**unverified UEFI**, not Secure Boot. Choose a matching firmware code/variables
pair with `--ovmf-code` and `--ovmf-vars` when automatic discovery is unsuitable.

The image normally contains a GPT partition named `NF-RUNTIME`. For legacy
images without one, the harness creates a disposable GPT runtime disk. An
explicit `--runtime-disk` must contain exactly one partition named `NF-RUNTIME`
and is rejected if it would create an ambiguous duplicate label.

The smoke fixture verifies Northforge OS identity and a running systemd PID 1,
then powers off. The ephemeral fixture checks an OverlayFS root, a read-only
lower mount, an ext4 upper/work filesystem on the plain-dm-crypt runtime mapper,
and disk-backed `/tmp` on that overlay. It verifies `/secure` is mounted read-only
and rejects writes; this does not establish an independently encrypted secure
volume or physical-credential unlock. It checks a LUKS2-backed `/persist` and
requires an actual wrong-key rejection (cryptsetup exit status 2), followed by a
successful unlock with the test credential. It writes an undeclared `/etc` file
and approved data under `/var/lib/northforge`, then reboots the same guest. On
the second boot it verifies the undeclared file disappeared, approved data
survived, and selected immutable base files have unchanged SHA-256 hashes.

In ephemeral mode the harness creates a separate disposable test partition named
`NF-TEST-PERSIST`. A **test-only** initramfs hook initialises that blank partition
as LUKS2, labels it `NF-PERSIST`, and unlocks it on subsequent boots. Its random
64-byte credential is generated at runtime in the private results directory
(mode 0600), passed using QEMU `fw_cfg`, and never included in the OS image. The
test KDF uses a bounded 32 MiB Argon2id memory cost suitable for the VM fixture;
this is not a production provisioning policy. The test key and disk are
development secrets: keep the whole results directory private and exclude them
from uploaded artifacts. Only upload the three evidence files named above.

Use `--persist-disk` and `--test-key-file` only for an explicitly selected test
fixture. The persistent disk is attached through a writable qcow2 overlay,
never directly. A wrong key fails closed. These tests do not establish TPM,
FIDO2, verified boot, dm-verity, A/B recovery, or physical-board support.
