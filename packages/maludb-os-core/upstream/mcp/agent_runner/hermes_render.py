"""Render one agent's Hermes profile from its ACTIVE config version. Deterministic: the same
version renders the same bytes, and sha256 of them is agent_runs.profile_hash.

Every setting here is one the H0 conformance suite proved necessary
(mcp/hermes_conformance/README.md, "Settings the profile renderer must always write"). Secrets
are never written: the file holds ${BOS_*} references and the values exist only in the Hermes
process environment.

config.yaml is written as JSON — JSON is YAML, and it needs no YAML library in the runner.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import config
from .persona import PREAMBLE, handbook_block, org_block

PROVIDER_NAME = "bos-ledger"


def server_slug(endpoint_name: str) -> str:
    """'Records MCP' -> 'records'. Hermes names tools mcp__<slug>__<tool> and takes the bare slug
    in -t (H0: 'mcp-<slug>' is rejected by one-shot mode)."""
    slug = re.sub(r"[^a-z0-9]+", "_", endpoint_name.lower().replace(" mcp", "")).strip("_")
    return slug or "endpoint"


def render(agent: dict, aux_tasks: list[str], agent_dir: Path, memory_block: str = "") -> dict:
    """Returns {soul, config, toolsets, warnings, hash}; writes nothing.

    agent_dir/ holds hermes/ (HERMES_HOME: config, persona, Hermes' own state.db and logs),
    outbox/ (where an agent-authored skill lands), cwd/ and home/ (the process's scratch dirs)."""
    model, runtime, warnings = agent["model"], agent.get("runtime_config") or {}, []
    wire = config.PROVIDERS.get(model["provider"], ("", "", "openai"))[2]
    proxy = f"http://127.0.0.1:{config.PROXY_PORT}"
    model_id = model["provider_model_id"]

    if runtime.get("native_toolsets"):
        warnings.append("runtime_config.native_toolsets is ignored: native Hermes toolsets need the docker "
                        "terminal backend, which this host does not have.")

    servers, toolsets = {}, ["skills"]      # 'skills' writes only to the outbox; never an empty -t (that means ALL)
    for ep in agent["endpoints"]:
        # The run token is the credential on the kernel's endpoints AND on those of an application from
        # us (A7 (a), 2026-09-22): both verify it with the tenant's key. Anyone else's endpoint would
        # need a tenant secret, which no agent is handed.
        if ep["auth_kind"] != "bearer" or (ep["app_key"] != "platform" and ep.get("catalog_kind") != "ours"):
            warnings.append(f"Endpoint '{ep['name']}' was skipped: external credentials need tenant_secrets.")
            continue
        slug = server_slug(ep["name"])
        servers[slug] = {"url": ep["url"],
                         "headers": {"Authorization": "Bearer ${BOS_RUN_TOKEN}"},
                         "tools": {"include": sorted(ep["tools"]), "resources": False, "prompts": False}}
        toolsets.append(slug)

    aux = {task: {"base_url": f"{proxy}/openai/v1", "api_key": "${BOS_PROXY_KEY}", "model": model_id}
           for task in sorted(aux_tasks)}
    aux.setdefault("title_generation", {})["enabled"] = False      # a title for a duty run is a wasted call

    cfg = {
        "model": {"default": model_id, "provider": f"custom:{PROVIDER_NAME}"},
        "providers": {PROVIDER_NAME: {
            "api": f"{proxy}/anthropic" if wire == "anthropic" else f"{proxy}/openai/v1",
            "key_env": "BOS_PROXY_KEY",
            "transport": "anthropic_messages" if wire == "anthropic" else "chat_completions",
            "default_model": model_id,
            **({"context_length": model["context_window_tokens"]} if model.get("context_window_tokens") else {}),
        }},
        "auxiliary": aux,
        "mcp_servers": servers,
        "tools": {"tool_search": {"enabled": False}},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "plugins": {"enabled": ["bos-hermes"]},
        "skills": {"external_dirs": [str(agent_dir / "skills")], "create_dir": str(agent_dir / "outbox")},
        "curator": {"enabled": False},
        "updates": {"check": False},
        "approvals": {"mode": "manual", "single_query_mode": "deny", "unattended_mode": "deny", "cron_mode": "deny"},
        "agent": {k: v for k, v in {"max_turns": runtime.get("max_turns")}.items() if v},
    }
    soul = PREAMBLE.format(
        name=agent["display_name"], title=f" as {agent['job_title']}" if agent.get("job_title") else "",
        departments=", ".join(agent["departments"]) or "no department yet",
        manager=agent.get("manager_name") or "not recorded") + (agent.get("job_description") or "").strip() + "\n"
    # The handbook is part of what the agent was configured with, so it is inside the hash: a run
    # whose profile_hash differs on the same version says the handbook (or a grant) changed.
    handbook, handbook_warnings = handbook_block(agent.get("handbooks") or [])
    soul += handbook
    warnings += handbook_warnings
    soul += org_block(agent.get("org"))            # its place in the orchestrator tree (db/154-155)
    config_text = json.dumps(cfg, indent=1, sort_keys=True) + "\n"
    digest = hashlib.sha256((soul + "\0" + config_text + "\0" + ",".join(toolsets)).encode()).hexdigest()
    # The hash identifies the CONFIGURATION. Core memory is added after it: an agent learning
    # something must not look like a configuration change.
    soul += memory_block
    return {"soul": soul, "config": config_text, "toolsets": toolsets, "warnings": warnings, "hash": digest}


def write(agent_dir: Path, rendered: dict) -> Path:
    """The agent's unix user (group bos-agent) must be able to write Hermes' own state — state.db,
    logs, caches, the outbox — and must NOT be able to change what the platform decided: its
    persona, its config, its skills. Directories are group-writable with the STICKY bit, so the
    agent can create and remove its own files but cannot rename or replace the runner's; the two
    rendered files are group-readable only. (They are re-rendered before every run regardless.)"""
    import os
    agent_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(agent_dir, 0o3770)
    for sub in ("hermes", "outbox", "cwd", "home"):
        (agent_dir / sub).mkdir(parents=True, exist_ok=True)
        os.chmod(agent_dir / sub, 0o3770)
    for name, text in (("SOUL.md", rendered["soul"]), ("config.yaml", rendered["config"])):
        path = agent_dir / "hermes" / name
        if path.exists():
            path.unlink()                       # ours to replace even if a previous run's mode differed
        path.write_text(text, encoding="utf-8")
        os.chmod(path, 0o640)
    return agent_dir / "hermes"
