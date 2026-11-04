# Moving development to a GPU host (2026-11-04)

Development moves, for a while, from the Proxmox VM (`maludb-dev-26`,
192.168.100.198: 12 vCPUs, an 8 GB balloon floor under a 16 GB cap, no
`/dev/kvm`) to a machine with an NVIDIA card, so that the server and the
desktop implementations can be built and tested where `nvidia-smi` answers:
real GPU facts in `maluctl gpu status`, the GPUs tab, the gateway's sharing,
the node API and the estate's inference backends (roadmap rows G1, G2, G4,
G5b on real hardware, and the `gpu` machine of D7). This note is the
runbook: what state the VM leaves behind, what is not in git and must be
carried, how the new host is set up, and what the GPU makes possible.

## 1. The repositories, as the VM leaves them

Everything that matters is pushed. Checked 2026-11-04 after the G5b commit.

| Repository | Remote | State on the VM |
|---|---|---|
| `~/maluos` | github.com/maludb/maluos | main == origin/main at 1a4cd28 (G5b, on top of the Slides and fonts vendoring); clean |
| `~/maludb-os-core` (the kernel) | github.com/maludb/maludb-os-core | main == origin/main at ab00263 (db/193); clean; `config/.env` is not in git (§2) |
| `~/maludb-os-docker` | github.com/maludb/maludb-os-docker | main == origin/main; clean |
| `~/malu123` | github.com/maludb/malu123 | main == origin/main; clean |
| `~/maluos-slides` | github.com/maludb/maluos-slides | this clone is 805 commits behind origin (development already moved); the local branch `upstream-renamed` (the frozen vendor branch) has no upstream |
| `~/maluos-photoedit` | github.com/maludb/maluos-photoedit | main == origin/main; only an untracked `docs/claude-log/` |
| `~/maludb-core-26` | github.com/maludb/maludb-core-26 | main == origin/main; four local branches without an upstream, the owner's: `mc2dbd-principal-binding`, `principal-scope-claims`, `worktree-agent-a7b0b6c3b7fd86c6d`, `worktree-agent-a98e40d16ae256f86` |

The vendored binaries (the MaluDB engine debs, MaluOS Slides, Malu123,
maluos-fonts, apple-bce) are in git under `vendor/`, so a fresh clone
builds the repository and the images without the VM. The branches without
an upstream are the only unpushed work; push them (`git push -u origin
BRANCH`) or keep the VM until they are not wanted.

## 2. What is not in git

| What | Where on the VM | Move it? |
|---|---|---|
| The development signing key (`MaluOS Archive Automatic Signing Key <apt@maludb.org>`, no passphrase) | the GnuPG keyring | **Yes.** The keyring package and every image trust its public half; a new key would mean a keyring release. `gpg --export-secret-keys --armor "$MALUOS_SIGNING_UID"` and `gpg --import` on the new host. |
| The production key's signing subkey (`MaluOS Archive Signing Key (2026) <apt@maluos.com>`, passphrase) | the GnuPG keyring | Only if the new host publishes to apt.maluos.com or cuts releases. `gpg --export-secret-subkeys --armor "$MALUOS_PUBLIC_SIGNING_UID"` (asks for the passphrase, which is in the password manager, never in a file); import on the new host, then delete the secret subkey on the VM: docs/release.md, custody rule 1 says one publishing host. |
| `~/.config/maluos/publish.env` | AWS profile name, the R2 endpoint, the apt and download bucket URLs | Yes, with `~/.aws/config` and `~/.aws/credentials` (the R2 token). `scripts/release.sh` and `repo/publish-remote.sh` read them. |
| GitHub access | `~/.config/gh` (account maludb-ed), `~/.ssh/id_ed25519_github` and `~/.ssh/config` | Yes, or `gh auth login` and a new SSH key on the new host. The remotes use SSH. |
| The kernel's `config/.env` | `~/maludb-os-core/config/.env` | Yes. The scratch database for `bin/test_*.php`, the application keys, the legacy host's address. Never commit it. |
| `~/.aptly` (1.3 GB) and `~/.aptly.conf` | the local repository | No. `repo/init.sh` recreates both (it writes `~/.aptly.conf` and creates the aptly repo; it skips the key when the imported one is present), `repo/publish.sh` fills it from `build/` and `vendor/`. |
| `~/iso-cache/ubuntu-26.04.1-live-server-amd64.iso` (2.8 GB) | the base medium for `iso/build-iso.sh` (`BASE_ISO`) | Copy or download again; the checksum is beside it. |
| `build/` (173 GB) | debs, rootfs, qcow2, ISOs, logs, the chain scripts | No. Everything is rebuilt by the scripts. The chain scripts (`build/logs/chain-*.sh`) are gitignored; the pattern is in §5. |
| `/var/www/html/maluos` | the LAN share of images (Apache) | Optional; any directory served on the LAN does. |
| `~/.claude/projects/-home-maludb/memory` (42 MB) | Claude Code's memory of this project | Yes, to the same path on the new host. The directory name encodes the working directory (`/home/maludb` → `-home-maludb`); keep the same home and start Claude Code from it, or rename the directory to match. |
| `~/craft-fonts`, `~/craft-fonts-photoedit`, `~/malu123-vendor` | fonts and vendor inputs of the app forks | Only when those forks are built on the new host (their own notes say how). |
| Git identity | `git config --global user.name / user.email` | Set it again. |

A bundle of the files that are small and secret (the development key, the
publishing environment, the AWS and GitHub configuration, the GitHub SSH
key, the kernel's `.env`, Claude's memory, the git identity) is made on
the VM by the commands in §3 step 1; the production subkey is never in it.

## 3. Setting up the new host

1. **On the VM**, make the bundle and copy it over (replace NEWHOST):

   ```
   mkdir -p -m 700 ~/handoff && cd ~/handoff
   gpg --export-secret-keys --armor "MaluOS Archive Automatic Signing Key <apt@maludb.org>" > dev-signing-key.asc
   tar czf maluos-dev-handoff.tgz -C ~ .config/maluos/publish.env .aws .config/gh .ssh/id_ed25519_github .ssh/id_ed25519_github.pub .ssh/config .gitconfig maludb-os-core/config/.env .claude/projects/-home-maludb/memory -C ~/handoff dev-signing-key.asc
   chmod 600 maluos-dev-handoff.tgz; shred -u dev-signing-key.asc
   scp maluos-dev-handoff.tgz NEWHOST:
   ```

   The production subkey, when wanted, goes separately:
   `gpg --export-secret-subkeys --armor "MaluOS Archive Signing Key (2026) <apt@maluos.com>" > prod-subkey.asc`
   (passphrase prompt), copied the same way and shredded afterwards.

2. **The host OS**: Ubuntu 26.04.1 (resolute), the same release as MaluOS.
   `scripts/build-packages.sh` runs `dpkg-buildpackage` on the host, so the
   toolchain must be resolute's; a different Ubuntu can still build inside
   an `ubuntu:26.04` container with `ci/in-container-build.sh`, as CI does.
   The user needs `sudo` (image builds run as root) and membership of the
   `kvm` group. Keep the same user name and home (`/home/maludb`) unless
   you want to rename Claude's memory directory.

3. **Packages**. The authoritative list is the `apt-get install` line of
   `ci/in-container-build.sh` (build-essential, devscripts, debhelper,
   dh-python, lintian, mmdebstrap, squashfs-tools, xorriso, qemu-utils,
   the GTK/libadwaita/libgtop development packages for the System Monitor
   fork, php-cli and composer for the kernel package, nodejs/npm, meson)
   plus, for the tests and the maintainer tools:

   ```
   sudo apt install aptly gnupg qemu-system-x86 ovmf cloud-image-utils openssh-client \
        xvfb dbus-daemon gh awscli tmux apache2
   ```

   `tests/system-monitor-local-test.sh` needs `xvfb-run` and
   `dbus-run-session`; the boot tests need `qemu-system-x86_64`, OVMF and
   `cloud-localds`.

4. **The GPU on the host**: the NVIDIA driver with `nvidia-smi`
   (`nvidia-driver-595` or `-580` with `nvidia-utils-*`, the branches
   seeds/nvidia.seed names). `nvidia-smi --query-gpu=name,driver_version,memory.used,memory.total,temperature.gpu,power.draw,compute_cap --format=csv,noheader` is the
   query `maluos_gpu.py` runs; if it answers, the reader will.

5. **Unpack and import**:

   ```
   tar xzf maluos-dev-handoff.tgz -C ~
   gpg --import ~/dev-signing-key.asc && shred -u ~/dev-signing-key.asc
   gpg --list-secret-keys        # both uids appear when the production subkey was imported too
   chmod 600 ~/.ssh/id_ed25519_github ~/.aws/credentials; gh auth status
   ```

6. **Clone**:

   ```
   cd ~ && for r in maluos maludb-os-core maludb-os-docker; do git clone git@github.com:maludb/$r.git; done
   ```

   (`malu123`, `maluos-slides`, `maluos-photoedit`, `maludb-core-26` as needed.)

7. **The local repository and the first build** (every long step as a
   detached unit, logs in `build/logs/NAME.log`, `scripts/jobs.sh` to watch):

   ```
   cd ~/maluos
   repo/init.sh                                   # finds the imported key, writes ~/.aptly.conf, creates the aptly repo
   scripts/run-detached.sh repo-serve repo/serve.sh
   scripts/run-detached.sh packages scripts/build-packages.sh      # ~20 min; lintian runs; the kernel package is the slow one
   repo/publish.sh                                # the dev tree ~/.aptly/public, signed with the dev key
   mkdir -p ~/iso-cache && cp /path/to/ubuntu-26.04.1-live-server-amd64.iso ~/iso-cache/   # or download it
   scripts/run-detached.sh rootfs-server  sudo image/build-rootfs.sh
   scripts/run-detached.sh qcow2-server   sudo image/build-qcow2.sh
   scripts/run-detached.sh test-server    tests/qcow2-boot-test.sh build/image/maluos-server-26.04-amd64.qcow2 --uefi
   ```

   Then the same three with `-p desktop` and the desktop qcow2. With KVM
   a boot test takes minutes instead of the VM's 25 and more; the scripts'
   timeouts were sized for TCG and need no change. The local harnesses
   that need no VM: `tests/vault-local-test.sh`,
   `tests/gateway-local-test.sh`, `tests/desk-local-test.sh`,
   `tests/memory-local-test.sh`, `tests/system-monitor-local-test.sh`,
   `python3 tests/gpu-test.py`.

8. **Things the VM needed that the new host may not**: the drop-caches
   loop and `scripts/gentle.py` exist because the hypervisor killed the VM
   when the page cache filled; on a host with its own RAM they are
   harmless and optional. `scripts/release.sh` still wants
   `source ~/.config/maluos/publish.env` first and the production
   subkey in the keyring.

9. **Releases from the new host**: nothing changes. The freshness guard
   requires the ISOs and qcow2s to come from the tree being released, so
   build both profiles there before `scripts/release.sh`.

## 4. What the GPU host makes possible

The boot tests run MaluOS inside QEMU, which has no GPU: every GPU check in
`tests/qcow2-boot-test.sh` asserts the no-GPU answer (`gpus == []`,
chassis `vm`) and keeps doing so on the new host. The real-hardware work
is on the host itself or on bare metal, in one of three ways:

1. **MaluOS on the GPU box** (the real D7 `gpu` machine): install
   maluos-server from the released ISO, then `sudo apt install
   maluos-nvidia` (the component is off the medium) and the proof's steps in
   docs/phase13-three-machine-proof.md. The strongest evidence, but the box
   is then not the build host.
2. **The MaluOS packages on the host's Ubuntu**: the host already runs
   resolute, so `maluos-firstboot`, `maluos-gateway`, `maluos-estate`,
   `maluos-desk` and the System Monitor fork install from the local
   repository (`sudo apt install` after adding `~/.aptly/public` as a
   `file:` or `http://127.0.0.1:8080` source with the dev keyring). The
   host becomes both the build machine and a real GPU node: `maluctl gpu
   status`, `maluctl gateway share on`, `maluctl gateway expose`, a real
   Ollama on the card, and a desktop VM enrolled against the mock office or
   a server VM's kernel sees the GPU through the estate's inference
   backends. This is the quickest path to real numbers.
3. **VFIO passthrough** of the card into the test VM: possible, not
   supported by the test scripts today (they would need the device
   arguments and a driver inside the image).

What to look at first, in roadmap order:

- **G1 on real hardware**: `maluctl gpu status --json` on the host:
  model, driver, VRAM used of total, temperature, power, compute
  capability; the chassis from `hostnamectl chassis` on bare metal
  (desktop → opt-in, server → always, laptop → idle only) and the
  sharing rule it implies; the GPUs tab's rendering of a real card
  (`gnome-system-monitor --show-gpus-tab` on the host's desktop, if it has
  one; else the desktop VM reading the host's facts through the office
  is G5b's path).
- **G2 and G4**: the node API on a gateway with a real backend: `maluctl
  gateway share on`, `expose`, `key issue`, a desk's `backend add URL
  --key`, queue positions and expected waits from real completions.
- **G5b**: the estate's shared GPUs in the Network and Queue tabs of a
  desktop VM with a real backend behind the office (mock or kernel).
- **D7**: the `gpu` machine of the three-machine proof is the host; the
  runbook's step 2 onwards.
- **The images**: the server image as the node, the desktop image as the
  desk; both profiles' chains in §5 run on the new host as before.

Findings go into the Status sections of docs/phase13-shared-gpus.md and
the G rows of docs/roadmap.md, as every slice's did.

## 5. The build and test chain, the pattern

The chains the VM ran were short scripts under `build/logs/` (gitignored)
started as transient units; the last one, for G5b, reads:

```
#!/bin/bash
set -euo pipefail
ROOT=/home/maludb/maluos; FROM=${1:-packages}; GO=0
drop() { sync; sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches'; }
step() { [ "$1" = "$FROM" ] && GO=1; echo; echo "#### $(date +%H:%M:%S) $1$([ $GO = 1 ] || echo " (skipped)")"; [ $GO = 1 ] && drop; [ $GO = 1 ]; }
cd "$ROOT"
GENTLE=(env MALUOS_RSYNC_BWLIMIT=60m MALUOS_IMAGE_RATE=80M ionice -c2 -n7 nice -n5)
! step packages || SKIP_BUILT=1 ionice -c2 -n7 nice -n5 scripts/build-packages.sh
! step publish  || repo/publish.sh
P=desktop
! step d-rootfs || sudo "${GENTLE[@]}" image/build-rootfs.sh -p "$P"
! step d-qcow2  || sudo "${GENTLE[@]}" image/build-qcow2.sh -p "$P"
sudo rm -r "build/image/maluos-$P.rootfs"
while systemctl list-units --no-legend "maluos-test-*" | grep -q .; do sleep 30; done
! step d-test   || tests/qcow2-boot-test.sh "build/image/maluos-$P-26.04-amd64.qcow2" --uefi
GO=1; step done
```

Run with `scripts/run-detached.sh chain-NAME build/logs/chain-NAME.sh`;
`scripts/jobs.sh chain-NAME` shows the status and the log's tail. Two
rules that cost time when broken: never edit a script a running unit is
executing (bash reads it incrementally), and an ISO build
(`iso/build-iso.sh -p PROFILE`, then `tests/iso-apt-check.sh`) comes
after the qcow2 when a release is planned. `SKIP_BUILT=1` leaves packages
whose deb is already in `build/` alone.

## 6. Leaving the VM

Keep the VM until the first full chain (packages, publish, both images,
both boot tests) passes on the new host. Then: the production subkey is on
one host only (delete it from the other), the four unpushed branches are
pushed or consciously dropped, and the VM can be stopped. The LAN share
and the local repository on the VM serve nothing once the new host
publishes.
