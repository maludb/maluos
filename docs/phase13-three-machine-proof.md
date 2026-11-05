# Phase 13: the three-machine proof (D7), the runbook

The estate's slices were each boot-tested on one VM standing in for every
member (the mock office, one host that is both the desk and a node). This
runbook runs the proof of docs/phase13-estate.md ("The proof: three
machines") on real hosts, as far as the slices built so far reach: slices
1, 1b, 2 and 3. It is the owner's to run; nothing in it needs this
repository, only the released images and apt.maluos.com. Written
2026-10-29 with slice 3; amended 2026-11-05 for an office behind a reverse
proxy (docs/phase13-estate-behind-a-proxy.md: the hub wherever the UDP
port is, `proxy_address` for the office's names); the result goes into
the Status of each slice's document.

## The three machines

| Machine | What it is | Image | Needs |
|---|---|---|---|
| **office** | the coordinator: the Business OS kernel; the estate's hub when it has the UDP port, a spoke otherwise | maluos-server (the `maludb-os-core` component on) | reachable over HTTPS by the two others (through a reverse proxy is the common case: `https://app.<domain>`; or `http://office:8080` on one LAN); under https, `proxy_address` in its plan so the office reaches its own names; the hub's UDP port only if the office is the hub (step 0) |
| **gpu** | the inference node: a GPU, Ollama, the gateway sharing it; the estate's hub when it is the member with a reachable UDP port | maluos-server | as a spoke, any network the hub is reachable from: NAT, DHCP, a dynamic address are all fine (the spoke dials out and keeps the tunnel alive); as the hub, one UDP port (51820) the office and the desk reach |
| **desk** | a person's desktop | maluos-desktop | the same: anywhere the hub is reachable from |

Every member reaches the others only over the overlay (`NAME.internal`,
100.100.0.0/16): no LAN names, no TLS of its own, and one UDP port in the
whole estate, at the hub.

### Step 0a: where the hub is

Decide this before any join (docs/phase13-estate-behind-a-proxy.md,
decision 3; the handbook's
[22-estate-behind-a-proxy.md](https://github.com/maludb/maluos-docs/blob/main/22-estate-behind-a-proxy.md)
and [30-reverse-proxy.md](https://github.com/maludb/maluos-docs/blob/main/30-reverse-proxy.md)):

- **The office has the port** (a server on a public address, or the
  router in front of its proxy forwards UDP 51820 to the office VM, or the
  proxy host's nginx has the `stream` block of the design note): the
  office is the hub. Its endpoint is a public name that resolves to the
  forwarder, `vpn.<domain>:51820`.
- **The office has no port** (a VM behind a proxy that forwards HTTPS
  only, nothing else to be had): the member that has one is the hub, the
  GPU server in this proof, and the office joins as a spoke.

The role moves without a leave: `sudo maluctl estate overlay hub off` on
the member that holds it, `sudo maluctl estate overlay hub HOST:PORT` on
the one that should. An office that joined as the hub on an address
nobody reaches recovers that way.

## Step 0: the office

1. Install maluos-server on **office** from the ISO with an install plan
   that gives the kernel its domain, scheme and admin under
   `firstboot.components.maludb-os-core` (the installer's screens do not
   ask them, and the medium's unattended plan installs a kernel for
   `maluos.local`): the handbook's
   [office runbook](https://github.com/maludb/maluos-docs/blob/main/10-office-on-proxmox.md)
   and its `plans/office.yaml`. The kernel's own `docs/install.md` is the
   hand install on plain Ubuntu 24.04 and does not apply on MaluOS.
2. Apply the kernel's migrations up to db/191 (an image from
   26.04.20261029 or later carries them; `sudo -u postgres psql -d
   maludb_os -f /var/www/db/191_estate_inference.sql` by hand on an older
   one).
3. Sign in as the super-admin. Settings → Desks is the estate's page.

## Step 1: the hub (slice 1 + 1b)

On the office page, mint a **node code** of kind `server`. On **office**,
as the hub (step 0a, the office has the port):

```
sudo maluctl estate join https://app.example.com --code CODE --name office --hub vpn.example.com:51820
maluctl estate status            # joined, the heartbeat ok
maluctl estate overlay status    # interface estate up, 100.100.0.1/16 as office.internal, hub listening on udp 51820
maluctl estate inference         # the facts the office's own gateway reports (none shared unless it has a GPU), the key stored
```

or as a spoke (the GPU host will be the hub):

```
sudo maluctl estate join https://app.example.com --code CODE --name office
maluctl estate overlay status    # a key was sent; no hub has joined the estate yet (the service waits)
```

Expect: Settings → Desks lists the node online with its report; the
overlay paragraph names the hub and its endpoint (or "the hub has not
joined yet"); the join printed `inference: key host:office/estate-inference-key`.
Under https the join only works when the office reaches `app.example.com`
through its proxy: `proxy_address` in the plan did that at first boot
(`getent hosts app.example.com` shows the proxy's address, not loopback).

## Step 2: the GPU node (slices 1, 1b, 3)

Mint a node code of kind `inference`. On **gpu**:

```
sudo maluctl gateway ollama install && sudo maluctl gateway ollama pull qwen3:8b      # or whatever the GPU holds
sudo maluctl estate join https://app.example.com --code CODE --name gpu-1 --kind inference                    # the office is the hub
sudo maluctl estate join https://app.example.com --code CODE --name gpu-1 --kind inference --hub gpu.example.com:51820   # or: this host is the hub
maluctl estate overlay status                   # a spoke: 100.100.0.2/16 as gpu-1.internal, the hub's last handshake recent;
                                                # or the hub: 100.100.0.1/16, listening on udp 51820, the office peered
sudo maluctl gateway expose --bind overlay      # the node API and the faces on the overlay address only
maluctl gateway share                           # on by the chassis rule (a server); contribution always
maluctl estate inference                        # facts: share on, the models; backends: none yet (nobody else shares); peers: office
```

Expect at the office: Settings → Desks → Shared inference lists gpu-1
published (shared, an overlay address, online) with its models and wait.
**`ping office.internal` from gpu answers through the tunnel**: that is the
done-criterion of the proxy round with the office behind nginx. When it
does not, `maluctl estate overlay status` on the spoke says so within two
minutes ("no handshake with the hub at …: UDP 51820 must reach the hub")
and names what to check; on the hub it asks whether the port is forwarded
to it. (With the GPU host as the hub the addresses are the other way
round: the hub is `.0.1`, the office a spoke.)

## Step 3: the desk (slices 1b, 2, 3)

Mint a **desk code** for the person. On **desk**, signed in as them:

```
sudo maluctl office enroll https://app.example.com --code CODE --name "Ed's desk"
maluctl office status                           # enrolled, the key, the heartbeat
maluctl estate overlay status                   # a spoke: 100.100.0.3/16 as ed-s-desk.internal, the hub's last handshake recent
maluctl office inference --refresh              # backends: gpu-1 at 100.100.0.2:11435 with its models and wait; peers: office, gpu-1
maluctl gateway estate                          # the rung estate:gpu-1, healthy (paired with the desk's own inference key)
maluctl gateway chat "Say hello" --model qwen3:8b --prefer estate      # served by gpu-1 over the overlay
```

Then on **gpu**: `sudo maluctl gateway usage --since 1h` shows the call under
`node:desk:<id>` with the origin request; `sudo maluctl gateway node runs
--limit 3` the run with its origin node. On **desk** the System Monitor's
MaluOS Network tab lists `estate:gpu-1` under Paired Nodes.

Checks of the slice 3 test plan on real hosts:

- `sudo maluctl gateway share off` on **gpu**, then the chat again from
  **desk**: refused `not_shared`; `share on` again: served.
- A rule at the office (Settings → Desks → Shared inference → Add rule):
  deny `kind:desk` on gpu-1. Within a desk heartbeat (five minutes, or
  `maluctl office inference --refresh` now) the rung leaves the desk's
  gateway; remove the rule and it returns.
- The entitlement: turn the scheduler on at the office; `maluctl office
  inference --refresh` then shows `editions scheduler; placement by the
  kernel`; the next chat's ledger row carries `placement.reason: placed`
  (`sudo maluctl gateway usage --raw` on **desk**).
- `maluctl gateway chat "x" --model qwen3:8b --prefer estate --sensitivity
  restricted`: refused on the desk's side (`classification:restricted>internal`).

## Step 4: delegation across the estate (slice 2, the proof's steps 1 to 3)

On **office** (the kernel's host joined as a node), create a Help Desk
agent that accepts the organisation:

```
sudo maluctl agent create helpdesk --exec "/usr/bin/python3 /usr/lib/maluos/maluos-agent-demo.py" --scope org:read --tiers fast --capability helpdesk --accept-from org --max-classification internal
```

On **desk**:

```
maluctl office agents --refresh                     # helpdesk on office, capability helpdesk, accepts org
sudo maluctl agent create me --personal --owner user:$USER
maluctl agent send me "ask helpdesk to summarise the last customer complaint"
maluctl estate tasks <id>                           # completed; chain user:… > agent:me > agent:helpdesk; the model calls
```

The chain's model call on **office** goes to its gateway; with slice 3 that
gateway holds the estate rung `estate:gpu-1`, so the Help Desk agent's
model call is served by the GPU host over the overlay: three ledgers (the
desk's, office's, gpu's), one envelope id (`sudo maluctl gateway usage
--envelope ENV` on each), one origin request id per hop. That is step 3 of
the proof; steps 4 and 5 (Projects, the approval reaching the responsible
person, memory) wait for slices 4 and 5.

## Step 5: a node goes away

Power **gpu** off. Within three node heartbeats the office marks it
offline and raises `node_offline`; on **desk** the rung turns unhealthy and
the next chat falls back to the local or the cloud rung (`maluctl gateway
routes`). Power it on: the tunnel comes back on its own (the spoke dials
the hub), the rung heals at the next probe.

## What to record

For each slice's document: the date, the three hosts (chassis, address
kind: static, DHCP, NAT), what passed, what did not, with the command and
its output. Anything that passes on the VM and fails here is a real
finding for the slice.
