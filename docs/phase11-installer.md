# Phase 11: the MaluOS installer

Planned 2026-10-23. Nothing here is built. The ISO today is Ubuntu's
server live installer with a MaluOS root filesystem as its install
source (docs/phase2-iso.md): the person boots into Ubuntu's live
environment, Ubuntu's text splash, Ubuntu's subiquity screens, and gets
MaluOS at the end. Phase 11 replaces that environment and those screens
with ours, so that the installer is the first MaluOS thing a person
sees, and so that the install itself (disks, user, network, unpacking
the squashfs, seeding first boot) is one tool we own, drive unattended
in the tests and extend for the desktop and the estate.

## What exists to build on

- **The root filesystems.** image/build-rootfs.sh builds a server or
  desktop rootfs from the seeds with mmdebstrap and squashes it; the ISO
  carries it as `/casper/maluos-PROFILE.squashfs`. The installer's job is
  to put that on a disk; nothing in the rootfs is installer-specific.
- **First boot.** maluos-firstboot provisions the memory database, the
  tenant, the administrator and the components from
  /etc/maluos/firstboot.yaml on the first boot (docs/phase4-firstboot.md).
  The installer seeds that file and nothing else about the database; the
  install stays a copy-and-configure.
- **The components.** docs/components.md: a component is a metapackage,
  its packages, a first-boot module and a `components.<name>` key in
  firstboot.yaml. The installer's component step writes that key and, for
  a component not in the image, installs its packages from the on-media
  repository (`/maluos/apt`).
- **The on-media repository.** iso/build-iso.sh copies the published
  MaluOS repository and the PGDG source onto the ISO; the installed system
  has them as a cdrom source until the network source is enabled. The
  installer keeps this.
- **The ISO assembly.** xorriso, with the boot images replayed from
  Ubuntu's ISO. Phase 11 assembles its own boot images: grub for BIOS
  (grub-pc-bin) and the signed shim and grub for UEFI (shim-signed,
  grub-efi-amd64-signed), all in the archive.
- **casper.** Ubuntu's live-boot initramfs (package `casper`, in the
  archive) is what boots the live squashfs today, from Ubuntu's initrd.
  With our own live rootfs and our own initrd built from it, casper boots
  our squashfs the same way. It is a boot mechanism, not a surface.
- **The tests.** tests/iso-boot-test.sh installs from the ISO under
  QEMU (BIOS and UEFI) and checks the installed system over SSH;
  tests/iso-apt-check.sh replays the installer's apt step without
  booting; tests/qcow2-boot-test.sh checks the provisioned system. All
  three carry over; the first one drives the new installer unattended.
- **Branding.** The plymouth theme, the grub theme text, os-release and
  the logo (Phase 3, Phase 12 slice 4) are packages; the live rootfs
  carries them like any other.

Not in the archive: curtin, the engine beneath subiquity, is no longer a
Debian package in 26.04, nor is debian-installer. The engine is ours.

## Decisions

1. **A live rootfs of our own, booted by casper.** A third profile,
   `live`, built by image/build-rootfs.sh from seeds/live.seed:
   maluos-base, the branding, casper, the installer, network-manager or
   netplan with the tools, openssh-server (off by default; on with a
   boot option for remote installs), the console fonts and keymaps, no
   database. Its kernel and initrd (built inside it, with casper's hooks
   and the plymouth theme) replace Ubuntu's on the ISO. The target
   squashfs stays separate on the media: one live image, one or more
   install images beside it.
2. **One engine, two faces.** `maluos-install` (package
   maluos-installer, Python like maluctl) is an engine that executes an
   **install plan**, a YAML document with the same sections the screens
   have (locale, keyboard, network, storage, identity, components,
   firstboot, bootloader). The text UI builds a plan and runs it; an
   unattended install reads one from the media or a URL; the tests use
   that path; the desktop's graphical front end (slice 5) builds the same
   plan. The plan replaces autoinstall; cloud-init stays for first boot
   only (NoCloud on the media is still how the unattended plan seeds
   /etc/maluos/firstboot.yaml and the SSH keys today, and the engine can
   write both directly).
3. **Text UI in urwid.** python3-urwid is in main, is what subiquity
   itself draws with, and runs on a serial console, which matters for
   servers and for the tests. Not whiptail (too little) and not textual
   (a heavier dependency with a shorter record on bare consoles).
4. **The engine's steps**, each a Python module with `plan`, `check`,
   `apply` and `summary`, idempotent where it can be, so a failed install
   can be resumed from its log:
   - *storage*: guided whole-disk layouts only in slice 2 (GPT; ESP
     1 GiB; root ext4, or LVM with root and a free remainder; optional
     LUKS on the root with a passphrase); swap as a file; the disk chosen
     from a list with model, size and bus; "use the free space" and
     manual partitioning later. sfdisk, mkfs, cryptsetup, lvm2.
   - *unpack*: unsquashfs of the target image onto the mounted layout
     (or mount and copy with reflinks on btrfs later); the squashfs is
     verified against the ISO's SHA256SUMS first.
   - *configure* (in the target, with a bind-mounted /dev, /proc, /sys):
     fstab and crypttab from the layout; hostname; locale, keyboard,
     timezone; the network as a netplan file (DHCP by default, static
     from the plan); the user with the password hash and the SSH keys,
     sudo; the apt sources (the cdrom source for the on-media repository,
     the network sources present but disabled until first boot, as now);
     the components (apt from the media when needed) and
     /etc/maluos/firstboot.yaml; the machine-id cleared; the kernel
     command line (serial console for the server profile as the
     late-commands do today).
   - *bootloader*: grub-install for BIOS on the chosen disk, and for
     UEFI the signed shim and grub into the ESP with an NVRAM entry
     (efibootmgr), from the target's own packages so Secure Boot works
     as it does for Ubuntu; update-initramfs in the target.
   - *finish*: the log and the plan as run copied to
     /var/log/maluos-install/ in the target, media ejected, reboot.
5. **Unattended first.** Slice 2 ships the engine and the unattended
   path before any screen exists, because that is what the CI and the
   boot tests need, and because the screens are a front end over it.
6. **Parity before the switch.** The subiquity ISO keeps being built and
   released until the MaluOS installer passes the same tests on BIOS and
   UEFI, with Secure Boot verified on one real machine; then the base
   ISO, the autoinstall directory and the casper layer trick go.
7. **The desktop installs from the same media.** The desktop ISO is the
   same live environment with the desktop squashfs as its target; the
   graphical live session with an installer window (GTK over the same
   engine) is slice 5, after the text installer is the default for both
   variants.
8. **No Ubuntu on any surface.** The live environment's splash, grub
   menu, console banner, the installer's title and its help text are
   MaluOS. The one visible exception, kept on purpose, is the Secure Boot
   chain: Ubuntu's signed shim and grub, so that MaluOS boots on machines
   with Secure Boot on without a key of our own in their firmware; the
   plan says so in the bootloader step's summary.

## Slices

### Slice 1: the live environment and the ISO we assemble

Specified in docs/phase11-slice1-live.md and built 2026-10-24 (its status section).

Specified in docs/phase11-slice1-live.md (2026-10-23): the live seed,
the media layout, the boot chain, the stub installer package, the
assembly script and the test.

- seeds/live.seed and the `live` profile: a rootfs with casper, the
  branding, the network tools, openssh-server (started only by the
  `maluos.ssh=` boot option), the installer package (empty at this
  point: a banner and a shell).
- The live initrd and kernel built in that rootfs (update-initramfs
  with casper's hooks; the plymouth theme in it so the live boot shows
  MaluOS, which Phase 12 slice 4 could not do with Ubuntu's initrd).
- iso/build-iso.sh assembles the ISO from scratch: the live squashfs,
  the target squashfs(es), the on-media repository, grub for BIOS (an
  El Torito image from grub-pc-bin) and for UEFI (an ESP image holding
  shim-signed and grub-efi-amd64-signed with our grub.cfg), the volume
  id, SHA256SUMS of the images on the media. The subiquity ISO is built
  by the old path beside it until slice 4.
- Test: the ISO boots under QEMU on BIOS and UEFI (OVMF) to the live
  login on the serial console, the media is mounted, the target squashfs
  is readable and its hash matches; the plymouth splash is ours (checked
  by the theme's files in the initrd, not by looking).

### Slice 2: the engine and the unattended install

Specified in docs/phase11-slice2-engine.md (2026-10-23): the steps and
their commands, the four layouts, the journal and resume, the events,
the SSH option, the telemetry document and endpoint, the tests.

- maluos-installer: `maluos-install --plan FILE|URL [--dry-run]`, the
  plan schema (docs/install-plan.md), the steps of decision 4 for the
  guided whole-disk layouts (ext4, LVM, LUKS), the log, the resume.
- The media carries `/maluos/plan/` with an unattended server plan and
  an unattended desktop plan (the erase-the-first-disk, login maluos,
  password change required variant of today's menu), and the grub menu
  gets "Install MaluOS unattended" pointing at them (`maluos.plan=`
  on the kernel command line; a URL works for network installs).
- Remote installs: `maluos.ssh=URL|KEY` on the kernel command line
  starts openssh-server in the live environment with those keys for the
  live user, so `ssh maluos@HOST maluos-install --plan URL` installs a
  headless machine from another one (the owner's answer 2).
- tests/iso-boot-test.sh installs with the plan on BIOS and UEFI and
  runs the Phase 4 checks on the installed system, once from the media's
  plan and once over SSH; tests/iso-apt-check.sh replays the installer's
  apt step against the new media layout.
- Test on a real machine once: BIOS, UEFI, UEFI with Secure Boot.

### Slice 3: the screens

- The urwid front end: welcome and language; keyboard; network (the
  interfaces, DHCP or static, a proxy; "continue without network" is
  always allowed because the media has the repository); storage (the
  disks, the guided layouts, LUKS and its passphrase, a summary of what
  will be erased, typed confirmation); identity (hostname, name, login,
  password with strength shown, SSH keys by paste or by GitHub login
  over the network); components (the metapackages the media offers,
  with their descriptions from debian/descriptions, the ones in the
  image pre-selected); first boot (tenant name, administrator principal;
  an enrolment code and address to join an office or, with Phase 13
  slice 1, an estate on the first boot, the owner's answer 3);
  telemetry (the report shown, Send or Don't send, the owner's answer 4);
  summary; progress with the engine's log; done, reboot.
- Every screen writes to the plan; "Save the plan" on the summary
  screen writes it to a USB stick or shows it, for the next machine.
- Test: the front end driven by a keystroke script on the serial console
  (an expect-style driver in tests/), producing the same plan the
  unattended path uses; the plan compared; the install then runs as in
  slice 2.

### Slice 4: parity and the switch

- Both variants install from the new ISO on BIOS, UEFI and Secure Boot
  (one real machine each way); the release pipeline (scripts/release.sh,
  the workflows) builds and tests only the new ISO; the base Ubuntu ISO,
  autoinstall/ and the cdrom-layer code are removed; docs/phase2-iso.md
  and docs/release.md updated; the download page says what the
  installer is.
- The last Ubuntu-branded surfaces checked off: the live boot, the
  installer, the installed system's first boot (already ours), GNOME's
  help on the desktop (docs/phase12-desktop.md "After that" 3).

### Slice 5: the graphical live session and installer (desktop)

- The desktop ISO boots into a GNOME live session (the desktop rootfs
  as the live image, a live user, the session's agent features off) with
  "Install MaluOS" on the dock: a GTK 4/libadwaita front end over the
  same engine and plan, the screens of slice 3 as pages.
- Test: the live session reaches GNOME under the boot test's display,
  the installer window builds from a plan (`--self-test` as the other
  windows have), the install runs unattended from the live session.

### Later

Manual partitioning and "use the free space"; RAID and ZFS; reinstall
keeping /home and the database; OEM mode (install now, identity on first
boot); netboot (PXE) with the plan from a URL and the images from
apt.maluos.com; arm64 media; an estate-enrolled install (Phase 13: the
plan carries the enrolment code so the machine joins the estate on
first boot).

## The test machine

The boot tests run under QEMU with TCG on the dev host and with KVM in
CI. Secure Boot is tested with OVMF's secure variant and the Microsoft
keys enrolled (`ovmf` ships `OVMF_VARS_4M.ms.fd`), which is what Ubuntu's
signed shim is for; one real machine confirms it before slice 4.

## The owner's answers (2026-10-23)

1. **LUKS is optional during install.** A switch on the storage screen
   and a key in the plan, off unless the person turns it on, on both
   variants; the earlier idea of on-by-default for the desktop is
   dropped. Unattended unlocking for servers (TPM) stays a later item.
2. **Remote installs over SSH: yes.** In slice 2: openssh-server in the
   live environment, started by the boot option `maluos.ssh=URL|KEY`
   (keys fetched from a URL or given on the command line), the live
   user `maluos` with no password, so a headless server is installed
   from another machine with `ssh maluos@… maluos-install --plan …` or
   the screens over SSH in slice 3.
3. **Estate enrolment at install time: yes.** The first-boot screen (and
   the plan's `firstboot` section) takes an enrolment code and an
   address: for the desktop it is `maluctl office enroll` run on first
   boot (what exists today, Phase 12 slice 6); for a server it is the
   estate's node enrolment once Phase 13 slice 1 exists. Slice 3 ships
   the screen and the desk path; the server path lands with Phase 13
   slice 1.

5. **The text installer first, then the graphical one.** The slice
   order stands as written: slices 1 to 4 give both variants the text
   installer, slice 5 the graphical one for the desktop.

4. **Telemetry: yes.** The installer offers to report the install to
   MaluOS. What is proposed, for the owner to adjust:
   - *What is sent*: one JSON document at the end of a successful
     install, and one on an installer failure with the engine's log
     tail: the MaluOS release and variant, the installer version, the
     components chosen, the layout chosen (ext4/LVM, LUKS yes/no, disk
     size), the hardware class (CPU model and count, memory, disk count
     and sizes, graphics vendor, firmware BIOS/UEFI, Secure Boot on/off,
     virtual or physical), the language, keyboard and timezone, how long
     the install took, and a random install id generated for the report.
     No hostname, user name, IP address, MAC address, serial number or
     enrolment detail; the document is shown on the screen before it is
     sent.
   - *Where*: `https://telemetry.maluos.com/v1/install`, a small
     endpoint beside the download site (a Worker writing to R2, like
     the rest of Phase 10's hosting), with a dashboard later.
   - *The screen*: "Help improve MaluOS", in slice 3 after the first-boot
     screen, with the report shown and a Send / Don't send choice; the
     plan carries `telemetry: {send: true|false}` so an unattended plan
     decides it, and the media's unattended plans say `false`. Default on
     the screen: **send**, as Ubuntu does (the owner's answer; set to
     off if preferred).
   - *First boot*: the installed system sends nothing. Reporting from
     running machines (updates, versions) is a separate decision for the
     editions work (Phase 9), not part of this.
   The endpoint and the sending code land in slice 2 (the unattended
   path sends when its plan says so); the screen in slice 3.

## Open questions for the owner

None; the five answers above decide the plan. Still to confirm when
slice 3 is cut: the telemetry screen's default (send, as proposed).
