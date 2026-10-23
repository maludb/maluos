# Phase 11 slice 1: the live environment and the ISO we assemble

Specified 2026-10-23 from docs/phase11-installer.md (decisions 1, 6, 8;
the owner's answers 2 and 5). Nothing here is built. It is sequenced in
docs/roadmap.md (E1) after Phase 12 slice 9; the subiquity ISO keeps
being built and released beside it until slice 4.

## What the slice delivers

An ISO that boots, on BIOS and UEFI, into a live MaluOS environment of
our own: our kernel and initrd, our splash, our grub menu, a console
with a MaluOS banner and a shell, the media mounted, the target image
beside it with its checksum. The installer on it is a stub that reports
the media and exits to a shell; the engine arrives in slice 2. Nothing
in the slice touches the released ISO or the installed system.

```
sudo image/build-rootfs.sh -p live                 # the live rootfs, kernel and initrd
iso/build-live-iso.sh -p server [--test]           # build/iso/maluos-server-26.04-amd64.live.iso
iso/build-live-iso.sh -p desktop [--test]
tests/live-iso-boot-test.sh [--uefi] -p server     # boots it under QEMU to the banner and checks the media
```

## What exists to build on

| Piece | Reused as |
|---|---|
| image/build-rootfs.sh, image/profiles/*.pkgs, seeds/*.seed | a third profile `live` and seeds/live.seed; the same mmdebstrap, manifest, size and squashfs steps; two new outputs, the kernel and the initrd |
| iso/build-iso.sh | the on-media repository copy, the grub.cfg templating with `--test`, the `--ssh-key` handling; the rest (replaying Ubuntu's boot images, the cdrom.sources layer, install-sources.yaml, md5sum.txt) is what this slice replaces |
| casper 26.04.2 in the archive | the live boot: `boot=casper layerfs-path=…` mounts one squashfs by name, makes the live user from `/etc/casper.conf`, and its initramfs hooks put itself and plymouth into the initrd |
| grub-pc-bin 2.14, grub-efi-amd64-signed 1.215, shim-signed 1.59 in the archive | the BIOS El Torito image and the hybrid MBR; the ESP image with the signed shim and grub |
| maluos-branding (plymouth theme, os-release, the grub colours, the logo) | the live rootfs carries it; the theme is the initrd's because it is the rootfs's default when the initrd is built |
| tests/iso-boot-test.sh | the QEMU and OVMF invocation, the serial log checks, the `--test` grub variant |
| the images CI workflow | a job that builds the live rootfs and the live ISO and runs the boot test under TCG |

## Decisions

1. **One live image, the targets beside it, outside `/casper`.** casper
   treats every squashfs under `/casper` as a candidate layer. The live
   image is the only file there; the install images live under
   `/maluos/images/` with their `.size`, `.manifest` and the SHA256SUMS,
   so casper never sees them and the installer owns them. The kernel
   command line names the live image: `layerfs-path=maluos-live.squashfs`.
2. **The live rootfs is a server-minimal system plus what an installer
   needs**, built like the others. seeds/live.seed: maluos-base (the
   branding, curl, gnupg, jq, sudo, openssh-server, which casper leaves
   disabled), casper, maluos-installer, network-manager (the desktop's
   choice, and `nmcli` beats hand-written netplan on a live console),
   iproute2, iputils-ping, ethtool, wireless-tools and wpasupplicant,
   console-setup, kbd, locales, tzdata, less, vim-tiny, parted, gdisk,
   dosfstools, e2fsprogs, lvm2, cryptsetup, squashfs-tools, efibootmgr,
   pciutils, usbutils, dmidecode, lshw, smartmontools, nvme-cli,
   openssh-client, rsync, tmux, python3-urwid (for slice 3, pulled now so
   the rootfs does not change shape then). image/profiles/live.pkgs adds
   `linux-generic` and `linux-firmware`, `grub-pc-bin`,
   `grub-efi-amd64-signed`, `shim-signed`, `grub2-common`. No database,
   no cloud-init, no unattended-upgrades (removed by the profile's
   exclusion list, since maluos-base pulls it), no snap.
3. **linux-firmware is in.** A live medium meets hardware the installed
   system will also meet; a network card without firmware stops an
   install. It costs about 350 MB on the ISO. The owner can cut it to
   `linux-firmware` minus the GPU blobs later if size matters more.
4. **The kernel and initrd come out of the live rootfs.** mmdebstrap
   installs `linux-generic` in the chroot; casper's hooks and the
   plymouth hook run in the chroot's `update-initramfs`, so
   `/boot/vmlinuz` and `/boot/initrd.img` in the rootfs are the live
   kernel and initrd with casper and our theme inside. build-rootfs.sh
   copies them out as `build/image/maluos-live.vmlinuz` and
   `maluos-live.initrd` before squashing, and the squashfs keeps them
   too (casper needs the modules; the files in `/boot` cost nothing on
   a squashfs that already holds `/lib/modules`). The theme is the
   initrd's because maluos-branding makes it the plymouth default at
   install, before the kernel's postinst builds the initrd; the profile
   orders the branding before the kernel for that reason, and the test
   checks the theme files in the initrd.
5. **The live user is `maluos`, no password, sudo without a password,
   autologin on the console.** `/etc/casper.conf` in the live rootfs:
   `USERNAME=maluos`, `USERFULLNAME="MaluOS live"`, `HOST=maluos`,
   `BUILD_SYSTEM=Ubuntu` (casper's scripts compare the value; it names
   their origin, is read by nothing a person sees, and is the one place
   the word stays). The installer's unit, not a getty, owns tty1; the
   serial console named by `console=` gets an autologin getty for
   `maluos`, as the installer's second seat (and the test's). SSH stays
   off: the `maluos.ssh=` boot option is slice 2's.
6. **The ISO is assembled from scratch with xorriso, Ubuntu's way.**
   `xorriso -as mkisofs` with `--grub2-mbr` (grub-pc-bin's
   `boot_hybrid.img`), a BIOS El Torito image made by `grub-mkimage -O
   i386-pc-eltorito` with the modules a CD boot needs (`biosdisk
   iso9660 part_gpt part_msdos fat normal configfile linux search
   gfxterm all_video font`), and an ESP FAT image appended as a GPT
   partition (`-append_partition 2 0xEF efi.img -appended_part_as_gpt
   -eltorito-alt-boot -e --interval:appended_partition_2:all::`) that
   holds `EFI/BOOT/BOOTx64.EFI` (shim-signed), `EFI/BOOT/grubx64.efi`
   and `mmx64.efi` (grub-efi-amd64-signed) and a stub `EFI/BOOT/grub.cfg`
   that finds the medium by `/.disk/info` and hands over to
   `/boot/grub/grub.cfg`. The result is a hybrid image that boots from a
   DVD and from a USB stick written with `dd`, on BIOS, UEFI and UEFI
   with Secure Boot (Ubuntu's signed chain, decision 8 of the phase
   plan). Nothing is replayed from Ubuntu's ISO; the base ISO is no
   longer an input to this path.
7. **No md5sum.txt, no `install-sources.yaml`, no cdrom.sources layer.**
   casper's medium check is skipped with `fsck.mode=skip` on the
   command line; the installer verifies the target squashfs against
   `/maluos/SHA256SUMS` before unpacking (slice 2's unpack step), which
   is the check that matters. The two subiquity files existed for
   curtin and go with it. The on-media repository (`/maluos/apt`) stays
   exactly as it is, and the live environment's own apt points at it
   (a `cdrom.sources` for `/cdrom/maluos/apt`, signed by the MaluOS
   keyring the branding carries), so `apt install` works offline in the
   live shell.
8. **The menu is ours and short.** "Start the MaluOS Server installer"
   (default, `quiet splash`), "Start the installer with the serial
   console" (`console=ttyS0,115200n8`, no splash), "Rescue shell"
   (`maluos.rescue=1`: the installer unit does not start; a root shell
   on the console), then on UEFI "Boot from next volume" and "UEFI
   Firmware Settings", as today. `--test` makes the serial entry the
   default with a 3-second timeout, as today. The grub colours are the
   branding's; a background image is slice 5's.
9. **The old path is untouched.** iso/build-iso.sh, autoinstall/, the
   base ISO and tests/iso-boot-test.sh keep working and keep releasing.
   The new script is iso/build-live-iso.sh and its output is named
   `.live.iso` until slice 4 renames it; the release workflow does not
   ship it. The owner may decide to publish it as an "installer
   preview" download once slice 2 can install.

## The media

```
/.disk/info                         "MaluOS 26.04.20261105 Server amd64"
/boot/grub/grub.cfg                 the menu
/boot/grub/i386-pc/eltorito.img     BIOS boot image (and its modules dir)
/boot/grub/fonts/unicode.pf2
/casper/vmlinuz                     the live kernel (from the live rootfs)
/casper/initrd                      the live initrd (casper, plymouth, our theme)
/casper/maluos-live.squashfs        the live rootfs
/casper/maluos-live.size, .manifest
/maluos/images/maluos-server.squashfs      the target (desktop ISO: maluos-desktop.squashfs)
/maluos/images/maluos-server.size, .manifest
/maluos/SHA256SUMS                  the live and target images, the kernel and initrd
/maluos/apt/{dists,pool,bootstrap}  the on-media repository, as today
/maluos/plan/                       slice 2: the unattended plans (empty directory now)
EFI partition (appended, GPT 2)     EFI/BOOT/{BOOTx64.EFI,grubx64.efi,mmx64.efi,grub.cfg}
```

Volume id `MALUOS_26.04.20261105_SERVER` (uppercase, 32 characters
max, as the volume id has to be); the label is what casper's
`/.disk/info` search and the stub grub.cfg use, and what the installed
system's cdrom source names.

Kernel command line, default entry:

```
/casper/vmlinuz boot=casper layerfs-path=maluos-live.squashfs fsck.mode=skip quiet splash ---
```

## The boot chain, in order

1. Firmware → the hybrid MBR (BIOS) or the ESP's `BOOTx64.EFI` (UEFI,
   shim verifies `grubx64.efi` under Secure Boot).
2. grub reads `/boot/grub/grub.cfg` on the ISO 9660 filesystem (the
   UEFI stub found it by `/.disk/info`), draws the menu, loads
   `/casper/vmlinuz` and `/casper/initrd`.
3. The initrd shows the plymouth theme, casper finds the medium by the
   volume id, mounts it at `/cdrom`, mounts
   `/cdrom/casper/maluos-live.squashfs` with an overlay in RAM, makes the
   live user, and pivots.
4. systemd in the live rootfs: NetworkManager brings up DHCP,
   `maluos-installer.service` takes tty1 (and the serial getty logs
   `maluos` in on ttyS0 when `console=` names it).
5. The stub installer prints the banner, the medium's facts and drops to
   a shell; in slice 2 it runs the engine.

## The packages and scripts

**maluos-installer** (new, 0.0.1, in the live seed only)

- `bin/maluos-install`: in this slice `--check-media` (the medium's
  mount, the images listed with sizes, SHA256SUMS verified for the
  target image, the kernel and the initrd, the plymouth theme files
  present in the initrd by `lsinitramfs`, firmware BIOS or UEFI, Secure
  Boot state from `mokutil --sb-state`, the network interfaces and
  their addresses), `--version`, and without arguments the banner, the
  check, and "The MaluOS installer is not on this medium yet (slice 2).
  You have a shell." The engine, the plan and the screens come later
  under this name.
- `systemd/maluos-installer.service`: `ConditionKernelCommandLine=
  !maluos.rescue`, `Conflicts=getty@tty1.service`, `StandardInput=tty`
  on `/dev/tty1`, runs `maluos-install` as root, restarts on exit so
  the console is never dead; `maluos-rescue.service` for the rescue
  entry (a root shell on tty1).
- `systemd/serial-getty@.service.d/autologin.conf` for the live user.
- `/etc/casper.conf`, `/etc/issue` (the MaluOS banner, no Ubuntu line),
  `/etc/apt/sources.list.d/cdrom.sources` for `/cdrom/maluos/apt`.
- The package is not installed on any target; the installed system
  never carries it.

**seeds/live.seed and image/profiles/live.pkgs**: decision 2;
image/build-rootfs.sh learns the profile (`-p live`), writes the kernel
and initrd outputs, and excludes unattended-upgrades and cloud-init
from this profile.

**iso/build-live-iso.sh** (new): `-p server|desktop`, `--test`,
`--ssh-key` (kept for slice 2's `maluos.ssh=`), `-o`. Steps: the stage
directory; the on-media repository copy (the same lines as today's
script, moved into a shared `iso/lib.sh`); the images into
`/maluos/images/`; `/maluos/SHA256SUMS`; the grub.cfg from
`iso/grub-live.cfg.in`; the El Torito image with `grub-mkimage`; the
ESP image with `mkfs.vfat` and `mcopy` (dosfstools, mtools: build
dependencies, listed in docs/phase2-iso.md's tool list); the `xorriso
-as mkisofs` call of decision 6; a final `xorriso -indev … -report_el_torito
as_mkisofs` printed to the log so the boot records are visible in CI.

**maluos-branding**: nothing new if the plymouth default is already set
in postinst (Phase 12 slice 4 did this for the desktop); verified in
the first build round. The grub colours move from iso/grub.cfg.in into
the branding's `/usr/share/maluos/grub-colours.cfg` so both grub
templates source one file.

**docs**: docs/phase2-iso.md gains a "Replaced by Phase 11" note at the
top pointing here; docs/components.md is unchanged.

## Test (tests/live-iso-boot-test.sh)

Boots the `--test` ISO under QEMU (TCG in CI, KVM on the dev VM) with
`-cdrom`, no disk, serial to a log, BIOS by default and `--uefi` with
OVMF as tests/iso-boot-test.sh does. The `--test` variant's default
entry adds `maluos.test=1`, on which the installer unit runs
`maluos-install --check-media` and then `systemctl poweroff` instead of
the shell, so the test is the serial log. Checks, each a line in the
log:

1. grub's menu text appears on the serial console ("Start the MaluOS
   Server installer"), so the right grub.cfg loaded on this firmware.
2. "MaluOS 26.04" from the kernel's boot messages and casper's
   "mounting /cdrom" line, no "Ubuntu" on the serial console after the
   firmware's own lines (grep, with the OVMF banner and the kernel's
   version string excluded by pattern).
3. `check-media` lines: `medium: /cdrom (MALUOS_26.04.…_SERVER)`,
   `live: maluos-live.squashfs NNN MB`, `target: maluos-server.squashfs
   NNN MB sha256 ok`, `kernel: 7.0.0-NN-generic`, `initrd: casper ok,
   plymouth theme maluos ok`, `firmware: BIOS` or `UEFI, Secure Boot
   off`, `network: ens3 10.0.2.15`.
4. `poweroff` within the timeout (10 minutes under TCG; the live boot is
   two to three minutes).

Run on both firmwares, server and desktop profiles: four runs, each a
few minutes, in the images workflow beside the existing jobs. The
Secure Boot path is verified on a real machine once by the owner (a USB
stick, Secure Boot on; the test for it is "the menu appears"), as
decision 6 of the phase plan requires before the switch.

## Deferred to slice 2 and later

- The engine, the install plan, the unattended install and the
  `maluos.ssh=` option: slice 2.
- The screens: slice 3. The ISO rename, the removal of the base ISO and
  autoinstall/: slice 4. The graphical live session: slice 5.
- A `toram` entry (copy the live image to RAM so the medium can be
  removed): later, if asked for.
- arm64 media: the same assembly with grub-efi-arm64-signed and no BIOS
  image; with E6 of the roadmap.

## To verify in the first build round

Things the archive's versions decide and this spec assumes; each is a
one-line check before the first full build:

- casper 26.04.2 honours `layerfs-path=` for a file that is not named
  in the dotted layer style, and ignores squashfs files outside
  `/casper` (expected: yes, both).
- The signed grub reads the stub `grub.cfg` from `EFI/BOOT` (Ubuntu's
  ISOs rely on it; if 2.14's signed build looks in `EFI/ubuntu` only, the
  stub goes there too, which is a path, not a surface).
- `fsck.mode=skip` disables casper-md5check in 26.04.2 (else
  `casper-md5check` is masked in the live rootfs).
- The plymouth theme lands in the initrd when the branding is installed
  before the kernel in one mmdebstrap run (else build-rootfs.sh runs
  `update-initramfs -u` in the chroot after the install, which is cheap).

## Effort

| Part | Size | Notes |
|---|---|---|
| seeds/live.seed, the profile, build-rootfs.sh changes | S | |
| maluos-installer 0.0.1 (stub, units, casper.conf, banner) | S | |
| iso/build-live-iso.sh (El Torito, ESP, xorriso) | M | the part with unknowns; the four checks above first |
| the grub template and the branding's colours file | S | |
| tests/live-iso-boot-test.sh and the CI job | S | |

Smaller than Phase 12 slice 7; two or three build rounds on the dev VM
(a live rootfs build is a few minutes; an ISO assembly is seconds once
the images exist).
