# maluos-estate

A MaluOS host as a node of its estate: Phase 13 slice 1, the host half
(docs/phase13-slice1-nodes.md). The kernel half (maludb-os-core db/188 and
the `/api/v1/estate/*` endpoints) is a separate change; until it lands, the
mock office in this package serves the contract for tests.

- `lib/maluos_estate/client.py`: the HTTP client every desk and node speaks
  to its office (surface 1), the facts, the enrolment files, the estate
  endpoints. maluos-desk's `maluctl office` imports it.
- `lib/maluos_estate/report.py`: the report a node sends with its
  heartbeat; `maluctl estate report` prints it without an office.
- `lib/maluos_estate/__main__.py`: maluos-estated, the heartbeat daemon
  (`python3 -m maluos_estate`, maluos-estate.service as user maluos-estate).
- `lib/maluctl.d/estate.py`: `maluctl estate join|status|report|heartbeat|nodes|leave`.
- `lib/maluos_estate/mock_office.py`: the mock Business OS office (desks
  and the estate, the overlay contract); `python3 -m maluos_desk.mock_office`
  still names it.
- `lib/maluos_estate/overlay.py`: the estate's network on this host (slice
  1b, docs/phase13-slice1b-overlay.md): maluos-overlay.service, a root
  reconciler that makes the `estate` WireGuard interface from the join's
  overlay block and GET endpoints.overlay, peers the hub (or every spoke on
  the hub), keeps the names in /etc/hosts (NAME.internal), and
  `maluctl estate overlay status|peers|up|down|rotate|refresh`.

Identity: `join` makes the principal `host:<hostname>` (kind `service`:
the kernel's principal kinds are human, agent and service; a `host` kind
waits for the kernel half) and maps the system user maluos-estate to it in
`/etc/maluos/vault.yaml` and `/etc/maluos/gateway.yaml` (`identities`),
so the token and the key the daemon reads are in that principal's
compartment and the ledger names the host.

The overlay: `join` (and the desk's `office enroll`) makes an X25519 key, keeps
the private half in the vault (`estate-overlay-key`, beside the token), sends
the public half, and the office answers with the host's address, name and hub.
`join --hub HOST:PORT` on the coordinator's host makes it the hub (udp 51820,
forwarding on the interface only). `--no-overlay` opts a host out.
