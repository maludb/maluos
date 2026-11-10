# Stage 3: the GPU server

**Your place in the roadmap:** [Choose a compute path](11-compute-roadmap.md). Follow this guide for a MaluOS GPU host, then [estate enrolment](13-estate.md) to make it available to other machines. Section 6 is optional manual pairing; the final VM section is an alternative host path. For hybrid use, finish estate checks before cloud setup and hybrid routing.

The bare-metal MaluOS server with the NVIDIA card is the estate's
inference node: Ollama behind the gateway, the GPU shared with every
member that is allowed to use it. It was installed on 2026-11-04 from the
server ISO as the GPU development host, so this stage reconciles what is
there rather than reinstalling. A reinstall, when wanted, is
[plans/gpu-node.yaml](plans/gpu-node.yaml).

This is the private-compute path. Use [cloud model APIs](11-cloud-models.md)
when adding capacity without a GPU, or [hybrid compute](11-hybrid-compute.md)
to combine this server with one or more approved cloud hosts.
For an Apple Silicon Mac or DGX Spark retaining its vendor operating
system, use [ARM inference hosts](11-arm-inference.md), then the
[Mac](11-gpu-macos.md) or [Spark](11-gpu-dgx-spark.md) installation guide.
Those guides separate working runtime preparation from the standalone
node-service integration that is still under development.

Machine: **gpu-1**. Exit criterion: a chat through the gateway is served
by the GPU, sharing is on.

For a new host use [26.04.20261109](02-current-release.md) and keep the
Business OS installer box unchecked. The existing gpu-1 history below
includes cleanup for older images; §3 is unnecessary when no office was
provisioned. The inference and estate protocols are unchanged in the
office-setup-only release.

## 1. Where it stands

```bash
cat /etc/os-release | grep -E 'PRETTY|VARIANT'      # MaluOS 26.04.…, Server
maluctl status                                      # the components and their state
dpkg -l maluos-server maluos-nvidia maluos-gateway maluos-estate maluos-memory maludb-os-core 2>/dev/null | awk '/^ii/{print $2, $3}'
nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv,noheader
# the card, the driver (595 or 580 branch), its VRAM
maluctl gpu status
# the same facts as MaluOS reads them: vendor, model, VRAM, driver, chassis, the sharing rule
hostnamectl chassis                                  # desktop or server: decides the sharing rule below
```

If `maluos-nvidia` is not installed (the box was set up before installer
0.3.4 added it, and the driver came from `apt` by hand), the driver is
still the right one; install the metapackage so updates track it. Dry-run
first: the seed names the 595 branch before 580, and a box on a
hand-installed 580 must see only the signed 580 modules added, no second
driver and nothing removed:

```bash
sudo apt update && apt-get install -s maluos-nvidia 2>&1 | grep -E '^(Inst|Remv|E:)'
# Inst linux-modules-nvidia-580-… , maluos-nvidia, nvtop; no Remv, no nvidia-driver-595
sudo apt install -y maluos-nvidia && sudo reboot
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader     # after the reboot: the card, the same driver branch
```

## 2. Bring it to the current release

```bash
sudo apt update && sudo apt full-upgrade -y
# apt.maluos.com: gateway 0.6.1, estate 0.6.0, memory 0.2.1, firstboot 0.1.12 or later, kernel 2026.11.01maluos1
sudo maluctl provision --force          # re-runs every component idempotently after an upgrade
maluctl status
```

## 3. The kernel this box does not need

Older images provisioned `maluos.local` by default, so the original gpu-1
has an unwanted office. Current images carry the package with provisioning
off. Apply this cleanup only to an older GPU host with a provisioned kernel;
the estate uses the office as its organization coordinator. The databases
stay and nothing is deleted:

```bash
sudo sed -i '/^  maludb-os-core:/,/^  [a-z]/{s/^    enabled: true/    enabled: false/}' /etc/maluos/firstboot.yaml
grep -A1 'maludb-os-core:' /etc/maluos/firstboot.yaml      # enabled: false
sudo systemctl disable --now maludb-os-web maludb-os-records-mcp maludb-os-activity-mcp maludb-os-actions-mcp \
    maludb-os-memory-mcp maludb-os-agent-runner maludb-os-activity-ingest.timer apache2
systemctl is-active maludb-os-web apache2            # inactive, inactive
```

Keep `maludb-api` running: the memory face and the estate use it.

## 4. Ollama and a model

The gateway installs its own pinned Ollama (no snap, no curl-pipe-sh) and
keeps it behind the gateway's socket. Pick a model the card holds:
`qwen3:8b` fits 12 GB; a 24 GB card takes `qwen3:32b` quantized.

```bash
sudo maluctl gateway ollama install
sudo maluctl gateway ollama pull qwen3:8b
sudo maluctl gateway ollama pull nomic-embed-text
maluctl gateway status                              # ollama-local backend up, the models listed
maluctl gateway chat "Say hello in five words" --model qwen3:8b
# an answer; nvidia-smi shows the model loaded while it runs
sudo maluctl gateway usage --since 10m              # the call in the ledger
```

## 5. Sharing

The rule is by chassis: a **server** shares always with no opt-in; a
**desktop** (this box, if DMI says so) is opt-in and then shares always; a
laptop is opt-in and idle-only. Check and set:

```bash
maluctl gateway share status                        # the chassis, the rule, on or off
sudo maluctl gateway share on --when always
maluctl gateway share status                        # on, contribution always
```

If the chassis is wrong for the machine (a tower read as `desktop` that
you mean as a server), override it in `/etc/maluos/gateway.yaml` under
`share:` rather than fighting DMI.

## 6. Pairing by hand, before the estate exists

Optional, and useful to prove the GPU over the LAN before stage 4. The
gateway exposes the node API on the LAN with a key; a desk adds it as a
backend. Once the estate is up this pairing is replaced by the directory.

```bash
# on gpu-1
sudo maluctl gateway expose --bind 0.0.0.0                       # tcp on 11435, keys required
sudo maluctl gateway key issue --name desk-test --class interactive --cloud-allowed=false   # the key, shown once
# on a MaluOS desk
sudo maluctl gateway backend add gpu-1 http://<gpu-1 address>:11435 --key <the key>
maluctl gateway chat "Say hello" --model qwen3:8b --prefer gpu-1
```

Withdraw it before stage 4 with `sudo maluctl gateway unexpose` on gpu-1
and `sudo maluctl gateway backend rm gpu-1` on the desk, or leave it: the
estate adds its own backend beside it, and stage 4's `expose --bind
overlay` moves the listener onto the tunnel anyway.

## Done when

- `maluctl gpu status` shows the card with live numbers.
- `maluctl gateway chat … --model qwen3:8b` answers and appears in the ledger.
- `maluctl gateway share status` says on.
- `maluctl status` no longer lists the kernel as enabled.

Next: [13-estate.md](13-estate.md).

## A second GPU node: a VM on Proxmox with the card passed through, no static address

A spoke needs no fixed address: it dials the hub and keeps the tunnel
alive, the kernel learns its address from every heartbeat, and its
overlay address (`100.100.0.N`, `gpu-2.internal`) is the one the estate
uses. DHCP is fine. What a VM needs is the card itself.

### The Proxmox host

GPU passthrough, once per host: IOMMU on in the firmware and on the
kernel command line (`intel_iommu=on iommu=pt` or `amd_iommu=on
iommu=pt` in `/etc/default/grub`, then `update-grub` and a reboot), the
card bound to `vfio-pci` instead of the host's `nouveau`/`nvidia`
(`/etc/modprobe.d/vfio.conf` with the card's vendor:device ids,
`blacklist nouveau`, `update-initramfs -u`), and the VM given the whole
device:

```bash
lspci -nn | grep -i nvidia                                  # the card's address and ids, e.g. 0000:01:00.0 [10de:2504]
qm set <id> --machine q35 --bios ovmf --hostpci0 0000:01:00,pcie=1    # the whole function group; x-vga=0 for a headless node
```

A card passed to a VM is unavailable to the host and to every other VM.
The VM's chassis reads `vm`, which the sharing rule treats as a server:
it shares always, no opt-in.

### If the VM has no MaluOS yet

Install from the server ISO with [plans/gpu-node.yaml](plans/gpu-node.yaml):
the kernel component off, `maluos-nvidia` added by the installer when it
sees the card (from the network: the driver is not on the medium), Ollama
installed and a model pulled by the gateway component at first boot. Mint
an `inference` node code at the office first and the plan's `enroll`
block joins the estate at first boot as a spoke; or leave it out and join
by hand as below. The VM needs nothing forwarded.

### If the VM already runs MaluOS

Bring it to gpu-1's state, in this order, each with its check:

```bash
sudo apt update && sudo apt full-upgrade -y                      # the 26.04.20261106 packages: estate 0.7.0, firstboot 0.1.16
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader   # the card is visible in the VM
apt-get install -s maluos-nvidia 2>&1 | grep -E '^(Inst|Remv|E:)'  # only the signed modules of the installed branch, no Remv
sudo apt install -y maluos-nvidia
sudo sed -i '/^  maludb-os-core:/,/^  [a-z]/{s/^    enabled: true/    enabled: false/}' /etc/maluos/firstboot.yaml
sudo systemctl disable --now maludb-os-web maludb-os-records-mcp maludb-os-activity-mcp maludb-os-actions-mcp \
    maludb-os-memory-mcp maludb-os-agent-runner maludb-os-activity-ingest.timer apache2 2>/dev/null; true
sudo maluctl gateway ollama install && sudo maluctl gateway ollama pull qwen3:8b
maluctl gateway chat "Say hello in five words" --model qwen3:8b     # served by the card
maluctl gateway share status                                       # on by the chassis rule (vm = a server)
sudo maluctl estate join https://app.$DOMAIN --code <inference code> --name gpu-2 --kind inference
maluctl estate overlay status; ping -c 2 office.internal           # a spoke; the tunnel answers
sudo maluctl gateway expose --bind overlay; maluctl estate inference
```

Expect at the office: Settings → Estate → Shared inference lists both
`gpu-1` and `gpu-2` with their models; `maluctl estate inference
--refresh` on the office shows two backends, and the gateway places by
expected wait between them.


