# Phase 3: MaluOS images built from the seeds

Phase 2 proved the install path with Ubuntu's own root filesystem and a
late-commands package install. Phase 3 makes the root filesystem ours:
built from the seeds, identical across the ISO and the cloud image, and
installable offline.

## Design

```
seeds/*.seed  ->  maluos-* metapackages  ->  MaluOS apt repo
                                                   |
image/profiles/server.pkgs  +  Ubuntu archive  +  PGDG
                                                   |
                 image/build-rootfs.sh  (mmdebstrap, as root)
                                                   |
            build/image/maluos-server.rootfs/  (directory)
                /                 \
 image/build-qcow2.sh         mksquashfs
        |                          |
 maluos-server-26.04-amd64.qcow2   maluos-server.squashfs  --> iso/build-iso.sh
 (cloud-init, BIOS+UEFI)           (default install source on the ISO)
```

**Installer.** The ISO keeps Ubuntu's live installer environment (subiquity)
untouched and adds the MaluOS squashfs as the default entry in
casper/install-sources.yaml. Subiquity copies it to the target disk, installs
the kernel from the ISO pool and applies identity, network and storage. No
installer fork, no snap seeding, and the installed system is exactly the
rootfs we built. Ubuntu's own sources stay selectable in the guided install.

**Offline.** PostgreSQL 18 and the MaluDB packages are inside the squashfs,
so an ISO install no longer needs the network. The late-commands only copy
the on-media repository to /var/lib/maluos/apt and enable the serial console.

**Identity.** maluos-branding diverts os-release, issue and issue.net.
NAME, PRETTY_NAME and VARIANT say MaluOS; ID stays `ubuntu` so cloud-init,
curtin, PGDG scripts and add-apt-repository keep working.

**Cloud image.** GPT with BIOS boot, ESP and ext4 root, grub for both
firmware types with Secure Boot shim, serial console on, cloud-init with
growpart. Boots on Proxmox, KVM, and cloud providers that take qcow2 or raw.

## Build

```
repo/serve.sh &                         # the rootfs build pulls from the local repo
sudo image/build-rootfs.sh              # -> build/image/maluos-server.{rootfs,squashfs,manifest,size}
sudo image/build-qcow2.sh               # -> build/image/maluos-server-26.04-amd64.qcow2
iso/build-iso.sh                        # -> build/maluos-26.04.1-server-amd64.iso (needs the squashfs)
```

## Test

```
tests/qcow2-boot-test.sh [image] [--uefi]   # boots the cloud image with a NoCloud seed, verifies over SSH
tests/iso-boot-test.sh [--uefi]             # full ISO install (needs KVM in practice)
```

## Profiles

image/profiles/<name>.pkgs lists what goes into a rootfs on top of the
Ubuntu bootstrap. `server` = ubuntu-server-minimal + maluos-server +
linux-generic + grub/shim + cloud-init. Add a profile for a desktop or an
agent appliance later; metapackages stay the single source of truth for
what "MaluOS" means.

## Status (2026-10-17)

- Rootfs: 434 packages, 1.9 GB uncompressed, 1.2 GB squashfs. PostgreSQL
  18.6 cluster 18/main is created at build time, so the service is up on
  first boot.
- Cloud image: tests/qcow2-boot-test.sh PASS on BIOS under QEMU/TCG:
  MaluOS identity, all MaluOS and MaluDB packages, postgresql@18-main
  active, maludb_core available, growpart to 20 GB, apt-get update clean,
  cloud-init done.
- ISO: 4.1 GB, maluos-server.squashfs is the default install source; both
  boot images replayed. End-to-end install test still needs a KVM host
  (see phase2-iso.md for the emulation limitation).

## Open

- Branding of the live installer environment itself (still Ubuntu).
- arm64 rootfs and images.
- CI: rootfs, qcow2 and ISO builds with boot tests on KVM runners.
- Production signing key and public mirror; until then maluos.sources is
  shipped disabled and the on-media repo is the update source.
