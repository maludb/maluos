# Download MaluOS

Source for the download page on https://maluos.com. The release number
below is the current one; `https://download.maluos.com/LATEST` always
holds it, so a site script can substitute it at render time.

---

## MaluOS Server 26.04.20261019

MaluOS is an operating system built around MaluDB: the database, its API,
the credential vault, the model gateway and the agent runtime install and
provision themselves on first boot. The free edition is the full server;
no account or licence is needed.

| File | Size | Use |
|---|---|---|
| [maluos-26.04.20261019-server-amd64.iso](https://download.maluos.com/26.04.20261019/maluos-26.04.20261019-server-amd64.iso) | 4.7 GB | Installer for physical machines and VMs (BIOS and UEFI, Secure Boot) |
| [maluos-26.04.20261019-server-amd64.qcow2](https://download.maluos.com/26.04.20261019/maluos-26.04.20261019-server-amd64.qcow2) | 1.7 GB | Cloud image with cloud-init, for KVM, Proxmox, OpenStack and similar |
| [SHA256SUMS](https://download.maluos.com/26.04.20261019/SHA256SUMS) · [SHA256SUMS.gpg](https://download.maluos.com/26.04.20261019/SHA256SUMS.gpg) | | Checksums and their signature |
| [RELEASE-NOTES.md](https://download.maluos.com/26.04.20261019/RELEASE-NOTES.md) | | Package versions and changes in this release |

Releases are dated: `26.04` is the package base, `20261019` the build
date. Every release is also on GitHub with the cloud image and checksums
attached: https://github.com/maludb/maluos/releases/tag/v26.04.20261019

## Verify the download

Every release is signed with the MaluOS archive signing key.

```
MaluOS Archive Signing Key (2026) <apt@maluos.com>
Fingerprint: 6387 5A4A 5397 B902 E9C5  CFF8 731A DA39 4135 B9FF
```

Fetch the key from the package repository, check the signature on the
checksum file, then check the file you downloaded:

```sh
V=26.04.20261019
curl -fsSLO https://download.maluos.com/$V/SHA256SUMS
curl -fsSLO https://download.maluos.com/$V/SHA256SUMS.gpg
curl -fsSL  https://apt.maluos.com/bootstrap/maluos-archive-keyring.gpg -o maluos-archive-keyring.gpg
gpg --no-default-keyring --keyring ./maluos-archive-keyring.gpg --verify SHA256SUMS.gpg
sha256sum -c SHA256SUMS --ignore-missing
```

`gpg` must print `Good signature from "MaluOS Archive Signing Key (2026)
<apt@maluos.com>"` with the fingerprint above, and `sha256sum` must print
`OK` for the file you downloaded. Stop if either differs.

## Requirements

| | Minimum | Recommended |
|---|---|---|
| Architecture | x86-64 (amd64) | |
| CPU | 2 cores | 4 cores or more |
| Memory | 2 GB | 8 GB; add the memory of any local model you run |
| Disk | 25 GB | 60 GB or more, SSD |
| Firmware | BIOS or UEFI, Secure Boot on or off | |
| Network | needed during install for package updates | |

Local language models run through Ollama on the same machine when
present; a GPU is optional. Without one, MaluOS routes model requests to
the cloud backends you configure.

## Install from the ISO

1. Write the ISO to a USB stick (`dd`, Rufus, balenaEtcher) or attach it
   to a VM, and boot from it.
2. Choose **Install MaluOS Server**. The installer asks for language,
   keyboard, network, proxy, disk layout, your user account and SSH
   access, then installs and reboots.
3. For a hands-off install choose **Install MaluOS Server unattended**.
   It erases the first disk without asking, creates the user `maluos`
   with the password `maluos`, and forces a password change at the first
   login.
4. On the first boot MaluOS provisions itself: the database cluster, the
   tenant, the API, the credential vault and the model gateway. This takes
   a few minutes. Log in and check:

```sh
maluctl status          # provisioning summary and service health
sudo maluctl token      # your API bearer token
```

The installer is the stock Ubuntu live installer, so its screens show
Ubuntu naming during the install; the installed system is MaluOS.

## Run the cloud image

The qcow2 image boots with cloud-init. Provide user data the way your
platform does (NoCloud seed, OpenStack metadata, Proxmox cloud-init
drive). A minimal NoCloud example for local KVM:

```sh
cat > user-data <<'UD'
#cloud-config
users:
  - name: maluos
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - ssh-ed25519 AAAA... you@example
UD
echo 'instance-id: maluos-1' > meta-data
cloud-localds seed.iso user-data meta-data
qemu-img create -f qcow2 -b maluos-26.04.20261019-server-amd64.qcow2 -F qcow2 disk.qcow2 40G
qemu-system-x86_64 -enable-kvm -m 4096 -smp 2 -drive file=disk.qcow2,if=virtio \
  -drive file=seed.iso,if=virtio,format=raw -nic user,hostfwd=tcp::2222-:22
ssh -p 2222 maluos@127.0.0.1 maluctl status
```

## Add MaluOS to an existing Ubuntu 26.04 system

The bootstrap script adds the signed package repository and installs the
server metapackage; first-boot provisioning runs on the next boot.

```sh
curl -fsSL https://apt.maluos.com/bootstrap/install-maluos.sh | sudo bash
```

To add only the repository:

```
Types: deb
URIs: https://apt.maluos.com
Suites: resolute
Components: main
Signed-By: /usr/share/keyrings/maluos-archive-keyring.gpg
```

with the keyring from `https://apt.maluos.com/bootstrap/maluos-archive-keyring.gpg`.

## Source and licensing

MaluOS is built on the Ubuntu 26.04 package base. MaluOS is not
affiliated with or endorsed by Canonical Ltd.; Ubuntu is a trademark of
Canonical. The MaluOS packages, build system and installer configuration
are at https://github.com/maludb/maluos; the MaluDB engine is at
https://github.com/maludb/maludb-core-26.

## Support

Questions and bug reports: https://github.com/maludb/maluos/issues.
Professional and Enterprise editions with support subscriptions are in
preparation; the free edition stays free.
