"""An agent's skills, in and out (docs/build-specs/agent-skills.md).

  down   before a run: resolve the agent's skill set from skill_assignments (most specific wins:
         agent > role > department > application > org; runtime_config.pinned_skills overrides all), fetch what
         changed from MaluDB, write it under <agent_dir>/skills/ — owned by the runner, readable and
         NOT writable by the agent's unix user. Hermes reads it through skills.external_dirs; its own
         docs say that setting is not a protection boundary, so the filesystem is.
  up     after a run: every folder in <agent_dir>/outbox/ that holds a SKILL.md is posted to PHP
         (html/skills/propose.php), which scans it, ingests it DISABLED and queues it for a person.

A skill that cannot be fetched is a warning, never a failed run.
"""
from __future__ import annotations

import base64
import logging
import os
import shutil
from pathlib import Path

import httpx

from . import config, store

log = logging.getLogger("agent_runner.skills")
SPECIFICITY = {"agent": 0, "role": 1, "department": 2, "application": 3, "org": 4}
MAX_OUTBOX_FILE = 262144


def choose(assignments: list[dict], pinned: list[dict] | None) -> dict[str, str | None]:
    """{skill_name: bundle_hash | None}. The most specific live assignment of a name wins;
    runtime_config.pinned_skills ([{name, bundle_hash}]) overrides every assignment."""
    chosen: dict[str, tuple[int, str | None]] = {}
    for a in assignments:
        rank = SPECIFICITY[a["scope_kind"]]
        if a["skill_name"] not in chosen or rank < chosen[a["skill_name"]][0]:
            chosen[a["skill_name"]] = (rank, a.get("pinned_bundle_hash"))
    out = {name: pin for name, (_, pin) in chosen.items()}
    for p in pinned or []:
        if isinstance(p, dict) and p.get("name"):
            out[str(p["name"])] = p.get("bundle_hash")
    return out


def _safe(path: str) -> bool:
    return bool(path) and not path.startswith("/") and ".." not in path.split("/") and "\\" not in path


async def sync_down(agent: dict, agent_dir: Path) -> tuple[list[dict], list[str]]:
    """Returns (snapshot for agent_runs.skills, warnings)."""
    root, snapshot, warnings = agent_dir / "skills", [], []
    root.mkdir(parents=True, exist_ok=True)
    _lock_down(root, agent_dir.stat().st_gid)
    wanted = choose(await store.skill_assignments_for(agent), (agent.get("runtime_config") or {}).get("pinned_skills"))
    url, token = config.get("MALUDB_API_URL"), config.get("MALUDB_API_TOKEN")
    if wanted and not (url and token):
        return [], ["Skills are assigned but MaluDB is not configured for the runner."]

    async with httpx.AsyncClient(base_url=url or "http://invalid", headers={"Authorization": f"Bearer {token}"}, timeout=30.0) as api:
        for name, pin in sorted(wanted.items()):
            try:
                r = await api.get("/v1/skills/resolve", params={"name": name, **({"bundle_hash": pin} if pin else {})})
                if r.status_code == 404:
                    warnings.append(f"Skill '{name}'{' at the pinned version' if pin else ''} is not in MaluDB (or is disabled); skipped.")
                    continue
                r.raise_for_status()
                skill = r.json()["skill"]
                target, marker = root / name, root / name / ".bundle_hash"
                if not (marker.exists() and marker.read_text().strip() == skill["bundle_hash"]):
                    listing = (await api.get(f"/v1/skills/{skill['id']}/files")).json()["files"]
                    fresh = root / f".{name}.new"
                    shutil.rmtree(fresh, ignore_errors=True)
                    for f in listing:
                        if not _safe(f["relative_path"]):
                            raise ValueError(f"unsafe path {f['relative_path']!r}")
                        body = (await api.get(f"/v1/skills/{skill['id']}/files/{f['relative_path']}")).json()["file"]
                        dest = fresh / f["relative_path"]
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(base64.b64decode(body["content_base64"]))
                    (fresh / ".bundle_hash").write_text(skill["bundle_hash"] + "\n")
                    shutil.rmtree(target, ignore_errors=True)
                    fresh.rename(target)
                _lock_down(target, agent_dir.stat().st_gid)
                snapshot.append({"name": name, "maludb_skill_id": skill["id"], "bundle_hash": skill["bundle_hash"],
                                 "version": skill.get("version"), "pinned": bool(pin)})
            except Exception as exc:
                log.warning("skill %s not synced for agent %s", name, agent["member_id"], exc_info=True)
                warnings.append(f"Skill '{name}' could not be fetched: {exc}")

    keep = {s["name"] for s in snapshot}
    for entry in root.iterdir():                      # no longer assigned (or failed this time): gone from the run
        if entry.is_dir() and entry.name not in keep:
            shutil.rmtree(entry, ignore_errors=True)
    return snapshot, warnings


def _lock_down(tree: Path, gid: int) -> None:
    """Runner-owned; the AGENT's group may read and never write; nothing is executable. The group
    is set explicitly: chmod without the setgid bit drops inheritance, and files that land in the
    runner's own group are unreadable to the agent — Hermes then reports "no skills" and says why
    nowhere."""
    for path in [tree, *tree.rglob("*")]:
        os.chown(path, -1, gid)
        os.chmod(path, 0o2750 if path.is_dir() else 0o640)


def collect_outbox(outbox: Path) -> list[tuple[str, Path, list[dict]]]:
    """[(skill_name, folder, files)] for every outbox folder holding a SKILL.md."""
    found = []
    if not outbox.is_dir():
        return found
    for skill_md in sorted(outbox.rglob("SKILL.md")):
        folder, files = skill_md.parent, []
        for f in sorted(p for p in folder.rglob("*") if p.is_file()):
            if f.stat().st_size > MAX_OUTBOX_FILE:
                continue                              # PHP's scan would refuse the bundle anyway; do not read megabytes to find out
            files.append({"relative_path": str(f.relative_to(folder)), "content_base64": base64.b64encode(f.read_bytes()).decode()})
        found.append((folder.name, folder, files))
    return found


async def sync_up(run_id: int, agent_dir: Path) -> list[str]:
    """Post each outbox skill to PHP. Returns event messages. The folder is removed once PHP has an
    answer about it — proposed, unchanged or refused; only an unreachable PHP leaves it for next time."""
    import json
    messages = []
    for name, folder, files in collect_outbox(agent_dir / "outbox"):
        try:
            async with httpx.AsyncClient(base_url=config.PHP_BASE, timeout=60.0) as client:
                r = await client.post("/skills/propose.php", headers={"X-Runner-Key": config.require("RUNNER_KEY", 32)},
                                      data={"agent_run": run_id, "skill_name": name, "files": json.dumps(files)})
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code == 201:
                messages.append(f"The agent wrote a skill, '{name}'. It is held for review as proposal #{body.get('skill_proposal_id')}.")
            elif body.get("unchanged"):
                messages.append(f"The agent re-wrote skill '{name}' unchanged; nothing to review.")
            elif body.get("refused"):
                messages.append(f"The agent's skill '{name}' was refused: {body.get('error')}")
            else:
                messages.append(f"The agent's skill '{name}' could not be proposed ({r.status_code}): {body.get('error')}")
                if r.status_code >= 500 or r.status_code == 424:
                    continue                          # keep the folder: try again after the next run
            shutil.rmtree(folder, ignore_errors=True)
        except Exception as exc:
            log.warning("run %s: skill %s not proposed", run_id, name, exc_info=True)
            messages.append(f"The agent's skill '{name}' could not be proposed: {exc}")
    return messages
