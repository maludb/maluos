"""The agent runner: one agent, one unit of work, everything recorded.

Spec: docs/build-specs/agent-runtime-hermes.md. A harness (Hermes first) sits behind one
interface; every model call it makes passes through the ledger proxy in this same process.
"""
