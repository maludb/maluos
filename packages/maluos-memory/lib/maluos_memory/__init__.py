"""maluos-memory: the memory face of a MaluOS host (Phase 13 slice 4, docs/phase13-slice4-memory.md).

One service per host answers memory queries for local principals over a Unix socket and for the estate over the
overlay, binding every query to a principal and a scope set before the engine runs it (maludb-core's principal
scoping: maludb_core.principal_ref / principal_scopes / principal_readonly, transaction-local). The answer is claims,
never records: the memory's summary with its scope, sensitivity, confidence, time, source, writer and holder; the
payload stays on the host that owns it.
"""
VERSION = "0.1.3"
API_VERSION = 1
DEFAULT_PORT = 11437
SENSITIVITY = {"public": 0, "internal": 1, "restricted": 2, "prohibited": 3}
SCOPE_SHAREABLE = r"^(org|dept:[0-9]+)$"
