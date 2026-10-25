"""maluos_installer: the MaluOS installer engine (Phase 11 slice 2).

plan.py     the install plan: schema, defaults, references, redaction (docs/install-plan.md)
disks.py    what the machine has: disks, firmware, memory, the install medium
engine.py   runs the steps in order, keeps the journal, emits events, resumes
steps/      storage, unpack, configure, bootloader, finish: plan(ctx), check(ctx), apply(ctx), summary(ctx)
telemetry.py  the one report, built from facts and the journal, sent only when the plan says so
"""
VERSION = "0.3.2"
