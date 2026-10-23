# The install plan (Phase 11)

The install plan is the one document the MaluOS installer executes. The
screens of `maluos-install` build one from the person's answers; an
unattended install reads one from the media, a disk or a URL; the tests
use that path; the desktop's graphical front end builds the same plan.
It replaces subiquity's autoinstall for MaluOS media (docs/phase11-installer.md,
decision 2). This page is the contract: the sections, every key with its
type and default, the layouts, and two complete examples.

A plan is YAML (or JSON) with a top-level `maluos-install` mapping and a
`version`. Unknown keys are an error, not a warning, so a typo cannot
silently change an install. Every key has a default; the smallest valid
plan is the version and a storage target:

```yaml
maluos-install:
  version: 1
  storage:
    disk: first
```

Keys the engine fills in itself are marked *derived*. Values the
screens ask for are marked *asked*; an unattended plan must give them or
accept the default.

## `source`

What is installed.

| Key | Type | Default | Notes |
|---|---|---|---|
| `image` | string | the media's default (`maluos-server` or `maluos-desktop`, from the ISO's menu) | the name of a squashfs under `/maluos/images/` on the media (Phase 11 slice 1 keeps `/casper/` for the live image alone), or a URL (netboot, later) |
| `verify` | bool | true | the squashfs is checked against the media's SHA256SUMS before unpacking; `false` only for experiments |
| `repository` | `media` \| `none` | media | copy the on-media MaluOS repository to the target (`/var/lib/maluos/apt`, a cdrom-style source beside apt.maluos.com), as the late-commands do today |

## `locale`

| Key | Type | Default | Notes |
|---|---|---|---|
| `language` | string | `en_US.UTF-8` | *asked*; the locale generated in the target and set in `/etc/default/locale` |
| `keyboard.layout` | string | `us` | *asked*; `/etc/default/keyboard` |
| `keyboard.variant` | string | empty | |
| `timezone` | string | `UTC` | *asked*; `/etc/localtime`; `auto` picks from the network's geolocation when there is one, else UTC |

## `network`

Written as one netplan file in the target (`/etc/netplan/50-maluos.yaml`),
and applied in the live environment for the install itself when the
plan asks for the network. DHCP on every wired interface is the default
and needs no section.

| Key | Type | Default | Notes |
|---|---|---|---|
| `mode` | `dhcp` \| `static` \| `none` | dhcp | `none` leaves netplan's defaults and does not wait for a link |
| `interface` | string | the first wired interface with a link (*derived*) | for `static` |
| `address` | string | | `static`: CIDR, e.g. `10.0.0.5/24` |
| `gateway` | string | | `static` |
| `nameservers` | list of string | the gateway for `static`; DHCP's otherwise | |
| `search` | list of string | empty | DNS search domains |
| `proxy` | string | empty | *asked*; `http://host:port`, written to apt and to the environment |
| `wifi` | mapping `{ssid, password}` | none | desktop media only; wpa_supplicant through netplan |

## `storage`

Guided layouts only in Phase 11 slice 2; manual partitioning is a later
item. The disk is erased; the plan must say so.

| Key | Type | Default | Notes |
|---|---|---|---|
| `disk` | string | *asked* | `first` (the first non-removable disk that is not the install media), a device path (`/dev/nvme0n1`), `id:` + a `/dev/disk/by-id` name, `serial:` + a serial, or `model:` + a model substring; a plan that matches more than one disk fails |
| `erase` | bool | *asked* | must be `true`; the screens require typing the disk's name |
| `layout` | `direct` \| `lvm` | `lvm` | *asked*; `direct`: GPT, ESP, `/boot` (when encrypted), root; `lvm`: GPT, ESP, `/boot`, one physical volume holding the volume group `maluos` with `root` sized by `root_size` and the rest free (the database and backups can take it later) |
| `root_size` | size \| `all` | `all` for `direct`; `50G` (or the disk when smaller) for `lvm` | |
| `filesystem` | `ext4` \| `xfs` | ext4 | the root filesystem; `xfs` for large database servers |
| `encrypt` | bool | false | *asked*, optional, off unless chosen (the owner's answer 1); LUKS2 on the root (the PV for `lvm`), `/boot` outside it, the passphrase asked at boot |
| `passphrase` | string | | required when `encrypt`; an unattended plan may give it in the clear (the plan is then a secret) or as `file:` + a path on the media |
| `swap` | size \| `none` | `auto` (the smaller of memory and 8G, as a file `/swap.img`) | a swap file; no swap partition |
| `esp_size` | size | `1G` | |
| `boot_size` | size | `2G` | only when `/boot` is separate (`encrypt`, or `layout: lvm`) |
| `label` | string | `maluos` | the root filesystem label |

What the engine does with it: `sfdisk` for the table, `mkfs`,
`cryptsetup luksFormat` and `lvm` when asked, then the mounts under
`/target`, and later the fstab and crypttab from the same facts. A plan
with an impossible layout (the disk too small for the sizes) fails in
`check`, before anything is written.

## `identity`

| Key | Type | Default | Notes |
|---|---|---|---|
| `hostname` | string | `maluos` | *asked*; also the machine's name in the estate |
| `user.name` | string | *asked* | the login; the first user, in `sudo` |
| `user.fullname` | string | the login | |
| `user.password` | string | *asked* | a SHA-512 crypt hash (`$6$…`), or `plain:` + a password for an unattended plan that is kept secret; the screens hash |
| `user.ssh_keys` | list of string | empty | `authorized_keys` lines, or `url:` + a URL (`https://github.com/NAME.keys` works) |
| `user.password_change_required` | bool | false | `true` on the media's unattended plans: the first login must change it |
| `ssh.server` | bool | true on server media, false on desktop | openssh-server enabled in the target |
| `ssh.password_auth` | bool | false | `true` on the media's unattended plans, with `password_change_required` |

## `components`

The metapackages the target carries beyond its image, from
docs/components.md. The ones in the image are already there; a name not
in the image is installed from the on-media repository in the target
(`apt-get install` against the cdrom source) before first boot.

| Key | Type | Default | Notes |
|---|---|---|---|
| `install` | list of string | empty | *asked* from the media's catalogue (`/maluos/catalog.yaml`: name, description from debian/descriptions, size, in-image yes/no) |
| `remove` | list of string | empty | a metapackage of the image to drop (its packages are autoremoved) |

## `firstboot`

Becomes `/etc/maluos/firstboot.yaml` in the target (docs/phase4-firstboot.md),
read by maluos-firstboot on the first boot. Only the keys given are
written; the conffile's documented defaults stand for the rest.

| Key | Type | Default | Notes |
|---|---|---|---|
| `tenant` | string | `maluos` | *asked* |
| `admin.principal` | string | `human:admin` | *asked* |
| `components.<name>` | mapping | enabled for every component installed | component-specific keys pass through |
| `enroll.kind` | `office` \| `estate` | none | *asked* (the owner's answer 3): `office` runs `maluctl office enroll` on the first boot (desks); `estate` enrols the node with Phase 13 slice 1 |
| `enroll.url` | string | | the office's or the estate's address |
| `enroll.code` | string | | the one-time code; `file:` + a path on the media for an unattended plan |
| `enroll.name` | string | the hostname | the desk's or node's name at the office |
| `cloud_init` | bool | true on server media, false on desktop | keep cloud-init enabled in the target (NoCloud and cloud data sources); `false` masks it |

## `bootloader`

| Key | Type | Default | Notes |
|---|---|---|---|
| `mode` | `auto` \| `bios` \| `uefi` \| `both` | auto (*derived* from how the live environment booted) | `both` writes grub for BIOS to the disk and shim and grub to the ESP, for a disk that may move between machines |
| `secure_boot` | `auto` \| `required` \| `ignore` | auto | `required` fails the install when the firmware has Secure Boot off; `auto` only reports it |
| `cmdline` | string | empty | appended to `GRUB_CMDLINE_LINUX_DEFAULT`; the media's server plan gives `console=tty1 console=ttyS0,115200` as the late-commands do today |
| `timeout` | int | 3 (server), 0 (desktop) | grub's menu timeout |
| `efi_entry` | string | `MaluOS` | the NVRAM entry's label |

## `telemetry`

The owner's answer 4 (docs/phase11-installer.md).

| Key | Type | Default | Notes |
|---|---|---|---|
| `send` | bool | *asked* (the screen defaults to send); `false` in the media's unattended plans | one report at the end of the install (and on a failure), shown on the screen before it goes |
| `url` | string | `https://telemetry.maluos.com/v1/install` | |

## `finish`

| Key | Type | Default | Notes |
|---|---|---|---|
| `action` | `reboot` \| `poweroff` \| `shell` \| `none` | reboot | `shell` drops to the live shell with the target still mounted; `none` leaves the live environment running (the tests use it to read the log over the serial console) |
| `eject` | bool | true | |
| `log` | string | `/var/log/maluos-install/` in the target | the engine's log and the plan as run (passwords and passphrases redacted) |

## Where a plan comes from

In this order; the first found wins:

1. `maluos.plan=` on the kernel command line: a URL (`https://…`, fetched
   after the network is up), a path on the media (`/maluos/plan/server-unattended.yaml`),
   or a label and path on another disk (`LABEL=PLANS:/laptop.yaml`).
2. `/maluos/plan/default.yaml` on the media, when present (a custom
   media built with one).
3. None: the screens run.

`maluos.ssh=` on the kernel command line (a URL or an `authorized_keys`
line) starts the SSH server in the live environment for a remote install
(the owner's answer 2); the plan is then given to `maluos-install --plan`
over SSH, or the screens are used in that terminal.

## Examples

**The media's unattended server plan** (`/maluos/plan/server-unattended.yaml`;
the menu entry "Install MaluOS Server unattended" points at it):

```yaml
maluos-install:
  version: 1
  source: {image: maluos-server}
  locale: {language: en_US.UTF-8, keyboard: {layout: us}, timezone: UTC}
  network: {mode: dhcp}
  storage: {disk: first, erase: true, layout: lvm, root_size: 50G, encrypt: false}
  identity:
    hostname: maluos
    user: {name: maluos, password: "$6$…", password_change_required: true}
    ssh: {server: true, password_auth: true}
  firstboot: {tenant: maluos, admin: {principal: human:admin}}
  bootloader: {cmdline: "console=tty1 console=ttyS0,115200"}
  telemetry: {send: false}
  finish: {action: reboot}
```

**A desk for a person, installed over SSH and enrolled with the office:**

```yaml
maluos-install:
  version: 1
  source: {image: maluos-desktop}
  locale: {language: en_GB.UTF-8, keyboard: {layout: gb}, timezone: Europe/London}
  storage: {disk: "model:Samsung SSD 990", erase: true, layout: direct, encrypt: true, passphrase: "file:/run/media/plans/pass.txt"}
  identity:
    hostname: ed-desk
    user: {name: ed, fullname: "Ed Honour", password: "$6$…", ssh_keys: ["url:https://github.com/maludb.keys"]}
    ssh: {server: false}
  components: {install: [maluos-tools]}
  firstboot:
    enroll: {kind: office, url: "https://app.example.com", code: "file:/run/media/plans/code.txt", name: "Ed's desk"}
  telemetry: {send: true}
  finish: {action: reboot}
```

## Validation

`maluos-install --plan FILE --check` validates without touching a disk:
the schema, the disk match (listing what `first` or `model:` resolves
to), the layout's fit, the network reachability of URLs, the presence of
the image on the media and its hash, and prints the plan as the engine
understood it with the defaults filled in. The ISO build runs `--check`
on the media's plans, as it validates the autoinstall today.
