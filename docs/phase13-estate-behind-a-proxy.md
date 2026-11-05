# Phase 13, the estate behind a proxy: the hub as a setting, the office's names under https

Specified and built 2026-11-05 from the first end-to-end test on real
hosts (the owner's handbook, github.com/maludb/maluos-docs:
[22-estate-behind-a-proxy.md](https://github.com/maludb/maluos-docs/blob/main/22-estate-behind-a-proxy.md),
[30-reverse-proxy.md](https://github.com/maludb/maluos-docs/blob/main/30-reverse-proxy.md),
[13-estate.md](https://github.com/maludb/maluos-docs/blob/main/13-estate.md)).
The test stopped at its stage 4: the office, a VM behind an nginx reverse
proxy on its own network, had joined its estate as the hub on a LAN
address no spoke can dial, and under `scheme: https` the office could not
reach its own names. Both were design gaps, not configuration mistakes.
This note weighs the transports, decides, and records what was built in
maluos (maluos-estate 0.7.0, the kernel component, the installer) and in
the kernel repository (maludb-os-core 8600c3d, the branch
`estate/hub-and-proxy-address`). It amends decision 1 of
docs/phase13-slice1b-overlay.md and keeps decision 2 of
docs/phase13-estate.md.

## What the test found

The common office is not a server on a public address. It is a VM behind
a reverse proxy (nginx on 192.168.100.1 terminating TLS for
`app.<domain>`, `os.<domain>` and every application name; the VM listens
on :80), and the members are elsewhere: the GPU server and the desks reach
the kernel only through the proxy's public names, which carry everything
that goes over HTTPS. Two things did not survive that:

1. **The hub.** Slice 1b put the WireGuard hub on the coordinator's host
   (`maluctl estate join … --hub HOST:PORT` on the office) and every other
   member keeps one tunnel to that endpoint on UDP 51820. nginx does not
   forward UDP, and the endpoint was fixed at the join: the office joined
   with `--hub 192.168.100.120:51820`, a hub nobody can dial, and the
   only way out was `leave`, a new code and a second join.
2. **The office's own names.** The kernel component's step 1 wrote
   `127.0.0.1 <domain> www.<domain> os.<domain> app.<domain>` into
   `/etc/hosts` so the kernel's URLs resolve on the office. Under https
   nothing on the office listens on 127.0.0.1:443, so every https client
   on the office was refused: `maluctl estate join https://app.<domain>`
   ("Connection refused"), the application installer's health and sign-on
   probes, the kernel's agents dialling applications. The operator's fix
   was to point the names at the proxy's LAN address instead.

## The candidates for part 1, weighed

| | Option | What it needs | Verdict |
|---|---|---|---|
| a | **The hub elsewhere.** Any member with a reachable UDP port is the hub; the office joins as a spoke and the spokes learn the hub's endpoint from the directory | the kernel to accept a hub that is not the coordinator (it already does: `overlay_set_hub()` never looked at which node asks); a way to move the role without a leave; the docs to stop saying "the coordinator's host" | **taken**, with the role made a setting of the running estate |
| b | **The hub on the office through a forward.** UDP 51820 forwarded to the office VM by the router in front of the proxy, or by nginx's stream module on the proxy host (`listen 51820 udp; proxy_pass <office>:51820; proxy_timeout 10m`, longer than the 25 s keepalive); the join takes the public name | no code: WireGuard needs nothing from the path but datagrams delivered back to the same source within the keepalive, which a UDP forward or stream proxy does; a check that the port actually reaches the hub | **taken as the documented special case of (a)**: the office is the hub, its endpoint a public name; the status verdict says when the port does not reach it |
| c | **Relay through the kernel.** Node-to-node calls (inference, memory, A2A tasks) carried over HTTPS to the coordinator and long-polled or streamed to the target; the kernel the only reachable party; the overlay the fast path where it forms | a per-node channel in the kernel with leases and backpressure, a `via: office` transport in the gateway's `remote` backend and the memory face, streaming through PHP, the kernel's bandwidth on every token; A2A tasks already travel this way (slice 2's inbox) | **deferred** to its own slice, sketched below; nothing built until an estate exists in which no member can take one UDP port |
| d | **A mesh with NAT traversal and relays** (the Tailscale and Headscale shape) | hole punching, a STUN-like service, relays for the pairs that fail, key distribution per pair, a second control-plane protocol | **stays deferred** (slice 1b, "Deferred"): it answers a question the estate does not have yet (the hub as a bottleneck, every spoke-to-spoke byte crossing it) at the price of (c) and more; revisited with slice 6's second hub, when the hub is measured, not assumed, to be the limit |

## Decisions

1. **The hub is whichever member the others reach on one UDP port.** The
   coordinator's host is not special: it is the hub when it has the port
   (a server on a public address, or behind a forward), and a spoke like
   any other when it does not (a VM behind a proxy that forwards HTTPS
   only). A GPU server with a public port, or any server node, may be the
   hub. A desk is never the hub: it has no fixed address, its owner can
   close the lid, and (decision 7) the hub sees spoke-to-spoke traffic in
   the clear. The kernel accepted this already; the documents said
   otherwise, and now say this.
2. **The hub endpoint is a setting of the running estate, not a constant
   of a join.** `sudo maluctl estate overlay hub HOST:PORT` on a node
   takes the hub role, or changes the endpoint when the node is the hub
   already; `sudo maluctl estate overlay hub off` releases it. The kernel
   serves `POST /api/v1/estate/overlay/hub` (node token): 409
   `hub_exists` while another member holds the role (it releases, or is
   retired at Settings → Desks), 409 `no_key` for a member that joined
   `--no-overlay`, 409 `not_hub` for a release by a non-hub. The former
   hub keeps its membership and key and moves to an ordinary address so
   the next hub can take the range's first; every move bumps the overlay
   version, so the members hear `overlay_changed` on their next heartbeat
   and re-peer at once. `--hub` at join is unchanged and remains the
   short way when the operator knows at join time. The owner's office
   recovers with one command: `overlay hub off` on the office, then
   `overlay hub <public name>:51820` on the member that has the port, or
   `overlay hub vpn.<domain>:51820` on the office itself once the forward
   exists.
3. **Two deployments are supported and documented, one mechanism.**
   *The hub elsewhere*: the office joins as a spoke, the GPU server (or
   another server node) joins with `--hub` or takes the role later; the
   office's own gateway and memory face then sit on the overlay as
   spokes, which changes nothing in slices 3 and 4 (their `published`
   rule asks for an overlay address and presence, not for the hub role).
   *The hub on the office through a forward*: UDP 51820 to the office VM
   from the router in front of the proxy, or nginx's stream module on the
   proxy host, and `--hub vpn.<domain>:51820` (or `overlay hub`) with a
   name that resolves to the forwarder; the handbook's 30-reverse-proxy.md
   already describes the router forward, and the stream block is given
   below. Which of the two an estate uses is the operator's call; the
   runbook (docs/phase13-three-machine-proof.md, step 0) asks it first.
4. **Reachability is diagnosed, not assumed.** The one thing the overlay
   needs from the network is one UDP port reaching the hub, and WireGuard
   is silent when it does not. `maluctl estate overlay status` (and the
   node's report, so the Estate page can show it) now gives a verdict
   from the handshakes: a spoke with no handshake 90 s after its tunnel
   came up, or none for 180 s, says so and names the endpoint (with what
   its host resolves to, or that it does not resolve) and what to check
   (the forward on the router or the proxy's stream module); a hub with
   spokes peered and none handshaken asks whether the port is forwarded
   to it. `join --hub` and `overlay hub` warn when the endpoint's host
   does not resolve from where they run. WireGuard itself is not probed:
   there is nothing to probe.
5. **The relay (c) is deferred, and its shape is fixed now so nothing
   built here forecloses it.** When an estate exists in which no member
   can take one UDP port (an office in a cloud with every member behind
   a corporate NAT that forwards nothing), node-to-node calls would ride
   the kernel: a per-node channel beside slice 2's inbox (leased, with a
   deadline, bodies streamed in chunks under a size cap), the gateway's
   `remote` backend and the memory face gaining `via: office` as a
   transport chosen when the directory publishes a holder with no
   overlay address, the ledger rows carrying the relay hop. The overlay
   stays the fast path where it forms. Not before a measured need: it is
   the most work of the four and the only one whose cost (the kernel in
   the data path of every token) is paid on every call.
6. **`--no-overlay` falls back to the kernel, which is option (c) for
   everything that already goes through the kernel.** A member that
   joined without an overlay key, or whose estate has no hub, keeps:
   enrolment and the heartbeat, the report and the operator's view, the
   catalogue and the applications the office publishes to its desks, the
   agent directory and delegation (slice 2's tasks and actions are leased
   from the kernel's inbox over HTTPS), the office's own model endpoint
   (`endpoints.models`), memory through the office (the office's own
   scopes answer at `endpoints.memory` and the Memory MCP), and G2's
   pairing by hand (`maluctl gateway backend add NAME URL --key …`
   against a gateway exposed with `--bind ADDR` on a LAN or public
   address). It loses what slices 1b, 3 and 4 put on the overlay:
   direct inference between members (a host without an overlay address
   publishes no backend; slice 3 decision 3), direct memory queries to
   other holders (slice 4, the same rule), `gateway expose --bind
   overlay` and `memory expose` (no address to bind), and the names
   `NAME.internal`.
7. **Connectivity is not permission (decision 2 of the phase, kept).**
   Moving the hub changes routes and nothing else: every service keeps
   its tokens (the node API's keys, the estate inference key), its
   envelopes (slice 2's signatures, slice 4's self-envelopes) and its
   policy, checked on the receiving host against its own vault and the
   kernel's published peers. The hub forwards on the overlay interface
   only (slice 1b, decision 6). One consequence is stated here because
   the hub may now be a node other than the office: in a hub-and-spoke
   WireGuard network the hub decrypts a spoke's packet and encrypts it
   again for the other spoke, so the hub's operating system sees
   spoke-to-spoke traffic in the clear, as the office did before. The hub
   is therefore always a server node an operator joined with a server or
   inference code, never a desk; and the data that crosses it is already
   bounded by what the services let out (claims, not records; model
   calls under the caller's classification ceiling). An estate whose
   policy cannot accept that on its GPU server keeps the hub on the
   office through a forward (decision 3).
8. **The office's own names under https go to the proxy, or nowhere.**
   `components.maludb-os-core.proxy_address` (the proxy's address as the
   office sees it, an address literal or a host name resolved once at
   provisioning) is new and optional. Under `scheme: https` the kernel
   component writes the four kernel names and, after step 9, every
   installed application's name to that address in a marked block of
   `/etc/hosts` (`# maluos business-os names begin … end`, one line per
   name) and takes those names off every loopback line (an earlier run,
   the kernel's installer, a hand), because nothing on the office serves
   https on loopback. Without a `proxy_address` it writes no line, clears
   the same loopback lines, and says so in the summary (`hosts.mode:
   none`, with the sentence `maluctl status` shows) and the log. Under
   `scheme: http` the behaviour is as it was: the names on loopback,
   where Apache answers; a stale block from an https run is removed. The
   kernel's application installer takes `--proxy-address` (the component
   passes it under https): a name that does not resolve, or resolves to
   loopback, is written to the proxy's address, and the sign-on proof
   dials it; an older installer ignores the option and the component
   fixes its line afterwards. The installer's First boot screen asks for
   the proxy address beside the domain and the scheme (https only), the
   plan checks it, the conffile documents it.

## nginx's stream module, when the proxy host is the forwarder

On the proxy host (Ubuntu: `apt install libnginx-mod-stream`), outside
the `http {}` block:

```
stream {
    server {
        listen 51820 udp;
        proxy_pass 192.168.100.120:51820;   # the office VM
        proxy_timeout 10m;                  # longer than the spokes' 25 s keepalive
        proxy_responses 0;                  # a session, not request and reply
    }
}
```

The office joins with `--hub vpn.<domain>:51820` where `vpn.<domain>`
resolves to the proxy's public address (an A record, or the same name as
`app.`); `wg show estate` on the office then lists every spoke with the
proxy's LAN address as its endpoint, which is right: the proxy keeps one
UDP session per spoke and maps the replies back. A router forward to the
VM (the handbook's 30-reverse-proxy.md) is the same thing one hop out.

## The contract, surface 1, the hub endpoint

**`POST /api/v1/estate/overlay/hub`** (bearer, node token; a desk token
is refused 401):

```json
{"surface": 1, "endpoint": "vpn.example.com:51820"}     → this node takes the hub role, or changes its endpoint
{"surface": 1, "endpoint": null}                        → this node releases the hub role
```

Answer (200): `{"ok": true, "surface": 1, "hub": {"endpoint", "address",
"name", "id"} | null, "overlay": <the node's overlay block, or null while
the estate has no hub>}`. Errors: 400 `invalid` (not host:port, or no
`endpoint` key), 409 `hub_exists`, 409 `no_key`, 409 `not_hub`. The
members' `GET …/overlay` answers carry the new hub on their next refresh;
their heartbeats say `overlay_changed`.

The join's `overlay_hub` and the leave's unsetting of the hub are as in
slice 1b. The Settings → Desks overlay paragraph shows whichever node is
the hub.

## The host half (built 2026-11-05)

**maluos-estate 0.7.0**

- `maluctl estate overlay hub HOST:PORT | off` (root, a node): the POST,
  the enrolment's `overlay` block rewritten from the answer, then on a
  claim the overlay service restarted (it re-reads the block: the listen
  port, every spoke as a peer, the range's first address on the
  interface) and on a release the interface taken down (the service
  waits for a hub, as a node that joined before any hub does). A node
  that joined `--no-overlay` is refused before the office is asked; an
  office before this change answers 404 and the command says what to do
  instead.
- `maluos_estate.overlay`: a moved hub is handled by the reconciler, not
  by hand: the interface's addresses are pruned to the one the office
  gives (a demoted hub loses `.0.1`, a changed address is replaced), a
  demoted hub gives up its listen port, the state records `since` (when
  the current role and address were configured) and `reachability()`
  gives the verdict of decision 4; `resolve_note()` says what an
  endpoint's host resolves to.
- `maluctl estate overlay status` prints the verdict as a `warn:` line;
  the report's `overlay` carries it as `warning`; `join --hub` warns on a
  host that does not resolve.
- The mock office serves `overlay/hub` with the kernel's semantics.

**maludb-os-core 2026.11.05maluos1** (the component and the vendored
kernel at 8600c3d)

- `components/60-maludb-os-core.py`: `proxy_address`, the hosts rule of
  decision 8 in `point_names()` (step 1 for the kernel's names, again
  after step 9 for the applications'), `--proxy-address` passed to the
  installer, the summary's `proxy_address` and `hosts {mode, address,
  note}`.
- `lib/maludb_os_apps.py`: `office_hosts(text, names, address)` (pure:
  the block, the loopback lines, idempotent), `resolve_address()`,
  `install_command(…, proxy_address)`.

**maluos-installer 0.3.6**: the First boot screen's "Proxy address, https
only" field under the scheme, with its hint; `plan.py` checks
`proxy_address` is an address or a host name. **maluos-firstboot 0.1.16**:
the conffile's commented `proxy_address`.

## The kernel half (maludb-os-core 8600c3d, branch estate/hub-and-proxy-address)

- `app/features/estate/overlay.php`: `overlay_claim_hub()`,
  `overlay_release_hub()`; `html/api/v1/estate/overlay/hub.php`; the
  Apache rewrite line in docs/deploy/apache-react-cutover.conf.
- `bin/app_install.php --proxy-address <addr>`: the dns step and the
  sign-on proof of decision 8.
- `bin/test_estate_overlay.php`: the "hub as a setting" section (a spoke
  refused while a hub exists, the hub's endpoint changed and heard, a
  bad endpoint, a release by a non-hub, a desk token, a keyless member,
  the release, the GPU host taking the hub and the office becoming its
  spoke, and back). docs/build-specs/estate-overlay.md records it. The
  proof needs a running kernel (`BOS_INTERNAL_URL`), which this
  development VM does not have: the files are linted, the proof is the
  owner's to run on the office or the GPU dev host before the branch
  merges.

## Test

- tests/apps-test.py: `office_hosts` (the block replaces loopback, follows
  the names and the address, nothing without an address, a shared
  loopback line keeps its other names, http leaves the file alone and
  drops a stale block), `resolve_address`, `--proxy-address` on the
  installer's command line. tests/install-plan-test.py: `proxy_address`
  accepted and checked.
- tests/desk-local-test.sh, the slice 1b section: `overlay hub` on a
  desk refused, a bad endpoint refused, the hub changing its endpoint
  (the desk given it, the interface re-set), the release (the interface
  down, the node on an ordinary address, the desk without a place), a
  second release 409, the hub taken back at `.0.1`; a `--no-overlay` node
  refused.
- tests/qcow2-boot-test.sh: the server seed asks for `scheme: https` with
  `proxy_address: 10.0.2.2` (QEMU's gateway stands in for the proxy;
  `BOOT_TEST_PROXY=0` keeps http): the four names resolve to it from the
  marked block, none on loopback, the summary says `proxy 10.0.2.2`; in
  the estate section the hub role released (the interface gone, the mock
  without a hub) and taken back (the service remakes the interface, the
  fake spoke peered, the names back).
- The three-machine proof: docs/phase13-three-machine-proof.md, step 0
  asks where the hub is; its done-criterion with the office behind nginx
  is `ping office.internal` answering from the GPU host after its join.

## Deferred

- The relay through the kernel (decision 5) and the mesh (decision 4 of
  the table): with a measured need.
- A hub chosen by the kernel (the member whose endpoint the others last
  reached) and a hub that moves on its own when the current one is
  offline: slice 6's second hub and failover.
- The Estate page showing the verdict as a notification ("the GPU host
  cannot reach the hub"): the report carries it; the page's row is G5's.
- `office enroll --hub`: a desk is never the hub (decision 1).

## Effort

| Part | Size |
|---|---|
| the kernel half (the endpoint, the installer option, the proof) | S |
| the host half (the command, the reconciler's moves, the verdict, the mock) | M |
| part 2 (the component, the library, the installer screen and plan, the tests) | M |
| the documents (this note, the runbook, slice 1b, the roadmap, install-plan, components) | S |

## Open questions for the owner

1. **Which member is the hub in the test estate?** The GPU server, if it
   has (or can be given) one public UDP port; else the office through a
   forward at the proxy host: nginx's stream block above, or the router
   forward the handbook already describes. The runbook supports both;
   the note recommends the GPU server when it has the port, because it
   leaves the proxy host untouched and the office a plain spoke.
2. **The branch `estate/hub-and-proxy-address` in maludb-os-core** is
   vendored here at 8600c3d but not pushed: the owner merges it (after
   `bin/test_estate_overlay.php` on a kernel) and, as with db/188 to
   db/193, the VENDORED ref is then `main`.
3. **`proxy_address` on the office**: the proxy's LAN address
   (192.168.100.1), as the operator did by hand, not its public address
   (a LAN that does not hairpin cannot reach its own public address);
   confirm that is what the handbook's stage 1 writes, and whether the
   handbook's `plans/office.yaml` should carry it.
4. **Should an operator be able to move the hub from the office's
   Settings page** (retire the hub's role without the node's own token,
   for a hub that is gone)? Today: retire the node at Settings → Desks,
   which unsets the hub, and claim elsewhere. A button is a small kernel
   change if wanted.
5. **The relay (decision 5)**: schedule it only when an estate without
   any UDP port appears, or now as insurance? The note says when it
   appears.

## Status

**Built 2026-11-05** on the development VM (the Proxmox VM, no KVM):

- tests/apps-test.py 20 ok, tests/install-plan-test.py 40 ok,
  tests/install-screens-test.py PASS twice (the medium's http plan, and
  `--https` with the proxy address typed into the First boot screen).
- tests/desk-local-test.sh: 156 checks, 0 failed, the seven hub checks
  among them (the endpoint moved and the desk given it, the release with
  the interface down and the node on an ordinary address, a second
  release 409, the role taken back at `.0.1`, a desk and a `--no-overlay`
  node refused).
- The kernel's proof (`bin/test_estate_overlay.php`) is linted, not run:
  no kernel runs on this VM. The owner runs it on the office or the GPU
  dev host before merging the branch.
- The server image's UEFI boot test (build/logs/chain-d1c.sh: packages,
  the repository, the server rootfs and qcow2, the test with the https
  seed and the hub round trip): **215 ok, 0 FAIL** on the second run
  (23:43 UTC; log build/logs/chain-d1c.run2.log). The first run's two
  failures were the new hosts checks' own text (the script's variable
  does not reach the quoted heredoc the VM runs), with the right hosts
  block and summary printed; the checks now read the VM's own
  `proxy_address`. On the real overlay service the hub role released
  (the interface gone, the mock without a hub) and taken back (the
  interface remade, the fake spoke peered, the names back); under https
  the four names resolve to 10.0.2.2 from the marked block and none on
  loopback, the summary says `proxy 10.0.2.2`.

The owner's three machines run the proof (docs/phase13-three-machine-proof.md,
step 0a first).
