# Agents as system entities (maluos-agent)

An agent on a MaluOS host is not a process with a borrowed key; it is a
system entity with the same shape a person has: a Linux user, a MaluDB
principal, a vault compartment, a gateway policy, and a unit that runs it.
`maluctl agent create` makes all of that in one step and `remove` reverses
it. Everything the vault and the gateway already enforce for people (peer-
credential identity, grants, class, tiers, cloud, egress ceiling, budget,
the ledger) applies to the agent without further configuration.

```
sudo maluctl agent create research \
    --exec "/opt/research/bin/run" \
    --scope dept:3:read --scope org:read \
    --tiers fast,standard --cloud yes --egress internal --budget usd_per_day=2 \
    --token --sandbox strict
sudo maluctl agent list
sudo maluctl agent show research
sudo maluctl agent logs research -f
sudo maluctl agent run research -- maluctl gateway chat "hello" --model fast
sudo maluctl agent remove research [--purge]
```

| Part | What `create` does |
|---|---|
| Linux user | `agent-NAME`, system account, no login, home /var/lib/maluos/agents/NAME (0750) |
| Principal | `agent:NAME` (kind agent, home scope `agent:NAME` or `--home`), scope grants from `--scope SCOPE:read|write` |
| Identity | `identities: {agent-NAME: agent:NAME}` in vault.yaml and gateway.yaml (both daemons reload on change) |
| Compartment | `agent:NAME`, owned by the agent; `maluctl secret` as the agent manages it; users delegate keys to it with `maluctl secret delegate` |
| Policy | a `maluos_policy` row for the principal: class (default `agent`), tiers, backends, cloud, egress, budget |
| Token | with `--token`, a gateway bearer token delivered to the unit as the credential `gateway-token` (for SDKs that need TCP; the socket needs none) |
| Unit | `maluos-agent@NAME.service`: runs `--exec` as the user with HOME in its directory and the MaluOS endpoints in the environment; hardened; `--sandbox strict` adds `IPAddressDeny=any` except localhost (a local-only agent: models through the gateway, memory through the listener, nothing else) |

The agent's environment: `MALUOS_AGENT`, `MALUOS_PRINCIPAL`,
`MALUOS_GATEWAY_SOCKET`, `MALUOS_VAULT_SOCKET`, `MALUDB_MC2DBD_URL`, and
`OPENAI_BASE_URL` / `OLLAMA_HOST` when the gateway's TCP listener is
enabled. A ledger row for a call from the unit carries
`process_ref = <comm>@maluos-agent@NAME.service`, so the audit trail names
the unit, not just the user.

`remove` stops and disables the unit, disables the principal (its history
stays in the ledger and in memory), revokes its gateway tokens, and drops
the identity mapping; `--purge` also deletes the user and its home.

The demo agent (/usr/lib/maluos/maluos-agent-demo.py) asks the gateway one
question through the socket as itself and then waits; the image boot test
creates an agent around it and checks every part above.

Not yet: polkit rules for agents that need to touch the system beyond the
sockets, bubblewrap or nspawn sandboxes for agents that run untrusted code,
and agent-specific resource limits. The unit template is the place for all
three.
