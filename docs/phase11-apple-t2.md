# Phase 11, the Apple T2 round: Intel Macs with the T2 chip

Asked for 2026-10-24 ("before the next release it is critical we support
Apple T2 for the installer and the drivers"), for the Intel Macs of 2018
on; the first machine is a MacBook Pro 15" 2018 (MacBookPro15,1: Core i9
6-core, 32 GB, Intel UHD 630 and a Radeon Pro 560X with 4 GB). Built the
same day on the installer of slices 1-3. The status at the end says what
the build settled and what only the real machine can settle.

## What Ubuntu 26.04's kernel already has, and what it lacks

Kernel 7.0 (linux-generic 7.0.0-38) carries, upstream: the Touch Bar
display (`appletbdrm`) and its keyboard and backlight drivers
(`hid-appletb-kbd`, `hid-appletb-bl`, upstream since 6.15), `apple-gmux`
with the T2's MMIO variant, the Cirrus CS8409 codec, `brcmfmac` for the
Broadcom BCM4364 with Apple's firmware naming, the EFI stub's
`set_os` call for the dual-GPU MacBook Pros (MacBookPro15,1 is in its
list, so the Intel GPU is visible to Linux), the T2 NVMe quirks,
`amdgpu` for the Radeon Pro 560X (Polaris).

It lacks the one driver nothing works without: the T2's **Buffer Copy
Engine** (`apple-bce`), the virtual USB host behind the internal keyboard,
trackpad, Touch Bar, camera and the T2 audio device. The t2linux project
keeps it out of tree (its successor `t2bce` is in their patched kernels,
not mainline). The stock `applesmc` and `bcm5974` do not bind on a T2 Mac
either (fans and temperatures; the trackpad's multitouch), and the Touch
Bar's function row needs a daemon.

## Decisions

1. **The stock kernel, DKMS for the three drivers.** MaluOS keeps
   Ubuntu's kernel (updates, Secure Boot signing, one kernel for every
   machine). `apple-bce` is built from source in packages/apple-bce-dkms
   (the t2linux `aur` branch, commit c7448ca of 2026-06-24, which builds
   against 7.0 unchanged and suspends and resumes); `applesmc-t2` and
   `bcm5974-t2` are the t2linux DKMS packages. DKMS rebuilds them for
   every kernel update (the kernel hooks run dkms before dracut), so an
   update never leaves a Mac without its keyboard.
2. **A component, selected by the installer.** `seeds/apple-t2.seed` is
   the metapackage `maluos-apple-t2`: the three DKMS drivers, DKMS and the
   kernel headers, the audio profiles, Vulkan for the Radeon
   (`mesa-vulkan-drivers`, `libvulkan1`; `vulkan-tools` recommended), and
   as recommends the Touch Bar daemon `tiny-dfr`, the fan daemon
   `t2fanrd`, the firmware script `get-apple-firmware` and the APFS
   driver. The PipeWire DSP `t2-dsp` (speaker and microphone graphs per
   model) is in the repository but off the medium: it would pull PipeWire
   and the LV2 plugins, 150 MB, onto every medium; `apt install t2-dsp` on a
   desktop Mac with the network. The engine adds the component
   when the facts say T2 Mac (`disks.apple()`: SMBIOS vendor Apple and the
   bridge device 106b:1801, or a known model) and the medium's catalogue
   has it; the screens show the Mac on the Welcome screen and pre-select
   the component. The images stay as they are: a server in a VM carries no
   compiler.
3. **The medium carries what the component needs, offline.** The
   component's Ubuntu dependencies the image lacks (DKMS and its
   toolchain, the kernel headers when the image has none, Vulkan: 51
   packages, 105 MB for the server image) go into a flat pool at
   `/maluos/apt/extra` (iso/extra-pool.py, resolved on the build host by
   the host's apt against the image's own dpkg status read out of its
   squashfs, without Ubuntu's recommends) and the target's
   `maluos-iso.sources` gets a second stanza for it. The
   t2linux binaries MaluOS does not build (two Rust daemons, three DKMS
   sources, two sets of configuration, one script) are vendored in
   vendor/apple-t2 with their checksums and go into the MaluOS repository
   like vendor/maludb. The live medium carries the driver parts
   (image/profiles/live.pkgs: the bridge and trackpad drivers built by
   DKMS into the live image), so the installer has the internal keyboard.
4. **The kernel options t2linux documents.** `intel_iommu=on iommu=pt
   pm_async=off` on every T2 Mac: the live menu decides from SMBIOS
   (grub's `smbios` and `regexp`, both in Ubuntu's signed grub), the
   engine writes them into `GRUB_CMDLINE_LINUX` on a T2 Mac. The initrd
   is rebuilt with `apple-bce` (`add_drivers` in a dracut drop-in) so the
   LUKS passphrase can be typed on the internal keyboard.
5. **Apple's firmware never ships; the Mac gives it.** The Broadcom Wi-Fi
   and Bluetooth firmware is Apple's. The owner runs the t2linux
   `firmware.sh` once in macOS (on the medium at `/maluos/apple/`): it
   copies macOS's `/usr/share/firmware` to the EFI partition as
   `firmware-raw.tar.gz`. `maluos-apple-firmware import --auto`
   (maluos-apple-t2-support) finds it on any FAT partition, renames the
   files as the Asahi renamer does (vendored, MIT) and installs them under
   `/lib/firmware/brcm` with a marker file; the live medium runs it at
   boot (`maluos-apple-firmware.service`, gated to Apple hardware by
   `ConditionFirmware=smbios-field`), the engine's new `apple` sub-step
   copies the live medium's import into the target or imports there, and
   the installed system runs the unit again at first boot. When macOS is
   gone, `get-apple-firmware` downloads Apple's recovery image (wired
   network) as t2linux does.
6. **Install beside macOS.** `storage.target: free` keeps the disk's
   partitions and installs into the largest free region: `/boot` (when
   LVM or LUKS) and the root or PV are appended to the GPT with `sfdisk
   --append`, every new partition with its start and size in the disk's
   own sectors (an Apple NVMe has 4096-byte sectors; the erase layout
   counts in the disk's sectors too now), and the Mac's EFI partition is
   shared: mounted at `/boot/efi`, never formatted, shim and grub in
   `EFI/ubuntu` and `EFI/BOOT` beside Apple's loader. UEFI only (no BIOS
   boot partition beside kept partitions). A resume deletes the
   partitions the earlier attempt appended (the journal keeps their
   numbers) before appending again. The screens offer the free space when
   a disk has at least 16G of it beside an EFI partition; the typed
   confirmation stays. t2linux recommends keeping macOS for firmware
   updates; whole-disk erase remains the default.
7. **The Mac's firmware and the boot entry.** `efibootmgr` writes the
   entry with the shared ESP's partition number; when Apple's firmware
   refuses the entry the install warns instead of failing: the disk boots
   from `EFI/BOOT/BOOTX64.EFI` through the Startup Manager (hold Option
   at power-on, choose "EFI Boot"), and the Mac remembers it.
8. **Graphics on the 15-inch.** The Radeon drives the panel by default (the
   firmware's choice when anything but macOS boots; the stock
   `apple-gmux` has no `force_igd`, that switch is a t2linux patch). The
   Intel GPU is visible (the kernel's `set_os`) for offload. Vulkan on the
   Radeon Pro 560X is Mesa's RADV (gfx8); `vulkaninfo --summary` lists it
   and llama.cpp's Vulkan backend uses its 4 GB. ROCm does not support
   Polaris; Vulkan is the inference path. When the Radeon misbehaves on
   mode changes, t2linux's workaround is `amdgpu.dpm=0` in
   `bootloader.cmdline`.
9. **Not in this round.** The t2linux kernel's own patches (the macsmc
   stack, the i915 4-lane quirk for the 15,1, gmux switching to the Intel
   GPU at probe, the 5K amdgpu patch, the APFS driver in-tree): MaluOS
   stays on Ubuntu's kernel. Touch ID (`t2-touchid`, needs fingers
   enrolled in macOS). Suspend: t2linux lists it as partially working per
   model. The internal microphone's low volume is the hardware's.

## The owner's steps on the Mac

1. In macOS: `bash /Volumes/MALUOS_26.04_SERVER/maluos/apple/firmware.sh`
   (or `.../DESKTOP`), choose 1: the firmware goes to the EFI partition.
   Shrink the APFS container in Disk Utility if macOS stays (100G free is
   plenty for a server install; the LVM root takes 50G by default).
2. Startup Security Utility (Command-R at power-on, Utilities menu):
   Secure Boot "No Security", "Allow booting from external media".
3. Hold Option at power-on, choose "EFI Boot" (the medium). The live
   menu's first entry starts the installer with the T2 options; the
   internal keyboard and trackpad work.
4. The installer: the Welcome screen names the Mac; Storage offers "Keep
   the existing partitions and install into the free space"; Components
   has `maluos-apple-t2` ticked; the apple step imports the firmware.
5. After the first boot: `maluos-apple-firmware status` says whether the
   firmware is there; `sudo get-apple-firmware` is the way when it is not;
   `vulkaninfo --summary` lists the Radeon; `systemctl status tiny-dfr
   t2fanrd` for the Touch Bar and the fans.

## Status (2026-10-24)

| Item | Where | Notes |
|---|---|---|
| The driver package | packages/apple-bce-dkms | builds against 7.0.0-38 on the dev host (alias pci:v0000106Bd00001801) |
| The support package | packages/maluos-apple-t2-support 0.1.2 | maluos-apple-firmware (import/copy/status), the boot unit, the Apple-only drop-ins for tiny-dfr and t2fanrd, the dracut drop-in, firmware.sh |
| The vendored packages | vendor/apple-t2 (8 packages) | from the t2linux Ubuntu repository, checksums in the README, verified by tests/apple-t2-test.py |
| The component | seeds/apple-t2.seed, maluos-meta 0.2.10 | in the catalogue as maluos-apple-t2 |
| The installer | maluos-installer 0.3.2 | the facts, storage.target free, the apple sub-step, the T2 options, the initrd, the extra pool source, the screens |
| The medium | iso/build-live-iso.sh, iso/extra-pool.py, iso/grub-live.cfg.in, image/profiles/live.pkgs | the extra pool, /maluos/apple, the SMBIOS-decided options, the drivers in the live image |
| Unit tests | tests/install-plan-test.py (29), tests/apple-t2-test.py (6) | pass |
| The screens in a pty | tests/install-screens-test.py | PASS (the plan equals the unattended plan, target disk) |
| The live image | build/image/maluos-live.squashfs (1.2 GB) | apple-bce and bcm5974 built by DKMS into it at the rootfs build (image/stage-packages.sh runs `dkms autoinstall` for every kernel of the image), maluos-apple-firmware present |
| The medium | the test medium, 3.4 GB | the extra pool: 51 Ubuntu packages, 103 MB, resolved against the image's own dpkg status |
| The firmware unit at boot | maluos-apple-firmware.service | 7 to 11 s wall clock under TCG on the installed disk (Python and lsblk under emulation; half a second on the build host); the "100 s" the live boot's progress line showed was the whole early boot's slowness with this job last in the queue, not the unit's work. On the fake Mac t2fanrd restarted into "failed" without an SMC device: its drop-in now also requires /sys/devices/platform/applesmc.* (support package 0.1.2) |

| Round (2026-10-24/25, TCG on the dev VM, no Mac) | Result |
|---|---|
| server UEFI, `--alongside` (storage.target free: a GPT with an EFI partition and a 4 GB "macOS" partition, the rest free) | PASS, 51 ok / 0 FAIL: the two partitions kept, /boot and the PV appended as partitions 3 and 4, the EFI partition shared (partition 1, Apple's label kept, shim in EFI/ubuntu and EFI/BOOT), the "macOS" partition's content unchanged (sha256), no BIOS boot partition, MaluOS first in the boot order; the install took 20 minutes under TCG. The first attempt installed but did not boot: the fixture's 300 MB FAT32, made with mkfs.vfat's default 16 KiB clusters, has fewer than 65525 clusters and OVMF's FAT driver refuses such a volume (Linux mounts it; a real Mac's EFI partition is Apple's own); the fixture now uses 512-byte clusters. |
| server UEFI, `--apple` (QEMU's SMBIOS says Apple MacBookPro15,1) | PASS, 71 ok / 0 FAIL: the live menu added the T2 options; the installer named the Mac, added maluos-apple-t2 and installed it from the medium's pool (the components sub-step took 28 minutes under TCG, the three DKMS builds inside the target), found no firmware to import (no macOS EFI partition in a VM; the apple sub-step says so and goes on), wrote the T2 options into GRUB_CMDLINE_LINUX and rebuilt the initrd; on the installed system apple-bce, bcm5974 and applesmc are built for its kernel, the initrd carries apple-bce, `intel_iommu=on iommu=pt pm_async=off` is on the command line, tiny-dfr and t2fanrd are installed and gated, vulkaninfo is there, maluos-apple-firmware.service is enabled and `status` names the model. The first attempt failed in the components sub-step on a latent slice 2 bug (engine.run's environment merge raised when a step set DEBIAN_FRONTEND itself; no earlier round installed a component): fixed in maluos-installer 0.3.1 with a unit test. |
| the owner's MacBookPro15,1 (2026-10-25 04:26 UTC, the desktop medium, whole-disk erase) | the medium booted from the Startup Manager, the internal keyboard and trackpad worked (apple-bce in the live image), the 1 TB NVMe was seen, storage took 3 s, the desktop image unpacked in 57 s, configure ran to the components sub-step and FAILED there: the Components screen had maluos-api ticked beside maluos-apple-t2 and the API's Python dependencies (python3-fastapi and friends, 3 MB) were not on the medium (the pool covered the Apple component alone). The retry then failed at storage/check: the disk "has mounted filesystems", the installer's own /target from the first attempt. Two cosmetic findings: the stock applesmc's probe failures printed over the screens, and the live image lacked applesmc-t2. Fixed the same hour: the pool covers every component of the catalogue (apt resolves them against the on-media repository; a component it cannot resolve is marked `offline: false` and refused early on the screen and in the check), the retry ignores its own /target mounts, the console unit lowers the console log level, applesmc-t2 joins the live image (maluos-installer 0.3.2). Not yet seen on the Mac: the bootloader on Apple's firmware, the first boot, audio, the Touch Bar, suspend. |
