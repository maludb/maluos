#!/bin/bash
# Phase 11 slice 2: the live medium installs MaluOS unattended from its plan, the installed
# disk boots, and the system is the one the plan asked for. Boots the --test-install medium
# under QEMU with an empty 24 GB disk (the default entry runs /maluos/plan/test.yaml), reads
# the serial console for "maluos-install: finished (reboot)", then boots the disk, waits for
# SSH and first boot, and checks the layout, fstab, swap, cmdline, the evidence, the user,
# firstboot.yaml, cloud-init, the bootloader entry and the Phase 2 and 4 stack.
#
# usage: tests/live-install-test.sh [--uefi] [-p server|desktop] [--ssh] [--encrypt] [--screens] [--layout direct|lvm] [--fs ext4|xfs] [--alongside] [--apple] [--boot-only]
#   --boot-only  skip the medium and the install: boot the disk an earlier run installed and verify it again
#   --alongside  (the Apple T2 round) the disk starts with a GPT, an EFI partition and a 4 GB "macOS" partition with the
#                rest free; the plan has storage.target free; the kept partitions are verified unchanged (UEFI)
#   --apple      (the Apple T2 round) QEMU claims to be an Apple MacBookPro15,1 through SMBIOS: the live menu adds the
#                T2 kernel options, the installer adds the apple-t2 component from the medium (DKMS builds in the
#                target), the kernel command line and the initrd are verified
#   --screens    (slice 3) the --test-ssh medium boots to the autologin shell on the serial console and
#                tests/lib/screens_driver.py answers the installer's screens there (login maluos, the test key,
#                lvm ext4); the verification then also reads the plan the screens left in /var/log/maluos-install
#   --ssh      boots the --test-ssh medium (maluos.ssh=media, no plan), runs the install over SSH with --json
#   --encrypt  the plan with an encrypted root; the LUKS prompt on the serial console is answered by
#              tests/lib/serial-answer.py (dev VM; not in CI yet)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-/var/tmp/maluos-install-test}
UEFI=0; PROFILE=server; SSH=0; ENCRYPT=0; LAYOUT=lvm; FS=ext4; BOOTONLY=0; SCREENS=0; FREE=0; APPLE=0
while [ $# -gt 0 ]; do case "$1" in
    --uefi) UEFI=1; shift ;; -p) PROFILE=$2; shift 2 ;; --ssh) SSH=1; shift ;; --encrypt) ENCRYPT=1; shift ;;
    --layout) LAYOUT=$2; shift 2 ;; --fs) FS=$2; shift 2 ;; --boot-only) BOOTONLY=1; shift ;; --screens) SCREENS=1; shift ;;
    --alongside) FREE=1; UEFI=1; shift ;; --apple) APPLE=1; shift ;; *) echo "bad arg $1" >&2; exit 2 ;; esac; done
INSTALL_TIMEOUT=${INSTALL_TIMEOUT:-$([ $APPLE = 1 ] && echo 9000 || echo 5400)}; BOOT_TIMEOUT=${BOOT_TIMEOUT:-1200}; FIRSTBOOT_TIMEOUT=${FIRSTBOOT_TIMEOUT:-2400}
SSHPORT=${SSHPORT:-2226}
ACCEL=$([ -w /dev/kvm ] && echo kvm || echo tcg)
PASS=maluos-test-passphrase
FW=$([ $UEFI = 1 ] && echo uefi || echo bios)
TAG=$PROFILE-$FW$([ $SSH = 1 ] && echo -ssh || true)$([ $SCREENS = 1 ] && echo -screens || true)$([ $ENCRYPT = 1 ] && echo -enc || true)$([ $FREE = 1 ] && echo -free || true)$([ $APPLE = 1 ] && echo -apple || true)-$LAYOUT-$FS
mkdir -p "$WORK"; cd "$WORK"
ss -ltn | grep -q ":$SSHPORT " && { echo "port $SSHPORT busy (a previous test VM?)" >&2; exit 1; }
[ -f testkey ] || ssh-keygen -q -t ed25519 -N '' -f testkey -C maluos-install-test
if [ $BOOTONLY = 1 ]; then rm -f "boot-$TAG.log" "serial-$TAG.sock"; [ -f "disk-$TAG.qcow2" ] || { echo "no disk-$TAG.qcow2 to boot" >&2; exit 1; }
else rm -f "install-$TAG.log" "boot-$TAG.log" "disk-$TAG.qcow2" "serial-$TAG.sock" "ssh-install-$TAG.log"; fi

[ $BOOTONLY = 0 ] && echo "== building the medium ($PROFILE, $([ $SSH = 1 ] && echo --test-ssh || echo --test-install), layout $LAYOUT $FS$([ $ENCRYPT = 1 ] && echo ', encrypted' || true))"
export TEST_PLAN_LAYOUT=$LAYOUT TEST_PLAN_FS=$FS
[ $ENCRYPT = 1 ] && export TEST_PLAN_ENCRYPT=$PASS
[ $FREE = 1 ] && export TEST_PLAN_TARGET=free
[ $BOOTONLY = 1 ] || "$ROOT/iso/build-live-iso.sh" -p "$PROFILE" $([ $SSH = 1 ] || [ $SCREENS = 1 ] && echo --test-ssh || echo --test-install) --ssh-key testkey.pub \
    -o "$WORK/maluos-install-test-$PROFILE.iso" > "build-$TAG.log" 2>&1 || { tail -30 "build-$TAG.log"; exit 1; }
P2SUM=none
if [ $FREE = 1 ]; then
    # a disk as a Mac leaves it after Disk Utility shrank macOS: GPT, the EFI partition (FAT, 300 MB), a 4 GB "macOS"
    # partition (APFS type, random content whose first 4 MiB are checksummed), the rest free
    if [ $BOOTONLY = 0 ]; then
        rm -f "disk-$TAG.raw"; truncate -s 24G "disk-$TAG.raw"
        printf 'label: gpt\nsize=300M, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name="EFI"\nsize=4G, type=7C3457EF-0000-11AA-AA11-00306543ECAC, name="Macintosh HD"\n' | sfdisk -q "disk-$TAG.raw" >/dev/null
        # 512-byte clusters: a 300 MB FAT32 with mkfs.vfat's default 16 KiB clusters has fewer than 65525 clusters, which
        # OVMF's FAT driver refuses (Linux mounts it; the install succeeds; the disk then does not boot)
        mkfs.vfat -F 32 -s 1 -n EFI --offset 2048 "disk-$TAG.raw" $((300 * 1024)) >/dev/null
        dd if=/dev/urandom of="disk-$TAG.raw" bs=1M seek=301 count=4 conv=notrunc status=none
        qemu-img convert -q -f raw -O qcow2 "disk-$TAG.raw" "disk-$TAG.qcow2"
        dd if="disk-$TAG.raw" bs=1M skip=301 count=4 status=none | sha256sum | cut -d' ' -f1 > "p2sum-$TAG"
        rm -f "disk-$TAG.raw"
    fi
    P2SUM=$(cat "p2sum-$TAG")
else
    [ $BOOTONLY = 1 ] || qemu-img create -q -f qcow2 "disk-$TAG.qcow2" 24G
fi
case "$PROFILE" in desktop) MEM=${MEM:-3072}; SMP=${SMP:-4} ;; *) MEM=${MEM:-2560}; SMP=${SMP:-2} ;; esac
QEMU=(qemu-system-x86_64 -machine q35,accel=$ACCEL -cpu max -smp $SMP -m $MEM
      -drive file="disk-$TAG.qcow2",if=virtio,format=qcow2
      -netdev user,id=n0,hostfwd=tcp:127.0.0.1:$SSHPORT-:22 -device virtio-net-pci,netdev=n0
      -display none -monitor none)
# --apple: SMBIOS says Apple MacBookPro15,1 (the comma doubled for QEMU's option parser); grub, the kernel's DMI and the
# installer's facts all see a T2 Mac, and the apple-t2 component installs from the medium without the hardware
[ $APPLE = 1 ] && QEMU+=(-smbios "type=1,manufacturer=Apple Inc.,product=MacBookPro15,,1,version=1.0,serial=C02TEST000001")
if [ $UEFI = 1 ]; then
    [ $BOOTONLY = 1 ] && [ -f "vars-$TAG.fd" ] || cp /usr/share/OVMF/OVMF_VARS_4M.fd "vars-$TAG.fd"
    QEMU+=(-drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd -drive if=pflash,format=raw,file="vars-$TAG.fd")
fi
ssh_opts=(-p "$SSHPORT" -i testkey -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -o LogLevel=ERROR)
wait_ssh() {  # $1 user, $2 timeout
    local deadline=$(( $(date +%s) + $2 ))
    until ssh "${ssh_opts[@]}" "$1@127.0.0.1" true 2>/dev/null; do
        kill -0 "$QPID" 2>/dev/null || { echo "FAIL: qemu exited"; tail -20 "${3:-/dev/null}"; return 1; }
        [ $(date +%s) -lt $deadline ] || { echo "FAIL: no SSH for $1 within $2 s"; tail -20 "${3:-/dev/null}"; return 1; }
        sleep 10
    done
}

echo "== install phase ($ACCEL, $FW); serial -> $WORK/install-$TAG.log"
start=$(date +%s)
if [ $BOOTONLY = 1 ]; then rc=0; echo "   skipped (--boot-only)"
elif [ $SCREENS = 1 ]; then
    # the screens on the serial console: QEMU's serial on a socket, the driver types the answers
    "${QEMU[@]}" -cdrom "maluos-install-test-$PROFILE.iso" -boot d -no-reboot -serial "unix:serial-$TAG.sock,server=on,wait=off" > "qemu-install-$TAG.log" 2>&1 & QPID=$!
    trap 'kill $QPID 2>/dev/null || true' EXIT
    python3 "$ROOT/tests/lib/screens_driver.py" --serial "serial-$TAG.sock" --log "install-$TAG.log" --disk vda --key testkey.pub --sudo --no-change --echo || true
    timeout 600 tail --pid=$QPID -f /dev/null; rc=0; kill -0 $QPID 2>/dev/null && { echo "FAIL: the live VM did not reboot after the screens' install"; exit 1; }
    trap - EXIT
elif [ $SSH = 0 ]; then
    timeout "$INSTALL_TIMEOUT" "${QEMU[@]}" -cdrom "maluos-install-test-$PROFILE.iso" -boot d -no-reboot -serial "file:install-$TAG.log" > "qemu-install-$TAG.log" 2>&1 && rc=0 || rc=$?
else
    "${QEMU[@]}" -cdrom "maluos-install-test-$PROFILE.iso" -boot d -no-reboot -serial "file:install-$TAG.log" > "qemu-install-$TAG.log" 2>&1 & QPID=$!
    trap 'kill $QPID 2>/dev/null || true' EXIT
    wait_ssh maluos 900 "install-$TAG.log" || exit 1
    echo "   live environment reachable over SSH (maluos.ssh=media); running the install with --json"
    ssh "${ssh_opts[@]}" maluos@127.0.0.1 'sudo maluos-install --plan /cdrom/maluos/plan/test.yaml --json' > "ssh-install-$TAG.log" 2>&1 || true
    timeout 300 tail --pid=$QPID -f /dev/null; rc=0; kill -0 $QPID 2>/dev/null && { echo "FAIL: the live VM did not reboot after the install"; exit 1; }
    trap - EXIT
fi
echo "   installer VM exited rc=$rc after $(( $(date +%s) - start ))s"
if [ $BOOTONLY = 1 ]; then :
elif [ $SSH = 1 ] && grep -q '"state": "fail"' "ssh-install-$TAG.log"; then
    echo "FAIL: the install over SSH reported a failure:"; grep '"state": "fail"' "ssh-install-$TAG.log" | tail -3; exit 1
fi
if grep -aq 'maluos-install: FAILED' "install-$TAG.log"; then
    echo "FAIL: $(grep -m1 'maluos-install: FAILED' "install-$TAG.log")"; echo "--- last 40 lines of the serial console:"; tail -40 "install-$TAG.log"; exit 1
fi
if [ $BOOTONLY = 0 ]; then
    if ! grep -aq 'maluos-install: finished (reboot)' "install-$TAG.log" "ssh-install-$TAG.log" 2>/dev/null; then
        echo "FAIL: no 'maluos-install: finished (reboot)' on the console (rc=$rc)"; tail -40 "install-$TAG.log"; exit 1
    fi
    echo "  ok   maluos-install: finished (reboot)"
    grep -q 'Secure Boot: Ubuntu' "install-$TAG.log" "ssh-install-$TAG.log" 2>/dev/null && echo "  ok   the bootloader summary names the signed chain" || echo "  warn no bootloader summary line on the console"
fi

echo "== boot phase: the installed disk"
if [ $ENCRYPT = 1 ]; then
    "${QEMU[@]}" -boot c -serial "unix:serial-$TAG.sock,server=on,wait=off" > "qemu-boot-$TAG.log" 2>&1 & QPID=$!
    python3 "$ROOT/tests/lib/serial-answer.py" "serial-$TAG.sock" "boot-$TAG.log" "$PASS" & APID=$!
    trap 'kill $QPID $APID 2>/dev/null || true' EXIT
else
    "${QEMU[@]}" -boot c -serial "file:boot-$TAG.log" > "qemu-boot-$TAG.log" 2>&1 & QPID=$!
    trap 'kill $QPID 2>/dev/null || true' EXIT
fi
wait_ssh maluos "$BOOT_TIMEOUT" "boot-$TAG.log" || exit 1
echo "   SSH up; waiting for first-boot provisioning (up to $FIRSTBOOT_TIMEOUT s)"
deadline=$(( $(date +%s) + FIRSTBOOT_TIMEOUT ))
until ssh "${ssh_opts[@]}" maluos@127.0.0.1 'test -f /var/lib/maluos/firstboot/done' 2>/dev/null; do
    [ $(date +%s) -lt $deadline ] || { echo "FAIL: first boot did not finish"; ssh "${ssh_opts[@]}" maluos@127.0.0.1 'systemctl status maluos-firstboot --no-pager | tail -15' || true; exit 1; }
    sleep 15
done

echo "== verifying the installed system"
ssh "${ssh_opts[@]}" maluos@127.0.0.1 "bash -s -- $UEFI $LAYOUT $ENCRYPT $PROFILE $FS $SCREENS $FREE $APPLE $P2SUM" <<'REMOTE' | tee "verify-$TAG.log"
UEFI=$1; LAYOUT=$2; ENCRYPT=$3; PROFILE=$4; FS=$5; SCREENS=${6:-0}; FREE=${7:-0}; APPLE=${8:-0}; P2SUM=${9:-none}
fail=0; ok() { echo "  ok   $1"; }; bad() { echo "  FAIL $1"; fail=1; }
root() { echo maluos | sudo -S -p '' "$@"; }     # the test plan's user has the password maluos and ordinary sudo
installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'; }
. /etc/os-release; cat /etc/maluos-release | head -1
[ "$ID" = maluos ] && echo "$ID_LIKE" | grep -q ubuntu && ok "os-release identifies MaluOS" || bad "os-release"
root grep -m1 '^menuentry' /boot/grub/grub.cfg | grep -q MaluOS && ok "GRUB menu names MaluOS" || bad "grub distributor"
# Phase 2 and 4: the stack
for p in maluos-server maluos-base maluos-archive maluos-keyring postgresql-18 postgresql-18-maludb-core maludb-mc2dbd maluos-firstboot; do
  installed $p && ok "$p installed" || bad "$p"; done
systemctl is-active --quiet postgresql@18-main && ok "postgresql@18-main active" || bad "postgresql@18-main"
root maluctl status | grep -q '^provisioned: 20' && ok "maluctl status: provisioned" || { bad "maluctl status"; root maluctl status; }
root maluctl status | grep -q 'tenant:      maluos' && ok "tenant maluos (firstboot.yaml from the plan)" || bad "tenant"
# the layout
src=$(findmnt -no SOURCE /)
if [ "$LAYOUT" = lvm ]; then
  [ "$src" = /dev/mapper/maluos-root ] && root lvs --noheadings -o vg_name,lv_name | grep -q 'maluos *root' && ok "root is LV root in VG maluos ($src)" || bad "root device $src (expected LV maluos/root)"
  findmnt -no SOURCE /boot | grep -qE '^/dev/' && ok "/boot is its own partition ($(findmnt -no SOURCE /boot))" || bad "/boot not mounted"
  [ "$FREE" = 1 ] && { findmnt -no SOURCE /boot | grep -qE '^/dev/(vd|sd)a3$' && ok "/boot is partition 3, after the two kept partitions" || bad "/boot is $(findmnt -no SOURCE /boot)"; }
  root vgs --noheadings -o vg_free maluos | grep -qvE '^\s*0 ' && ok "the VG has free space for later ($(root vgs --noheadings -o vg_free maluos | tr -d ' '))" || ok "the VG is fully used (small disk)"
else
  if [ "$ENCRYPT" = 1 ]; then [ "$src" = /dev/mapper/maluos-root ] && ok "root is the LUKS mapping maluos-root" || bad "root device $src"
  else echo "$src" | grep -qE '^/dev/(vd|sd)a3$' && ok "root is partition 3 ($src)" || bad "root device $src (expected partition 3)"; fi
fi
[ "$ENCRYPT" = 1 ] && { root cryptsetup status maluos-root 2>/dev/null | grep -q 'is active' || root cryptsetup status maluos-pv 2>/dev/null | grep -q 'is active'; } && ok "cryptsetup status: the LUKS device is active" || [ "$ENCRYPT" = 0 ] || bad "cryptsetup status"
[ "$ENCRYPT" = 1 ] && { grep -q 'rd.luks.name=' /proc/cmdline && ok "rd.luks.name on the kernel command line" || bad "rd.luks.name missing"; }
findmnt -no FSTYPE / | grep -q "^$FS$" && ok "root filesystem is $FS" || bad "root filesystem $(findmnt -no FSTYPE /)"
findmnt /boot/efi >/dev/null && ok "/boot/efi mounted (vfat ESP)" || bad "/boot/efi"
if [ "$FREE" = 1 ]; then   # storage.target free: the kept partitions untouched, the EFI partition shared
  findmnt -no SOURCE /boot/efi | grep -qE '^/dev/(vd|sd)a1$' && ok "/boot/efi is the disk's own EFI partition (partition 1, shared)" || bad "/boot/efi is $(findmnt -no SOURCE /boot/efi)"
  lsblk -rno PARTTYPE | grep -qi '7c3457ef-0000-11aa-aa11-00306543ecac' && ok "the macOS partition is still there" || bad "the macOS partition is gone"
  sum=$(root dd if=/dev/vda2 bs=1M count=4 status=none | sha256sum | cut -d' ' -f1)
  [ "$sum" = "$P2SUM" ] && ok "the macOS partition's content is unchanged (sha256 of its first 4 MiB)" || bad "the macOS partition changed ($sum != $P2SUM)"
  [ "$(lsblk -rno PARTLABEL /dev/vda1)" = EFI ] && ok "the EFI partition's label is still Apple's" || bad "EFI partition label $(lsblk -rno PARTLABEL /dev/vda1)"
  ! lsblk -rno PARTTYPE | grep -qi '21686148-6449-6e6f-744e-656564454649' && ok "no BIOS boot partition (none made beside kept partitions)" || bad "a BIOS boot partition appeared"
  root grep -q 'target: free' /var/log/maluos-install/plan.yaml && ok "the plan ran with storage.target free" || bad "plan.yaml target"
else
  lsblk -rno PARTTYPE | grep -qi '21686148-6449-6e6f-744e-656564454649' && ok "the BIOS boot partition is there (a disk that moves boots on BIOS too)" || bad "no BIOS boot partition"
fi
if [ "$APPLE" = 1 ]; then   # the apple-t2 component on a machine that says it is a MacBookPro15,1
  grep -q 'MacBookPro15,1' /sys/class/dmi/id/product_name && ok "SMBIOS says Apple MacBookPro15,1" || bad "dmi $(cat /sys/class/dmi/id/product_name)"
  for p in maluos-apple-t2 maluos-apple-t2-support apple-bce-dkms applesmc-t2 bcm5974-t2 apple-t2-audio-config dkms linux-headers-generic mesa-vulkan-drivers; do
    installed $p && ok "$p installed from the medium" || bad "$p not installed"; done
  for p in tiny-dfr t2fanrd apple-firmware-script apfs-dkms vulkan-tools; do installed $p && ok "$p installed (recommended)" || echo "  warn $p not installed"; done
  ! installed t2-dsp && ok "t2-dsp not on the medium (in the repository for desktops with the network)" || echo "  warn t2-dsp installed from the medium"
  root modinfo -n apple-bce 2>/dev/null | grep -q "/lib/modules/$(uname -r)/updates/dkms/apple-bce.ko" && ok "apple-bce built by DKMS for $(uname -r)" || { bad "apple-bce module missing"; root dkms status; }
  root modinfo -n bcm5974 2>/dev/null | grep -q updates && ok "bcm5974 (T2) built by DKMS" || bad "bcm5974-t2 module missing"
  root modinfo -n applesmc 2>/dev/null | grep -q updates && ok "applesmc (T2) built by DKMS" || bad "applesmc-t2 module missing"
  root lsinitrd 2>/dev/null | grep -q 'apple-bce.ko' && ok "the initrd carries apple-bce (dracut add_drivers)" || bad "apple-bce not in the initrd"
  grep -q 'intel_iommu=on iommu=pt pm_async=off' /proc/cmdline && ok "the T2 kernel options are on the kernel command line" || bad "cmdline: $(cat /proc/cmdline)"
  command -v vulkaninfo >/dev/null && ok "vulkaninfo present (Vulkan for the Radeon)" || echo "  warn no vulkaninfo"
  root maluos-apple-firmware status | grep -q 'model: MacBookPro15,1' && ok "maluos-apple-firmware status names the model" || bad "maluos-apple-firmware status"
  systemctl cat tiny-dfr.service 2>/dev/null | grep -q 'ConditionFirmware=smbios-field' && ok "tiny-dfr gated to Apple hardware (drop-in)" || bad "tiny-dfr drop-in"
  systemctl is-enabled maluos-apple-firmware.service >/dev/null 2>&1 && ok "maluos-apple-firmware.service enabled" || bad "maluos-apple-firmware.service"
  root grep -q 'maluos-apple-t2' /var/log/maluos-install/plan.yaml && ok "the plan as run lists the apple-t2 component (added by the installer)" || bad "plan.yaml components"
  root python3 -c 'import json,sys; j=json.load(open("/var/log/maluos-install/journal.json")); sys.exit(0 if j["steps"]["configure"]["subs"]["apple"]["state"]=="ok" else 1)' && ok "journal: the apple sub-step ran" || bad "journal apple sub-step"
  ls /lib/firmware/brcm/ | grep -q 'apple' && ok "Apple Wi-Fi firmware present" || echo "  info no Apple firmware (expected: no macOS EFI partition in this VM)"
fi
# fstab, swap
grep -qE '^UUID=\S+\s+/\s' /etc/fstab && ! grep -qE '^/dev/' /etc/fstab && ok "fstab by UUID" || bad "fstab: $(grep -v '^#' /etc/fstab | head -4 | tr '\n' ';')"
grep -q '^/swap.img' /etc/fstab && swapon --show --noheadings | grep -q '/swap.img' && ok "swap file /swap.img in fstab and active ($(swapon --show=SIZE --noheadings | head -1))" || bad "swap file"
# the kernel command line from the plan
if [ "$SCREENS" = 1 ]; then  # the screens ask no bootloader question: the defaults, no serial console
  ! grep -q 'console=ttyS0' /proc/cmdline && ok "the kernel command line has the defaults (no bootloader screen)" || bad "cmdline: $(cat /proc/cmdline)"
else
  grep -q 'console=ttyS0,115200' /proc/cmdline && ok "the plan's cmdline is on the kernel command line" || bad "cmdline: $(cat /proc/cmdline)"
fi
# the evidence
for f in install.log plan.yaml journal.json; do root test -s /var/log/maluos-install/$f && ok "/var/log/maluos-install/$f" || bad "$f missing"; done
! root grep -q '\$6\$' /var/log/maluos-install/plan.yaml && root grep -q '<redacted>' /var/log/maluos-install/plan.yaml && ok "plan.yaml carries no hash (redacted)" || bad "plan.yaml not redacted"
! root grep -q 'maluos-test-passphrase' /var/log/maluos-install/plan.yaml /var/log/maluos-install/install.log && ok "no passphrase in the evidence" || bad "passphrase leaked into the evidence"
# the journal is copied by finish's evidence sub-step, so finish and that sub-step are still "start" in the copy
root python3 -c 'import json,sys; j=json.load(open("/var/log/maluos-install/journal.json")); s=j["steps"]; sys.exit(0 if len(s)==5 and all(v["state"]=="ok" for k,v in s.items() if k!="finish") and s["finish"]["subs"]["evidence"]["state"] in ("start","ok") else 1)' && ok "journal: the five steps, every one before finish ok" || bad "journal: $(root python3 -c 'import json; print({k:v["state"] for k,v in json.load(open("/var/log/maluos-install/journal.json"))["steps"].items()})')"
# UEFI: the entry
if [ "$UEFI" = 1 ]; then
  first=$(root efibootmgr | awk '/^BootOrder:/{split($2,a,","); print a[1]}')
  root efibootmgr | grep -q "^Boot$first\*\? *MaluOS" && ok "efibootmgr: MaluOS is first in the boot order" || { bad "efibootmgr first entry"; root efibootmgr | head -6; }
  root test -f /boot/efi/EFI/ubuntu/shimx64.efi && root test -f /boot/efi/EFI/BOOT/BOOTX64.EFI && ok "shim on the ESP (EFI/ubuntu and the EFI/BOOT fallback)" || bad "ESP contents"
fi
# the user and SSH
id -nG maluos | grep -qw sudo && ok "maluos is in sudo" || bad "sudo group"
root sshd -T 2>/dev/null | grep -q "^passwordauthentication $([ "$PROFILE" = server ] && echo yes || echo no)" && ok "sshd PasswordAuthentication as the plan says" || bad "sshd password auth"
[ "$(hostname)" = maluos ] && ok "hostname maluos" || bad "hostname $(hostname)"
grep -q '127.0.1.1 maluos' /etc/hosts && ok "/etc/hosts" || bad "/etc/hosts"
! id ubuntu >/dev/null 2>&1 && ok "no default ubuntu user (cloud-init created none)" || bad "an ubuntu user exists"
[ -s /etc/machine-id ] && ok "machine-id generated on first boot" || bad "machine-id"
# firstboot.yaml, cloud-init
root grep -q 'name: maluos' /etc/maluos/firstboot.yaml && root grep -q 'ref: human:admin' /etc/maluos/firstboot.yaml && ok "firstboot.yaml has the plan's tenant and principal" || bad "firstboot.yaml"
if [ "$PROFILE" = server ]; then
  [ ! -f /etc/cloud/cloud-init.disabled ] && cloud-init status 2>/dev/null | grep -qE 'status: (done|running)' && ok "cloud-init kept and ran (NoCloud seed)" || bad "cloud-init: $(cloud-init status 2>&1 | head -1)"
else
  [ -f /etc/cloud/cloud-init.disabled ] && ok "cloud-init disabled on the desktop" || bad "cloud-init not disabled"
fi
# network, apt
root test -f /etc/netplan/50-maluos.yaml && ok "netplan 50-maluos.yaml" || bad "netplan file"
ip -4 addr | grep -q '10\.0\.2\.' && ok "DHCP address" || bad "no address"
grep -q OS_PROBER=true /etc/default/grub.d/50-maluos-install.cfg && ok "grub defaults from the plan" || bad "grub defaults"
if [ "$SCREENS" = 1 ]; then  # the plan the screens built, as the engine left it (redacted)
  P=/var/log/maluos-install/plan.yaml
  root grep -q 'layout: lvm' $P && root grep -q 'name: maluos' $P && root grep -q 'send: false' $P && root grep -q 'fullname: MaluOS Test' $P && root grep -q 'password_auth: true' $P \
    && ok "the screens' plan has the answers typed (lvm, maluos, telemetry off, the name, password auth)" || { bad "the screens' plan"; root cat $P | head -40; }
  root grep -q 'password_change_required: false' $P && ok "the screens' plan: no forced password change (the driver's --no-change)" || bad "password_change_required"
fi
caps=$(root getcap -r /usr 2>/dev/null | wc -l); [ "$caps" -gt 0 ] && ok "file capabilities survived the unpack ($caps files)" || echo "  warn no file capabilities found under /usr (the image may carry none)"
test -f /etc/apt/sources.list.d/maluos-iso.sources && test -d /var/lib/maluos/apt/dists && ok "the on-media repository and maluos-iso.sources" || bad "maluos-iso.sources"
root apt-get update -q >/dev/null 2>&1 && ok "apt-get update clean (media and network sources)" || echo "  warn apt-get update had errors"
grep -q 'LANG=en_US.UTF-8' /etc/default/locale && grep -q 'XKBLAYOUT="us"' /etc/default/keyboard && [ "$(cat /etc/timezone)" = UTC ] && ok "locale, keyboard, timezone" || bad "locale"
echo "checks failed: $fail"; exit $fail
REMOTE
rc=${PIPESTATUS[0]}
ssh "${ssh_opts[@]}" maluos@127.0.0.1 'root poweroff' 2>/dev/null || true
sleep 5
if [ "$rc" = 0 ]; then echo "PASS: the $PROFILE live medium installs ($LAYOUT, $FS$([ $ENCRYPT = 1 ] && echo ', encrypted' || true)$([ $SSH = 1 ] && echo ', over SSH' || true)$([ $FREE = 1 ] && echo ', into the free space beside macOS' || true)$([ $APPLE = 1 ] && echo ', as an Apple MacBookPro15,1 with the apple-t2 component' || true)) and boots on $FW"
else echo "FAIL (see $WORK/verify-$TAG.log, boot-$TAG.log)"; exit 1; fi
