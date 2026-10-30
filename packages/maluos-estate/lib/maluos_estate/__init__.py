"""maluos_estate: a MaluOS host as a node of its estate (Phase 13 slice 1, docs/phase13-slice1-nodes.md).

client   the HTTP client, the enrolment files and the estate endpoints (join, heartbeat, me, leave, nodes)
report   what a node reports with its heartbeat: units, agents, the gateway, vault alerts, updates, disk, memory, load
__main__ maluos-estated, the heartbeat daemon (python3 -m maluos_estate)
mock_office  the mock Business OS office for tests: desks (Phase 12 slice 6) and the estate (this slice)
"""
VERSION = "0.4.0"
