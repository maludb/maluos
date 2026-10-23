# Phase 11 slice 2: the engine and the unattended install

Specified 2026-10-23 from docs/phase11-installer.md (decisions 2, 4, 5,
8; the owner's answers 1, 2, 3 and 4), docs/install-plan.md (the plan
is the contract; this page is what executes it) and slice 1
(docs/phase11-slice1-live.md, the media it runs from). Nothing here is
built. It is sequenced after slice 1 in docs/roadmap.md (E1).

## What the slice delivers

`maluos-install --plan` installs MaluOS from the live medium onto a
disk without a screen: guided layouts (direct or LVM, ext4 or xfs, LUKS
optional), the image verified and unpacked, the target configured, the
bootloader written for BIOS and UEFI with Secure Boot, the first-boot
file seeded, one telemetry report when the plan says so, reboot. The
media carries an unattended plan for each variant behind a menu entry,
a headless machine is installed over SSH, and the ISO boot test drives
the whole path on BIOS and UEFI. No screen yet: a medium booted without
a plan still lands in the slice 1 shell.

```
sudo maluos-install --plan /cdrom/maluos/plan/server-unattended.yaml
sudo maluos-install --plan https://example.com/plans/db-2.yaml [--check | --dry-run] [--json]
sudo maluos-install --resume                 # after a failed step, from the journal
maluos-install --telemetry-preview --plan …  # the report that would be sent, nothing sent
```

## What exists to build on

| Piece | Reused as |
|---|---|
| docs/install-plan.md | the schema the engine validates; the two examples become the media's plans and the tests' plans |
| autoinstall/late-commands*.yaml | the configure step's apt part (the on-media repository copy and `maluos-iso.sources`), the server's serial console, the desktop's `quiet splash`, `chage -d 0` for the unattended user |
| maluos-firstboot and /etc/maluos/firstboot.yaml | the `firstboot` section's target; the package gains the `enroll` key |
| slice 1: the live rootfs (parted, gdisk, lvm2, cryptsetup, dosfstools, e2fsprogs, squashfs-tools, efibootmgr, rsync), `maluos-installer.service`, `/maluos/images/`, `/maluos/SHA256SUMS`, the grub template | the tools, the console, the images, the menu |
| the target images' own packages (grub-pc-bin, grub-efi-amd64-signed, shim-signed, grub2-common, efibootmgr) | the bootloader step runs the target's grub-install in a chroot, so Secure Boot works as it does for Ubuntu |
| tests/iso-boot-test.sh, tests/iso-apt-check.sh, tests/qcow2-boot-test.sh | the install test on both firmwares, the apt replay against the new media, the Phase 4 checks on the installed system |
| the download site's Cloudflare Worker and R2 (Phase 10) | the telemetry endpoint's shape |

## Decisions

1. **One Python package, one step per module, one journal.**
   `maluos_installer/` with `plan.py` (schema, defaults, `file:` and
   `url:` references, redaction), `disks.py` (what the machine has),
   `steps/{storage,unpack,configure,bootloader,finish}.py`, each
   exposing `plan(ctx)`, `check(ctx)`, `apply(ctx)` and `summary(ctx)`,
   and `engine.py` which runs them in order and writes a journal
   (`/run/maluos-install/journal.json`: each step and sub-step with its
   state, start, end and error). `--resume` reruns from the first step
   not completed; `storage` and `unpack` are all-or-nothing (a failure
   there is a fresh start, which the journal says), `configure` and
   `bootloader` are sub-stepped and idempotent, so a bootloader failure
   fixed in the shell resumes without unpacking again.
2. **Check everything before touching the disk.** `check` runs for every
   step before `apply` runs for any: schema, the disk resolved to one
   device, the layout's fit, the image present and its hash, URLs
   reachable, the firmware mode against `bootloader.mode`, Secure Boot
   against `secure_boot`, the passphrase present when `encrypt`. `--check`
   stops there and prints the plan as understood. The ISO build runs
   `--check` on the media's plans.
3. **Guided layouts, exactly these.** GPT always; a 1 MiB BIOS boot
   partition always (so `bootloader.mode: both` and a disk that moves
   between machines work without re-partitioning); the ESP at
   `esp_size`; `/boot` as its own ext4 partition whenever the root is
   encrypted or on LVM; then the root.

   | `layout` | `encrypt` | Partitions after ESP and BIOS boot | Root device |
   |---|---|---|---|
   | direct | false | root (`root_size` or the rest) | `/dev/DISKp3`, label `maluos` |
   | direct | true | `/boot` (`boot_size`), LUKS2 (the rest) | `/dev/mapper/maluos-root` |
   | lvm | false | `/boot`, PV (the rest) → VG `maluos` → LV `root` (`root_size` or all) | `/dev/maluos/root` |
   | lvm | true | `/boot`, LUKS2 (the rest) → PV on `/dev/mapper/maluos-pv` → VG `maluos` → LV `root` | `/dev/maluos/root` |

   Commands, in order: `wipefs -a`, `sfdisk --wipe always` with a
   generated script (type GUIDs for ESP, BIOS boot, Linux filesystem,
   Linux LUKS or LVM), `udevadm settle`, `mkfs.vfat -F32 -n ESP`,
   `mkfs.ext4 -L boot` for `/boot`, `cryptsetup luksFormat --type luks2
   --pbkdf argon2id --label maluos-crypt` with the passphrase on a
   file descriptor and `cryptsetup open`, `pvcreate`, `vgcreate maluos`,
   `lvcreate -L SIZE -n root maluos` (or `-l 100%FREE`), `mkfs.ext4 -L
   maluos` or `mkfs.xfs -L maluos`, then the mounts under `/target`
   (`/target/boot`, `/target/boot/efi`). Swap is a file made after the
   unpack (`fallocate`, `mkswap`, `/swap.img` in the fstab; inside the
   encrypted root when encrypted, so it needs no second key). Sizes are
   parsed as `sfdisk` reads them; the fit check leaves 1 MiB of
   alignment slack at each end and refuses a root under 8 GiB.
4. **Unpack is `unsquashfs` onto the mounted target, after the hash.**
   `sha256sum` of the image against `/maluos/SHA256SUMS` first (the
   plan's `source.verify`; a mismatch fails before any write), then
   `unsquashfs -f -xattrs -d /target IMAGE` with its progress on the
   engine's event stream. No overlay, no rsync; the image is the
   installed system, as Phase 3 built it.
5. **Configure writes files; it runs commands only in the target's
   chroot.** With `/dev`, `/proc`, `/sys`, `/run` and `/cdrom` bound
   (and `efivarfs` on UEFI), in this order, each a journal sub-step:
   `fstab` (by UUID: `/`, `/boot`, `/boot/efi`, the swap file) and
   `crypttab` (`maluos-root UUID=… none luks,discard`, or `maluos-pv`);
   `hostname` and `/etc/hosts`; `locale` (`locale-gen`,
   `/etc/default/locale`, `/etc/default/keyboard`, `/etc/localtime`);
   `network` (`/etc/netplan/50-maluos.yaml`, renderer `networkd` on the
   server image and `NetworkManager` on the desktop image, DHCP on
   every wired interface or the static block; the proxy into
   `/etc/apt/apt.conf.d/50maluos-proxy` and `/etc/environment`);
   `identity` (`useradd -m -G sudo -s /bin/bash`, `chpasswd -e` with the
   hash, `authorized_keys`, `chage -d 0` when
   `password_change_required`, `/etc/ssh/sshd_config.d/50-maluos.conf`
   with `PasswordAuthentication`, `systemctl enable|disable ssh`);
   `apt` (the on-media repository to `/var/lib/maluos/apt` and
   `maluos-iso.sources`, exactly today's late-commands; the network
   `maluos.sources` left `Enabled: no` as today, which first boot
   turns on); `components` (`apt-get install` in the chroot against the
   media source only, `apt-get autoremove` after a `remove`; the
   catalogue `/maluos/catalog.yaml` says what the media can install);
   `firstboot` (`/etc/maluos/firstboot.yaml` from the plan's section,
   only the keys given; `cloud-init` masked when `false`, else a NoCloud
   seed with `instance-id` so cloud-init does not search); `grub`
   (`/etc/default/grub`: the cmdline from the plan, the timeout,
   `GRUB_DISABLE_OS_PROBER=true`); `machine-id` cleared last.
   `update-initramfs -u` runs in the chroot after `crypttab` so the
   initrd can unlock.
6. **The bootloader is the target's own, run in the chroot.** BIOS:
   `grub-install --target=i386-pc DISK`. UEFI: `grub-install
   --target=x86_64-efi --efi-directory=/boot/efi --uefi-secure-boot`,
   which installs the signed shim and grub, then `efibootmgr` is used
   only to rename the NVRAM entry to `bootloader.efi_entry` (`MaluOS`)
   and put it first; for `mode: both` and for a disk that may move, also
   `--removable` so `EFI/BOOT/BOOTX64.EFI` exists. `update-grub` last.
   The EFI directory name the signed grub expects is a path, not a
   surface; the first build round settles whether it must stay
   `ubuntu` (see "To verify"). The summary line says "Secure Boot:
   Ubuntu's signed shim and grub", as decision 8 of the phase plan
   requires.
7. **Finish copies the evidence into the target and then does what
   the plan says.** `/var/log/maluos-install/install.log`, `plan.yaml`
   as run with passwords, hashes, passphrases and codes redacted, and
   `journal.json`; the swap file made; the mounts released in reverse,
   LUKS closed, the VG deactivated; `eject` when asked; then `reboot`,
   `poweroff`, `shell` (the target left mounted for inspection) or
   `none` (the tests read the log over the serial console and power
   off themselves).
8. **The engine talks in events.** Every action emits one event
   `{ts, step, sub, state: start|ok|fail|progress, pct, message}` to the
   log and, with `--json`, to stdout as one line each; without `--json`
   the console gets one readable line per event. The screens of slice 3
   and the desktop installer of slice 5 consume the stream; nothing in
   the engine knows about a screen.
9. **A plan is read once, then owned by the engine.** `maluos.plan=` on
   the kernel command line is read by `maluos-installer.service` in the
   live environment, which runs the engine with it; `file:` references
   inside a plan resolve against the media and `LABEL=` mounts; `url:`
   references and a URL plan are fetched after the network is up, with
   a retry ladder of two minutes and a clear failure after. The service
   without a plan does what slice 1's did (the banner and a shell) until
   slice 3 replaces the shell with the screens.
10. **SSH for a remote install is a boot option and nothing else.**
    `maluos.ssh=` (a URL, or an `authorized_keys` line) makes
    `maluos-live-ssh.service` fetch or take the keys for the live user,
    start `sshd` with password authentication off, and print the
    address on the console banner ("ssh maluos@10.0.0.5"). The person
    runs `sudo maluos-install --plan …` in that session; the live user's
    sudo needs no password. Without the option, sshd is not running.
11. **Telemetry is one document, shown before it goes, and only when the
    plan says `send: true`.** The media's unattended plans say `false`.
    The schema and the endpoint are below; the sending code is in the
    engine's finish step and in its failure path, with a five-second
    timeout and no retry, so a report never delays an install.
12. **The subiquity path is still the release until slice 4.** The live
    ISO gains the unattended entries and the tests; the release workflow
    keeps shipping today's ISO. The owner may publish the live ISO as an
    installer preview once this slice's tests pass.

## The media, after this slice

```
/maluos/plan/server-unattended.yaml     erases the first disk; login maluos, password change required (install-plan.md example 1)
/maluos/plan/desktop-unattended.yaml    the same for the desktop image
/maluos/plan/default.yaml               absent on release media; a custom medium puts its plan here
/maluos/catalog.yaml                    the components the media can install (name, description, size, in-image)
```

Menu entries added to slice 1's: "Install MaluOS Server unattended
(erases the first disk; login maluos, password change required)" with
`maluos.plan=/maluos/plan/server-unattended.yaml`; the `--test` variant
makes it the default with `console=ttyS0,115200n8` and `finish: none`
patched into the test plan by the build (`--test` writes
`/maluos/plan/test.yaml`).

## The telemetry report and endpoint

One POST of `application/json` to `telemetry.url`, by the engine, at
the end of a successful install and on an installer failure. The
document, version 1:

```json
{"v": 1, "install_id": "6f0c…-uuid4", "sent_at": "2026-11-20T10:31:04Z", "outcome": "ok",
 "release": "26.04.20261120", "variant": "server", "installer": "maluos-installer 0.1.0",
 "duration_s": 412, "unattended": true, "remote": false,
 "components": ["maluos-server", "maluos-api"],
 "layout": {"kind": "lvm", "filesystem": "ext4", "encrypt": false, "disk_gb": 256, "root_gb": 50, "swap_gb": 8},
 "hardware": {"cpu": "AMD EPYC 7313", "cores": 16, "memory_mb": 65536,
              "disks": [{"bus": "nvme", "gb": 256}, {"bus": "sata", "gb": 2000}],
              "gpu": "none", "firmware": "uefi", "secure_boot": true, "virtual": "kvm"},
 "locale": {"language": "en_US", "keyboard": "us", "timezone": "UTC"},
 "failure": null}
```

On a failure, `outcome` is `failed` and `failure` is `{"step":
"bootloader", "sub": "grub-install", "error": "…", "log_tail": "the last
40 lines, redacted"}`. Never in the document: hostname, user names, IP
or MAC addresses, serial numbers, disk models beyond the bus, the
enrolment address or code, the plan's text. `--telemetry-preview`
prints the document; the slice 3 screen shows the same.

The endpoint: a Cloudflare Worker at `telemetry.maluos.com/v1/install`
beside the download site's, POST only, body at most 32 KB, `v: 1`
validated, 60 requests per minute per address, which drops the address
and keeps only the country code from Cloudflare's header as `country`
(the owner may drop that too); each report written to the R2 bucket
`maluos-telemetry` as `install/YYYY/MM/DD/<install_id>.json`; a 204 on
success and nothing else. Retention two years; a daily count by
release, variant, layout and firmware as a small JSON the download
site can show later. The site's download page gains a privacy line
that links to this section.

## The packages and scripts

**maluos-installer** (0.1.0, live seed only): `maluos_installer/` as
decision 1; `bin/maluos-install` with `--plan`, `--check`, `--dry-run`
(every command printed, none run; the disk facts real), `--resume`,
`--json`, `--telemetry-preview`; `maluos-installer.service` reads
`maluos.plan=`; `maluos-live-ssh.service`; the two media plans and the
catalogue builder (`iso/build-live-iso.sh` writes `/maluos/catalog.yaml`
from the seeds and the on-media repository's sizes).

**maluos-firstboot** (next version): the `enroll` key in
firstboot.yaml (`kind`, `url`, `code`, `name`) and a module that runs
`maluctl office enroll` (desks) or `maluctl estate join` (nodes, once
Phase 13 slice 1 exists; until then the module reports "estate
enrolment is not available on this release" and leaves the key) after
provisioning, with the code removed from the file once used, and
`maluctl firstboot status` showing the outcome.

**iso/build-live-iso.sh**: the plans and the catalogue onto the
media, `--check` on each plan, the menu entries, `--test` writing the
test plan with the SSH key from `--ssh-key` and `finish: {action:
none}`.

**docs**: docs/install-plan.md's `source.image` note changes from
`/casper/` to `/maluos/images/` (slice 1 moved them); this page is
linked from docs/phase11-installer.md.

## Tests

**tests/live-install-test.sh** (new; tests/iso-boot-test.sh stays for
the subiquity ISO until slice 4), `[--uefi] [-p server|desktop]
[--ssh] [--encrypt]`:

1. Builds the `--test` live ISO with the throwaway key; boots it under
   QEMU with a 24 GB disk; the default entry is the unattended plan.
2. Reads the serial console until `maluos-install: finished (reboot)`
   or `maluos-install: FAILED at STEP`, with the event lines in the
   log; fails on the latter with the last 40 lines shown.
3. Boots the disk; waits for SSH; runs the Phase 2 and Phase 4 checks
   that tests/iso-boot-test.sh runs today, plus: `lsblk` shows the
   layout the plan asked for (VG `maluos`, LV `root`), `/etc/fstab` is
   by UUID and has the swap file, `swapon --show` lists it, the kernel
   command line carries the plan's `cmdline`, `/var/log/maluos-install/`
   holds the three files and `plan.yaml` has no `$6$` and no code,
   `efibootmgr` on UEFI shows `MaluOS` first, `chage -l maluos` says the
   password must change, `/etc/maluos/firstboot.yaml` has the plan's
   tenant, cloud-init is active on the server and masked on the desktop.
4. `--ssh`: boots the live ISO with `maluos.ssh=` and no plan, waits for
   the banner's address, copies the plan over `scp`, runs `sudo
   maluos-install --plan` over SSH and watches its `--json` stream, then
   step 3.
5. `--encrypt`: the plan with `encrypt: true` and a passphrase; after
   the install the test answers the unlock prompt on the serial console
   (QEMU's serial on a socket), then step 3 plus `cryptsetup status`.
   Dev VM only until it proves stable; not in CI at first.

**tests/iso-apt-check.sh**: reads `/maluos/images/` and no layer;
replays the configure step's apt part with the engine's own code
(`maluos-install --apt-check IMAGE`), so the test and the installer
cannot drift.

**tests/install-plan-test.py** (new, unit, runs in the packages
workflow): the schema (every key, defaults, unknown-key errors, `file:`
and `url:` forms), the layout computation for the four layouts on
disks of 16, 64 and 2000 GB, the fit refusals, the redaction, the
telemetry document from a fixture of facts.

CI: the images workflow runs the live install test on BIOS for both
images under TCG; UEFI runs on the dev VM as the UEFI boot tests do
today. The real-machine round (BIOS, UEFI, UEFI with Secure Boot, a USB
stick) is the owner's, once per slice from here to the switch.

## Deferred

- The screens (slice 3), the switch (slice 4), the graphical installer
  (slice 5).
- Manual partitioning, "use the free space", btrfs, a swap partition,
  a separate `/var/lib/postgresql`: later items of the phase plan.
- TPM-backed unlocking of the LUKS root: later.
- An image from a URL (`source.image: https://…`, netboot): later; the
  key is reserved.
- Wi-Fi for the install itself: slice 3 with the network screen (the
  plan's `network.wifi` is parsed and refused with "not yet" until then).
- The telemetry summary job and its page on the download site: after
  the first reports exist.

## To verify in the first build round

- Whether Ubuntu's signed grub, installed with `--bootloader-id=MaluOS`,
  finds its `grub.cfg` (the embedded prefix may be `/EFI/ubuntu`); if
  not, the directory stays `ubuntu` and only the NVRAM label is
  `MaluOS`.
- `unsquashfs -f` onto a mounted xfs root keeps capabilities and
  security xattrs (`-xattrs`; checked on `/usr/bin/ping`).
- `update-initramfs` in the chroot picks up `crypttab` without
  `/etc/crypttab` tricks (the `cryptsetup-initramfs` package is in the
  target images; confirm it is).
- `cloud-init`'s NoCloud seed with only `instance-id` makes a first boot
  that does not wait on a network datasource.

## Effort

| Part | Size | Notes |
|---|---|---|
| plan.py, disks.py, the schema test | M | |
| storage and unpack | M | the four layouts and LUKS; `--dry-run` first |
| configure and bootloader | M | the chroot sub-steps; the Secure Boot question |
| finish, events, journal, resume | S | |
| the SSH option, the media plans, the catalogue, the menu | S | |
| telemetry: the document and the Worker | S | |
| maluos-firstboot's enroll module | S | |
| tests/live-install-test.sh and the CI job | M | the slow part to run; an install under TCG is tens of minutes |

About the size of Phase 12 slice 7; four or five install rounds on the
dev VM, with KVM, before CI sees it.
