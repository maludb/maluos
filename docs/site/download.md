# Download MaluOS

Source for the download page on https://maluos.com. The release number
below is the current one; `https://download.maluos.com/LATEST` always
holds it, so a site script can substitute it at render time.

---

## MaluOS 26.04.20261029

MaluOS is an operating system built around MaluDB: the database, its API,
the credential vault, the model gateway and the agent runtime install and
provision themselves on first boot. The free edition is the full system;
no account or licence is needed. It comes as a server and as a desktop.

| File | Size | Use |
|---|---|---|
| [maluos-26.04.20261029-server-amd64.iso](https://download.maluos.com/26.04.20261029/maluos-26.04.20261029-server-amd64.iso) | 5.2 GB | Server installer for physical machines and VMs (BIOS and UEFI, Secure Boot) |
| [maluos-26.04.20261029-server-amd64.qcow2](https://download.maluos.com/26.04.20261029/maluos-26.04.20261029-server-amd64.qcow2) | 1.7 GB | Server cloud image with cloud-init, for KVM, Proxmox, OpenStack and similar |
| [maluos-26.04.20261029-desktop-amd64.iso](https://download.maluos.com/26.04.20261029/maluos-26.04.20261029-desktop-amd64.iso) | 5.4 GB | Desktop installer (GNOME) for workstations, laptops and VMs (BIOS and UEFI, Secure Boot) |
| [maluos-26.04.20261029-desktop-amd64.qcow2](https://download.maluos.com/26.04.20261029/maluos-26.04.20261029-desktop-amd64.qcow2) | 2.0 GB | Desktop image with cloud-init, for a workstation VM |
| [SHA256SUMS](https://download.maluos.com/26.04.20261029/SHA256SUMS) · [SHA256SUMS.gpg](https://download.maluos.com/26.04.20261029/SHA256SUMS.gpg) | | Checksums and their signature |
| [RELEASE-NOTES.md](https://download.maluos.com/26.04.20261029/RELEASE-NOTES.md) | | Package versions and changes in this release |

Releases are dated: `26.04` is the package base, `20261029` the build
date. Every release is also on GitHub with the cloud images and checksums
attached: https://github.com/maludb/maluos/releases/tag/v26.04.20261029

## The desktop

MaluOS Desktop is the server with a GNOME 50 workstation on top: the same
database, vault, model gateway and agent runtime run on the machine, so
agents on your desk have local memory and credentials while it is on.
The MaluOS session adds an indicator to the top panel that shows the
agents on the host and lets you start and stop them, the gateway and its
backends, your model budget, your vault secrets and delegations, and the
latest alerts; changes arrive as desktop notifications. There are no
snaps; the browser is Firefox from Mozilla's own apt repository, GNOME
Software installs debs only, and security and MaluOS updates install
themselves through apt (`maluctl update status` shows what is pending).

The desktop is the ninth desktop release and the first that joins an
estate. A desk enrols with an office (`sudo maluctl office enroll`) and
gets its own signing key; every agent in the estate is listed in the
Agents app by what it can do, and a task sent to one of them travels in an
envelope the desk signs, so the node that runs it can verify who asked
and with what authority. An agent that needs a decision asks through
the estate inbox, which arrives as a desktop notification with Approve
and Deny on it. A personal agent (`maluctl agent create me --personal`)
acts for you under your own key with a weekly grant. The machines of an
estate talk over a WireGuard overlay the estate brings up on join. Since
26.04.20261024 the desk also decides grant requests with a level, an
expiry and a budget, re-authenticates through polkit before a reveal,
streams agents' answers, and the System Monitor shows the GPUs the host
shares and the estate's network and queue.
Agents gain a task interface (`maluctl agent send NAME "…"`); the server
images carry it too. It is tested in virtual machines (BIOS and UEFI)
and installed on a laptop and on Proxmox; the graphics stack and the
boot splash have not yet been seen on a range of real hardware. The
desktop needs at least 4 GB of memory and 40 GB of disk; 8 GB or more
is recommended, plus the memory of any local model you run.

## Verify the download

Every release is signed with the MaluOS archive signing key.

```
MaluOS Archive Signing Key (2026) <apt@maluos.com>
Fingerprint: 6387 5A4A 5397 B902 E9C5  CFF8 731A DA39 4135 B9FF
```

Fetch the key from the package repository, check the signature on the
checksum file, then check the file you downloaded:

```sh
V=26.04.20261029
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
2. Choose **Install MaluOS Server** (or **Install MaluOS Desktop** on the
   desktop ISO). The installer asks for language, keyboard, network,
   proxy, disk layout, your user account and SSH access, then installs
   and reboots.
3. For a hands-off install choose the **unattended** entry. It erases
   the first disk without asking, creates the user `maluos` with the
   password `maluos`, and forces a password change at the first login.
4. On the first boot MaluOS provisions itself: the database cluster, the
   tenant, the API, the credential vault and the model gateway. This takes
   a few minutes. On the desktop the login screen appears while this runs
   in the background; log into the **MaluOS** session. On either, check:

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
qemu-img create -f qcow2 -b maluos-26.04.20261029-server-amd64.qcow2 -F qcow2 disk.qcow2 40G
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
