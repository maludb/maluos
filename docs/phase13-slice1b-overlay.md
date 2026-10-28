# Phase 13 slice 1b: the overlay (the estate's own network)

Specified 2026-10-28 from the owner's confirmation of the vision
(docs/phase13-estate.md): the people running MaluOS Desktop have no
static addresses, OpenVPN has proved too hard for them, and the estate's
network must come with the packages and be made when a computer joins.
The coordinator stays (decision 1 of the phase); hub and spoke is the
first topology. Nothing here is built. It replaces the "overlay later, if
needed" of decision 4 and is sequenced between slices 1 and 2 in
docs/roadmap.md (D1b); the kernel half needs the owner's approval first.

## What the slice delivers

Every node of an estate, server or desk, has an address on the estate's
private network and a name, wherever it is and whatever its public
address does. The tunnel is WireGuard, made at `maluctl estate join` (and
`maluctl office enroll` on a desk) with no question asked, kept up by a
system service, and taken down by `leave`. The hub is the coordinator's
own host; spokes reach each other through it. A GPU server exposed on the
overlay is reachable from a desk at home as `gpu-1.internal`, which is
what the shared-GPU pairing of G2 needed and the directory of G4 will
use.

```
sudo maluctl estate join https://app.example.com --code 7F3K-2Q9M --hub vpn.example.com:51820   # on the coordinator's host: the hub
sudo maluctl estate join https://app.example.com --code 2B8R-9WLP                               # a server: a spoke
sudo maluctl office enroll https://app.example.com --code 5K2T-77QA                             # a desk: a spoke, as before
maluctl estate overlay status                   # the interface, the address, the hub's last handshake, the peers
maluctl estate overlay peers [--json]           # who is reachable, by name and address
sudo maluctl estate overlay up|down             # by hand; join and leave do it
sudo maluctl estate join … --no-overlay         # a node that must stay off the estate network
sudo maluctl gateway expose --bind overlay      # the GPU box: the node API on the overlay address only
```

## What exists to build on

| Piece | Reused as |
|---|---|
| slice 1: `maluctl estate join`, the host principal, the node key and token in the vault, estate.yaml, `maluos-estated`, the heartbeat | the join makes the overlay key too and carries the public half; the enrolment file carries the `overlay` block; the heartbeat answer carries changes to the hub |
| desk enrolment (docs/desk-enrolment.md): `maluctl office enroll`, office.yaml, the desk token in the owner's compartment | the desk's path to the same overlay |
| decision 8 of slice 1: the coordinator's host joins its own estate as a `server` node | that node is the hub |
| the vault: secrets of kind `key`, read by root as an operator | the WireGuard private key, never in a file on disk |
| the gateway's TCP listener (`maluctl gateway expose --bind ADDR`, G2) and the `remote` backend | `--bind overlay`; pairing URLs by estate name |
| WireGuard in the Ubuntu 26.04 kernel; `wireguard-tools` 1.0.20250521 in main | the tunnel; `wg`, no daemon of its own |
| the mock office (maluos-estate) and the boot test | the mock's overlay answers; the slice's test |

## Decisions

1. **WireGuard, hub and spoke, the coordinator's host as the hub.** The
   hub is the one machine an estate already has to make reachable (its
   office URL); it gains one UDP port (51820 by default) forwarded to it.
   Every spoke keeps one tunnel to the hub with a 25-second keepalive,
   so a desk behind a home router or on a phone's hotspot stays
   reachable without any address of its own; traffic between two spokes
   goes through the hub, which forwards on the overlay interface only.
   A mesh with NAT traversal and relays (what Tailscale and Headscale
   do) is not attempted; direct links between two nodes on one LAN are a
   later optimisation that changes routes, not the design.
2. **The join makes the network.** `maluctl estate join` and `maluctl
   office enroll` generate the WireGuard key, send the public half,
   receive the node's address, the hub's key and endpoint, write them to
   the enrolment file, store the private key in the vault and start
   `maluos-overlay.service`. No second command, no dialog, no file for
   the person to edit. `--no-overlay` opts a node out; nothing else
   changes for it.
3. **Addresses are the kernel's to give and names are the kernel's to
   publish.** The estate has one private IPv4 range (`100.100.0.0/16` by
   default, in Settings → Estate; the CGNAT block, which no LAN uses), the
   hub is `.0.1`, every node receives an address at join that it keeps
   for its life, and a retired node's address is reused after 30 days.
   Every node resolves every other as `NAME.internal` (`.internal` is the
   private-use top-level domain; `.estate` is a public one): the overlay
   service keeps a marked block in `/etc/hosts` from the kernel's list,
   which works on both profiles without touching the resolver.
4. **The private key lives in the vault, the public key in the
   directory.** `estate-overlay-key` (kind `key`) sits beside the node
   token: in the host principal's compartment on a server, in the owner's
   compartment on a desk, like slice 2's desk key. The overlay service
   runs as root, reads it as an operator and hands it to the kernel's
   WireGuard through a pipe; it is never written under /etc/wireguard.
   The kernel stores only public keys. Rotation is `maluctl estate
   overlay rotate` (a new key, `POST …/overlay/key`, the hub re-peered),
   not automatic in this slice.
5. **The overlay carries node-to-node traffic; the office stays on
   HTTPS.** Heartbeats, reports, the directory and (in slice 2) tasks keep
   going to the office URL as today, so a node whose tunnel is down is
   still a member and still reports. What moves onto the overlay is what
   decision 4 of the phase deferred: the gateway's node API (G2's
   `expose --bind overlay`), slice 3's remote inference, slice 4's memory
   queries. Decision 2 of the phase holds unchanged: an address on the
   overlay is reachability, not permission; every service keeps its own
   tokens, keys and envelopes.
6. **The hub forwards, and only on the overlay.** The hub sets
   forwarding on the `estate` interface alone (`net.ipv4.conf.estate.
   forwarding`), with each spoke's `/32` as its allowed address, so a
   spoke can reach other spokes and the hub, and nothing on the hub's
   LAN. A spoke's allowed addresses are the whole range through the hub.
   No masquerading, no route to the internet through the hub: this is
   not a VPN for browsing.
7. **Community edition.** The overlay is what makes an estate work
   across the places its people are; it ships with joining, in
   maluos-estate, on both profiles. Many hubs and failover are the
   Enterprise `fleet` conversation of decision 10, not this slice.

## The contract, surface 1, overlay additions

**Join request** (`POST /api/v1/estate/join`, and the desk's
`POST /api/v1/desks/enroll`) gains one field:

```json
{"…": "as slice 1", "overlay_public_key": "<WireGuard public key, base64>",
 "overlay_hub": {"endpoint": "vpn.example.com:51820"}}
```

`overlay_hub` is sent only by the hub's join (`--hub ENDPOINT`); a second
hub is refused with 409 `hub_exists` until the first leaves. A join
without `overlay_public_key` (`--no-overlay`, or an older maluos-estate)
is accepted and the node simply has no address.

**Join answer** gains `overlay` (null when the estate has no hub yet, or
the node opted out):

```json
"overlay": {"address": "100.100.0.57", "prefix": 16, "name": "db-1.internal",
            "hub": {"public_key": "…", "endpoint": "vpn.example.com:51820", "address": "100.100.0.1"},
            "role": "spoke", "listen_port": null}
```

The hub's own answer has `"role": "hub"`, `"listen_port": 51820` and
`"hub": null`.

**`GET /api/v1/estate/overlay`** (bearer, node token) and
**`GET /api/v1/desks/overlay`** (bearer, desk token), polled by the
overlay service every `refresh_s` (60) and on SIGHUP:

```json
{"ok": true, "surface": 1, "fetched_at": "…",
 "self": {"address": "100.100.0.57", "role": "spoke"},
 "hub": {"public_key": "…", "endpoint": "vpn.example.com:51820", "address": "100.100.0.1"},
 "peers": [{"public_key": "…", "address": "100.100.0.1", "name": "office-1"}],
 "names": [{"name": "office-1", "address": "100.100.0.1"}, {"name": "db-1", "address": "100.100.0.57"},
           {"name": "eds-desk", "address": "100.100.0.12"}],
 "refresh_s": 60}
```

For a spoke `peers` is the hub alone; for the hub it is every active node
with a key (its `/32` each). `names` is every active node with an
address, which becomes the `/etc/hosts` block on every member. A node
whose heartbeat answer carries `"overlay_changed": true` (a new hub key
or endpoint, a node joined or left) refreshes at once instead of waiting.

**`POST /api/v1/estate/overlay/key`** (bearer) `{"overlay_public_key":
"…"}` replaces the node's key (rotation); **leave** frees the address and
drops the node from every member's `peers` and `names` on their next
refresh.

`endpoints.overlay` names the GET in every join, me and heartbeat answer;
null means the estate has no overlay for this node.

## The kernel half (maludb-os-core)

For the owner's approval, beside db/188:

- db/189: a settings row `estate_overlay` (`enabled`, `range` default
  `100.100.0.0/16`, `hub_location_id`, `hub_endpoint`, `hub_public_key`);
  `locations.overlay_public_key text`, `overlay_address inet`,
  `overlay_address_freed_at`; the allocator (lowest free address, the
  hub `.0.1`, 30-day quarantine on retirement).
- `html/api/v1/estate/overlay.php`, `overlay/key.php` and
  `html/api/v1/desks/overlay.php`; the join and enroll handlers take and
  return the overlay fields; `overlay_changed` on heartbeat answers after
  any change to the hub or the membership; `endpoints.overlay` on every
  answer.
- Settings → Estate shows the overlay: the range, the hub and its
  endpoint, each node's address and name, "the hub has not joined yet"
  until it has.
- proof `bin/test_estate_overlay.php`.

## The host half

**maluos-estate 0.2.0** (Depends: `wireguard-tools`; both seeds already
install the package):

- `lib/maluos_estate/overlay.py`: the overlay service, `python3 -m
  maluos_estate.overlay`, run by `maluos-overlay.service` as root with
  `CapabilityBoundingSet=CAP_NET_ADMIN` and the gateway's other
  hardening; `ConditionPathExists=|/etc/maluos/estate.yaml`,
  `|/etc/maluos/office.yaml`. It reads whichever enrolment exists, takes
  the token and the private key from the vault, makes the `estate`
  interface (`ip link add … type wireguard`, `wg set` with the key on a
  pipe, the address, the hub as the peer with keepalive 25, `up`), then
  every `refresh_s` fetches `endpoints.overlay` and reconciles the peers
  and the `/etc/hosts` block (`# maluos-estate overlay begin … end`).
  On the hub it also sets the listen port, forwarding on the interface
  and every spoke as a peer. SIGHUP refreshes now; SIGTERM leaves the
  tunnel up (a service restart must not drop the network); `overlay
  down` and `leave` take it down and remove the hosts block. The state
  (`/var/lib/maluos/overlay/state.json`: last refresh, peers, the hub's
  last handshake from `wg show`) feeds `maluctl estate overlay status`.
- `maluctl estate join` and `office enroll`: `wg genkey` into the vault
  as `estate-overlay-key`, `overlay_public_key` in the request, `--hub
  ENDPOINT`, `--no-overlay`, the `overlay` block written to estate.yaml
  or office.yaml, `systemctl enable --now maluos-overlay`. `leave`:
  `overlay down`, the key deleted with the token. `maluctl estate
  overlay status|peers|up|down|rotate`.
- `maluos_estate.client`: `overlay(conf, tok)` for the GET, the key POST;
  `report.py` gains `overlay` (interface up, address, hub handshake age,
  peers) so the Estate page can show a node whose tunnel is down.
- The session and the Estate page: the node's overlay address and name
  on the node rows (`maluctl office estate`, the Network tab's Estate
  group, the Desk's Estate row); a notification when the desk's tunnel
  has had no handshake for three minutes.

**maluos-gateway 0.5.0**: `maluctl gateway expose --bind overlay`
resolves to the node's overlay address at every start (the config keeps
the word, not the address), refuses when the node has none, and the
listener follows the address if it changes. G2's pairing recipe in
docs/phase13-shared-gpus.md becomes `backend add gpu-1
https://gpu-1.internal:11435 --key …`.

**The mock office**: the overlay settings (`--overlay 100.100.0.0/16`,
default on), the allocator, the hub registration, `/api/v1/estate/overlay`
and the desk twin, `overlay/key`, `overlay_changed`, and `/mock/overlay`
for the tests to read the allocation; a fake spoke (`--overlay-spoke
NAME=PUBKEY`) so a hub under test has a peer to show.

## Test

- tests/desk-local-test.sh: the join against the mock with
  `MALUOS_OVERLAY_DRY_RUN=1` (the overlay service prints the `ip`, `wg`
  and `sysctl` commands it would run and writes a hosts block in a test
  file): the key in the vault and not on disk, the public key registered,
  the address and name in estate.yaml, the hub's peer line with keepalive
  25, the hosts block with every name, the refresh after a mock
  membership change, leave removing all of it; the desk path through
  `office enroll`.
- tests/qcow2-boot-test.sh, both profiles: the VM joins as the hub
  (`--hub 127.0.0.1:51820`): the `estate` interface exists with
  `100.100.0.1/16`, `wg show estate` lists the mock's fake spoke,
  forwarding is set on the interface only, `/etc/hosts` resolves
  `test-node.internal` and the spoke's name, the gateway exposed with
  `--bind overlay` answers `/node/v1/health` on `100.100.0.1:11435` and
  not on the LAN address. Then a real spoke in a network namespace: the
  test runs the overlay service a second time with a second enrolment
  (`MALUOS_ESTATE_CONF`, a second mock code) inside `ip netns exec
  spoke`, over a veth pair, and checks a handshake on both sides and a
  ping from the spoke to the hub's overlay address; `leave` on the hub
  tears down the interface and the hosts block.
- The three-machine proof (docs/phase13-estate.md) gains a step 0: the
  desk is on a different network from the servers, and every later step
  runs over the overlay.

## Deferred

- Direct spoke-to-spoke links on a shared LAN, NAT traversal, relays:
  after the hub has proved itself; `peers` is where the kernel would add
  a second endpoint.
- A second hub, failover, many coordinators: the Enterprise `fleet`
  conversation (decision 10 of the phase) and slice 6.
- IPv6 on the overlay; names through systemd-resolved instead of
  `/etc/hosts`; automatic key rotation: when a measured need appears.
- Binding the vault's and memory's remote faces to the overlay: slice 4,
  which makes those faces.
- A firewall policy per service on the overlay interface: with G4's
  admission control, when more than the gateway listens there.

## Effort

| Part | Size | Notes |
|---|---|---|
| the overlay service, the join and enroll changes, the commands | M | `wg` and `ip` do the work; the service is a reconciler |
| the gateway's `--bind overlay` | S | |
| the session and the Estate page additions | S | |
| the mock | S | |
| the local test and the boot test (the namespace spoke) | M | the namespace spoke is the only new test mechanism |
| the kernel half | M | separate repository, owner's approval first |

About the size of slice 1's host half. Two build-and-test rounds on each
image.

## Status

**Both halves built 2026-10-28**, the day after the specification and the
owner's approval of db/189:

- The kernel half (maludb-os-core 6c94d29, vendored as maludb-os-core
  2026.10.28maluos1): db/189 (`estate_overlay`, the members' keys and
  addresses with the 30-day quarantine, a version), join and enroll taking
  the key and `--hub`, the `overlay` block in the answers, `GET
  /api/v1/estate/overlay` and `/api/v1/desks/overlay`, `POST
  overlay/key`, `overlay_changed` on heartbeats, Settings → Desks showing
  the overlay for an operator; proof `bin/test_estate_overlay.php` (48
  checks). The kernel half of slice 1 (db/188) landed with it.
- The host half: maluos-estate 0.2.0 (`maluos_estate.overlay`, the
  service, the join's key, `maluctl estate overlay`, the report's
  `overlay`, the mock's overlay contract), maluos-desk 0.5.1 (the desk's
  key at enroll, the tunnel down at leave, the hint on `overlay_changed`),
  maluos-gateway 0.5.0 (`expose --bind overlay`).
- Tests: tests/desk-local-test.sh (the service in a dry run: this host as
  the hub, a desk as its spoke, the names, rotation, the hint, down,
  leave; 87 checks in all), tests/qcow2-boot-test.sh (both profiles: the
  VM joins as the hub with a real `estate` interface, the mock's fake
  spoke peered, forwarding, the names resolving, the gateway on the
  overlay address only; the desktop's desk as the hub's spoke).
- **Images boot-tested 2026-10-28** (both profiles, 488 checks). The chain
  took three runs: the mock estate crashed when given a fake spoke, and
  the overlay unit shared `StateDirectory=maluos/estate` with the daemon,
  which systemd re-owned to root when the overlay started (maluos-estate
  0.2.1: the overlay's state in `/var/lib/maluos/overlay`); then a first-boot
  timing flake in the vault component (maluos-vault 0.4.2: a deadline and
  OSError tolerated; maluos-gateway 0.5.1: the routes listing tolerates an
  empty class).

Where the build departs from the text above, and why:

1. **The key is made with python3-cryptography, not `wg genkey`**, so the
   local test and a host without `wireguard-tools` at hand can still make
   and verify keys; the private key reaches `wg` on stdin and is never
   on disk.
2. **The hint is a file, not a signal.** `maluos-estated` and `maluctl
   office heartbeat` run as unprivileged users and cannot signal a root
   service; they touch `/run/maluos/overlay/changed` (the unit's runtime
   directory, mode 1777) and the service, which polls it every two
   seconds, refreshes at once. SIGHUP works too.
3. **A member that joins before any hub keeps its address** and the
   service waits ("no hub yet") until one joins; the join answer's
   `overlay` is null meanwhile, as specified, and the enrolment file
   records the key was sent.
4. **The network-namespace spoke of the boot test is not built.** The
   hub's side is proved with a real interface and the mock's fake spoke
   (its public key peered, its name resolving); the first real handshake
   between two hosts waits for the three-machine proof, where the desk
   and a server are different machines.
5. **No Estate page or indicator change beyond the address**: the kernel's
   node rows carry `overlay.address`, `maluctl estate nodes` and
   `maluctl office estate` pass it through; the Network tab's rows stay
   as G5 left them until the directory (G4) uses the names.
