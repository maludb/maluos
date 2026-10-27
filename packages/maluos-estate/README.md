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
  and the estate); `python3 -m maluos_desk.mock_office` still names it.

Identity: `join` makes the principal `host:<hostname>` (kind `service`:
the kernel's principal kinds are human, agent and service; a `host` kind
waits for the kernel half) and maps the system user maluos-estate to it in
`/etc/maluos/vault.yaml` and `/etc/maluos/gateway.yaml` (`identities`),
so the token and the key the daemon reads are in that principal's
compartment and the ledger names the host.
