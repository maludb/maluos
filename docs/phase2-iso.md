# Phase 2: the first bootable MaluOS ISO (remaster)

> Replaced by Phase 11 (2026-10-24): the medium is now assembled from scratch by
> iso/build-live-iso.sh around our own live environment (docs/phase11-slice1-live.md);
> this script and its base ISO keep releasing beside it until Phase 11 slice 4.


MaluOS 26.04.1 Server is the stock Ubuntu Server 26.04.1 ISO with a MaluOS
layer added and the boot menu replaced. The kernel, installer (subiquity),
squashfs and Ubuntu boot images are untouched, so the ISO boots on BIOS and
UEFI exactly as Ubuntu's does, Secure Boot included.

## Build

```
repo/publish.sh                      # the ISO carries the published repo
iso/build-iso.sh                     # -> build/maluos-26.04.1-server-amd64.iso
iso/build-iso.sh --test --ssh-key k  # test variant: serial console, 3 s timeout,
                                     # automated entry default; never ship it
```

The base ISO is read from ~/iso-cache/ubuntu-26.04.1-live-server-amd64.iso
(override with -i). Its SHA256 must match Ubuntu's published SHA256SUMS:
cc8a95cde20f6ced61a322420de00f10cc3c90ced545daa46cb9c1a117f1d927.

xorriso reads the base image, replays its El Torito/MBR/GPT boot setup
(`-boot_image any replay`), maps in the new files and writes a new image.
No extraction of the 2.7 GB tree is needed; a build takes well under a minute.

## What the ISO adds

| Path on ISO | Content |
|---|---|
| /maluos/apt/ | The published MaluOS repository: dists, pool, bootstrap (keyring .gpg, bootstrap .debs, install script) |
| /maluos/pgdg.sources | PGDG source file, identical to the one maluos-archive installs |
| /maluos/nocloud-auto/ | Unattended autoinstall (user-data + meta-data) |
| /maluos/nocloud-interactive/ | Guided autoinstall (interactive-sections) |
| /boot/grub/grub.cfg | MaluOS menu |
| /md5sum.txt | Updated for the new and replaced files |

Boot menu, in order: "Install MaluOS Server" (guided, default), "Install
MaluOS Server (automated, erases first disk)", and the stock Ubuntu installer.

## Install flow

Subiquity runs the autoinstall from `ds=nocloud;s=/cdrom/maluos/nocloud-*/`.
After Ubuntu is on the target disk, the shared late-commands
(autoinstall/late-commands.yaml):

1. copy /cdrom/maluos/apt to /var/lib/maluos/apt and add a `file:` source for it;
2. install postgresql-client-common (brings the PGDG key) and add pgdg.sources;
3. `apt-get update` and install maluos-server, which pulls PostgreSQL 18 and
   its PGDG extensions over the network and the MaluDB packages from the media;
4. disable the network MaluOS source (no public mirror yet);
5. enable the serial console in grub and write /etc/maluos-release.

Network access to the Ubuntu archive and apt.postgresql.org is required
during install. Making the ISO fully offline means mirroring PostgreSQL 18
and its dependencies onto the media (Phase 3).

## Test

```
sudo apt install qemu-system-x86 ovmf qemu-utils
tests/iso-boot-test.sh            # BIOS
tests/iso-boot-test.sh --uefi     # OVMF
```

The test builds the --test variant with a throwaway SSH key, installs on a
24 GB qcow2 under QEMU (KVM if /dev/kvm is writable, otherwise TCG, which
takes tens of minutes), boots the installed disk, and over SSH checks that
the MaluOS packages are installed, postgresql@18-main is active, the network
source is disabled and `apt-get update` is clean. Logs in /var/tmp/maluos-iso-test.

## Test status (2026-10-16)

Verified under QEMU/TCG on the dev host: the remastered image boots (BIOS),
the kernel and live environment start, cloud-init finds the NoCloud data
on the media, and subiquity loads and validates the autoinstall, including
the late-commands section (an earlier YAML quoting bug there was caught by
this test and is now checked at build time).

Not yet verified end to end. Under software emulation subiquity's network
stage fails: `netplan apply` reports "Call failed: Connection timed out"
because systemd-networkd takes ~40 s to act on the reload, past the 25 s
bus timeout. The network itself is up (DHCP lease, default route) and the
config is subiquity's own default, so this is an emulation artefact, not an
ISO defect. `tests/debug-installer.sh` drives the installer's failure shell
over the serial socket and captured the crash report and a manual
reproduction.

To finish verification run `tests/iso-boot-test.sh` on a host with KVM
(the script uses it automatically when /dev/kvm is writable), or enable
nested virtualisation for this dev VM on its hypervisor. GitHub-hosted
Linux runners also expose KVM.

## Known limitations

- Default credentials of the automated variant are maluos / maluos with SSH
  password auth enabled. Change them on first login.
- os-release, motd and plymouth still say Ubuntu; branding packages are Phase 3.
- The installer environment itself is unbranded Ubuntu subiquity.
- amd64 only.
