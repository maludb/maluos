# Stage 4: the estate, two servers as one network

The kernel's estate is its model of every machine that joined it. The
office joins its own estate first and becomes the hub of a WireGuard
overlay; the GPU server joins as an inference node and becomes a backend
the whole estate can use. After this stage the office's Settings → Estate
page shows both, and a model call from any member can be served by gpu-1
over the tunnel.

This enrolment path uses the MaluOS estate client. For Apple Silicon Macs
and DGX Sparks retaining their vendor OS, use [ARM inference](11-arm-inference.md).
The standalone node repository does not yet ship an estate client or a
runnable inference API; do not apply these `maluctl` commands to those hosts.

Machines: **office**, **gpu-1**. Exit criterion: both nodes online at the
office, gpu-1's models listed under Shared inference.

This is `maluos/docs/phase13-three-machine-proof.md` steps 1 and 2 with
the names of this test.

## 0. Where the hub is

The tunnel is UDP 51820 to one member, the hub; nginx cannot carry it
([30-reverse-proxy.md](30-reverse-proxy.md)). Decide this before any
join (maluos `docs/phase13-estate-behind-a-proxy.md`, decision 3):

- **The office has the port**: the router in front of the proxy forwards
  UDP 51820 to the office VM, or the proxy host's nginx `stream` block
  does. The office is the hub, endpoint `vpn.$DOMAIN:51820` with an A
  record to the proxy's public address.
- **The office has no port**: the member that has one is the hub, the GPU
  server in this test (its network forwards UDP 51820 to it, a public
  name points there), and the office joins as a spoke.

**This test's choice (2026-11-06): the office is the hub, through the
proxy host's nginx `stream` block**, endpoint `vpn.tipdesk.org:51820`.
The proxy host already carries every exposure of the office, and the GPU
server stays a plain spoke on its own network.

The role moves without a leave: `sudo maluctl estate overlay hub off` on
the member that holds it, `sudo maluctl estate overlay hub HOST:PORT` on
the one that should. An office that joined as the hub on an address
nobody reaches (this test's first attempt) recovers that way.

Both servers must run the 26.04.20261106 packages first (`maluos-estate
0.7.0`, `maludb-os-core 2026.11.06maluos1`): `sudo apt update && sudo apt
full-upgrade -y` on each. And the office's own names must point at the
proxy ([10-office-configuration.md](10-office-configuration.md) §5b), or the
office cannot reach its own kernel over https for the join.

## 1. Mint the node codes at the office

Signed in as the super-admin at `https://os.$DOMAIN`: Settings → Estate →
mint a code, kind **server**, name `office`; then another, kind
**inference**, name `gpu-1`. Each code is shown once and is one-time. Or
from the shell:

```bash
cd /var/www
php bin/mint_desk_code.php --email "$ADMIN_EMAIL" --kind server --name office       # prints the code
php bin/mint_desk_code.php --email "$ADMIN_EMAIL" --kind inference --name gpu-1
```

Only an operator (a super-admin) mints a node code; a desk code (stage 5)
is minted for the person who owns the desk.

## 2. The office joins its own estate

As the hub, when the office has the port:

```bash
sudo maluctl estate join https://app.$DOMAIN --code <server code> --name office --hub vpn.$DOMAIN:51820
maluctl estate status             # joined, the node id, the heartbeat ok
maluctl estate overlay status     # interface estate up, 100.100.0.1/16 as office.internal, hub listening on udp 51820
```

As a spoke, when the GPU server will be the hub:

```bash
sudo maluctl estate join https://app.$DOMAIN --code <server code> --name office
maluctl estate overlay status     # a key was sent; no hub has joined yet (the service waits)
```

Either way:

```bash
maluctl estate inference          # the office's own facts (no GPU, nothing shared), the inference key stored
```

Expect at `os.$DOMAIN` → Settings → Estate: `office` online with its
report (CPU, memory, disk, no GPU), and an overlay paragraph naming the
hub and its endpoint, or "the hub has not joined yet".

## 3. The GPU server joins as an inference node

```bash
sudo maluctl estate join https://app.$DOMAIN --code <inference code> --name gpu-1 --kind inference                       # the office is the hub
sudo maluctl estate join https://app.$DOMAIN --code <inference code> --name gpu-1 --kind inference --hub gpu.$DOMAIN:51820   # or: this host is the hub
maluctl estate status             # joined
maluctl estate overlay status     # a spoke: 100.100.0.2/16 as gpu-1.internal, the hub's last handshake seconds ago;
                                  # or the hub: 100.100.0.1/16, listening on udp 51820, the office peered
ping -c 2 office.internal         # answers through the tunnel: the done-criterion of the proxy round
sudo maluctl gateway expose --bind overlay     # the node API and the faces on the overlay address only
maluctl gateway share status      # on (stage 3)
maluctl estate inference          # facts: share on, the models; peers: office
```

When the ping does not answer, `maluctl estate overlay status` on the
spoke says within two minutes that no handshake reached the hub and
names what to check; on the hub it asks whether the port is forwarded to
it. With the GPU host as the hub the addresses are the other way round:
the hub is `.0.1`, the office a spoke.

Three things the first run found (2026-11-07):

- Run `expose --bind overlay` only after the ping answers: before the
  node has its overlay address the command is refused, and a node that
  joined before the hub existed gets its address later, on its own. Its
  facts are published to the estate either way, so the office lists a
  backend it cannot reach until the expose is re-run.
- If the node runs `ufw`, the overlay interface is subject to it: open
  the gateway's port (and the memory face's, for stage 6) on it, or the
  office's probe times out:
  `sudo ufw allow in on estate to any port 11435 proto tcp` and the same
  for `11437`.
- `sudo maluctl estate heartbeat --report` pushes the facts now instead
  of at the next five-minute report.

Expect at the office: Settings → Estate lists `gpu-1` online, with its
GPU in the report; Settings → Estate → Shared inference lists `gpu-1`
published, shared, at its overlay address, with its models and expected
wait. The office's own gateway now holds a rung `estate:gpu-1`:

```bash
# on office (sudo: the host's node token is the vault's, not the login user's)
sudo maluctl estate inference --refresh # backends: gpu-1 at 100.100.0.2:11435 with its models
maluctl gateway estate                  # the rung estate:gpu-1, healthy
maluctl gateway chat "Say hello" --model qwen3:8b --prefer estate      # served by gpu-1 over the overlay
# on gpu-1
sudo maluctl gateway usage --since 10m  # the call under node:server:<office id>, with the origin request
```

That last pair is the whole point of the stage: a model call made on a
machine without a GPU, served by the machine with one, with the same
request id in both ledgers.

## 4. The office's agents use the GPU

The kernel's agent runner calls models through the office's gateway. With
the estate rung in place, an agent on a local model tier is served by
gpu-1. Register the local model in the kernel so an agent can be given it:
`os.$DOMAIN` → Settings → Models → add `qwen3:8b` on the gateway's
OpenAI-compatible endpoint (the gateway's socket is the runner's local
backend; the kernel's `model_registry` row names the harness). The
Anthropic models stay the default for the Installer and JEV agents.

## 5. Rules and the paid placement

Settings → Estate → Shared inference → Add rule: deny `kind:desk` on
gpu-1, and the desks of stage 5 lose the backend within a heartbeat;
remove it and it returns. The `scheduler` entitlement (a flag on the
kernel's settings row until editions exist) turns estate-wide placement
on; with it, `maluctl estate inference --refresh` on a member reports
`placement by the kernel` and the ledger rows carry `placement.reason`.
Leave it off except for the proof's one check.

## Done when

- Settings → Estate lists `office` and `gpu-1`, both online, with reports.
- `ping office.internal` answers on gpu-1 and `ping gpu-1.internal` on office.
- A chat on office with `--prefer estate` appears in gpu-1's ledger.

Next: [14-desks.md](14-desks.md).

## The proof (stage 6), once the desks are in

From `maluos/docs/phase13-three-machine-proof.md` steps 3 and 4, with
DocCloud added:

1. On a desk, `maluctl gateway chat "x" --model qwen3:8b --prefer estate`
   is served by gpu-1; gpu-1's ledger shows `node:desk:<id>`; the desk's
   System Monitor → MaluOS Network lists `estate:gpu-1` under Paired Nodes.
2. `sudo maluctl gateway share off` on gpu-1: the desk's next call is
   refused `not_shared`; `share on`: served.
3. A deny rule for `kind:desk` at the office removes the rung from the
   desk's gateway within five minutes (or at once with `maluctl office
   inference --refresh`); removing the rule restores it.
4. `--sensitivity restricted` on the desk's call is refused on the desk's
   side: `classification:restricted>internal`.
5. Delegation: on office, a Help Desk agent that accepts the organization
   (`sudo maluctl agent create helpdesk --exec … --scope org:read --tiers
   fast --capability helpdesk --accept-from org --max-classification
   internal`); on the desk, a personal agent (`sudo maluctl agent create
   me --personal --owner user:$USER`) sent "ask helpdesk to summarise the
   last customer complaint"; `maluctl estate tasks <id>` shows the chain
   `user > agent:me > agent:helpdesk` and the model call, served by gpu-1:
   three ledgers, one envelope id.
6. DocCloud: a document uploaded from a desk's browser is found by the
   DocCloud Expert from the command bar within a minute, and the
   Filing Clerk's Monday report (run it by hand from the agent's page)
   mentions it as untagged.

