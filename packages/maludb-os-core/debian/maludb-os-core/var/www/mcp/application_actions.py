"""Action tools of applications from us (A7 (c) and (d), 2026-09-22).

An application from us ships an action manifest and the registry built from it; the installation
agent copies that registry here as mcp/registries/<app_key>.json with the application's internal
base URL, so every built action becomes a tool on the kernel's ONE Actions MCP — the one write
door: tool grants enforced at this boundary, an eval run's write recorded and never sent, the relay
key the agent must not hold, and — new here — the approval hook: an action with an approval
category asks the kernel (html/approvals/hook.php) before it is posted, so a matching policy pauses
it in the kernel's queue and a later approval replays it to the application's handler.

Entities are resolved through the application's OWN records MCP (`resolve` in the registry file):
a name in a param becomes an id by calling the application's find_* tool with the caller's token.

    {
      "schema": "maludb-os.registry/1",
      "app_key": "reservations", "name": "Reservations",
      "base_url": "http://127.0.0.1:8101",
      "records_url": "https://reservations.subello.com/mcp/records",
      "resolve": {"booking": {"tool": "find_bookings", "query_param": "q", "id_field": "booking_id",
                              "label_field": "title", "params": ["booking", "booking_id"]}},
      "registry": { ...the application's mcp/action_registry.json... }
    }

Tool names (K55, 2026-10-11; docs/build-specs/kernel-action-tool-names.md): every application's actions share this one server's
list of names. Each built action carries a `tool_name` the installer gives it (app/features/applications/action_tool_names.php):
its own action name when no other application and no kernel action uses it, else "<app_key>_<action>". The tool is served under
that name; the action's own name stays what the application, the approval hook and the log know it by. A registry written before
K55 has no tool names — bin/actions_tool_names.php gives them and moves the agents' grants.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote
import logging
import pathlib
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, create_model

log = logging.getLogger("actions.applications")
REGISTRIES_DIR = pathlib.Path(__file__).with_name("registries")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def load_registries() -> list[dict]:
    out = []
    if not REGISTRIES_DIR.is_dir():
        return out
    for path in sorted(REGISTRIES_DIR.glob("*.json")):
        try:
            reg = json.loads(path.read_text())
        except ValueError as exc:
            log.warning("registry %s is not JSON (%s) — skipped", path.name, exc)
            continue
        if not isinstance(reg.get("app_key"), str) or not isinstance(reg.get("base_url"), str) \
                or not isinstance((reg.get("registry") or {}).get("actions"), dict):
            log.warning("registry %s lacks app_key, base_url or registry.actions — skipped", path.name)
            continue
        reg["_file"] = path.name
        out.append(reg)
    return out


async def resolve_via_mcp(url: str, token: str, tool: str, params: dict) -> list[dict]:
    """One call of the application's find_* tool as the caller; the answer's rows."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(tool, {"params": params})
            text = res.content[0].text if res.content else ""
            rows = json.loads(text) if text else []
            if isinstance(rows, dict):
                # An application whose tools answer an envelope (cidery: {"count", "rows": [...]}, or candidates for an
                # ambiguous label) — the list inside is the answer.
                for key in ("rows", "candidates", "results", "items"):
                    if isinstance(rows.get(key), list):
                        return rows[key]
            return rows if isinstance(rows, list) else [rows]


def describe(action: dict, app_name: str) -> str:
    """The manifest's own words, as the kernel's factory writes them for its own actions (A7 c):
    the log event, who may, the undo, the confirm and approval rules, and the terminal sentence."""
    lines = [f"{action.get('description') or action['action']} — an action of {app_name} (logs {action.get('log_event') or action['action']})."]
    params = [p for p in action.get("params") or [] if p.get("name")]
    if params:
        lines.append("Fields: " + ", ".join(f"{p['name']}{' (required)' if p.get('required') else ''}" + (f" — {p['note']}" if p.get("note") else "") for p in params) + ".")
    notes = [p["note"] for p in action.get("params") or [] if not p.get("name") and p.get("note")]
    if notes:
        lines.append("Note: " + "; ".join(notes) + ".")
    if action.get("who"):
        lines.append(f"Allowed for: {action['who']} — the endpoint enforces it.")
    if action.get("confirm"):
        lines.append("Destructive or irreversible: call with confirmed=true only after the user agreed.")
    if action.get("approval"):
        lines.append(f"An approval policy may apply (category: {action['approval']}); if it does, the result is "
                     "status=pending_approval, nothing changes, and you say it is waiting for approval.")
    if action.get("undo"):
        lines.append(f"Undo: {action['undo']}.")
    if action.get("partial"):
        lines.append("Send the record and only what changes; the rest is kept.")
    lines.append("After success, say what you did in ONE short sentence and END THE TURN.")
    return "\n".join(lines)


def tool_name(action: dict) -> str:
    """The name a built action is served under: its registry's tool_name (K55), else the action's own name."""
    return str(action.get("tool_name") or action["action"])


def register(mcp, app_post, action_token, taken: set[str]) -> int:
    """Attach one tool per built action of every registry in mcp/registries/. `app_post(path,
    fields, base=)` posts as the caller; `action_token()` is the caller's token for resolution."""
    count = 0
    for reg in load_registries():
        base = reg["base_url"].rstrip("/")
        app_key, app_name = reg["app_key"], reg.get("name") or reg["app_key"]
        resolve_map: dict = reg.get("resolve") or {}
        param_entity = {p: ent for ent, spec in resolve_map.items() for p in (spec.get("params") or [ent])}
        records_url = reg.get("records_url")

        for action in reg["registry"]["actions"].values():
            if not action.get("built"):
                continue
            name = tool_name(action)
            if name in taken:
                # Never quietly: an agent granted this name would be handed another application's tool (K55). The registry
                # predates tool names, or was written by hand — `php bin/actions_tool_names.php plan` says what to change.
                log.error("%s: action '%s' would be served as '%s', which is already another tool's name — NOT registered; "
                          "run php bin/actions_tool_names.php plan", reg["_file"], action["action"], name)
                continue
            taken.add(name)
            _make_tool(mcp, app_post, action_token, action, base, app_key, app_name, param_entity, resolve_map, records_url)
            count += 1
    return count


def _make_tool(mcp, app_post, action_token, action: dict, base: str, app_key: str, app_name: str,
               param_entity: dict, resolve_map: dict, records_url: str | None) -> None:
    fields: dict = {}
    # Path parameters (2026-10-04, the cidery adoption): an endpoint written "/vessels/{vessel}/status" names the entity in its
    # path — the htmx-php-builder convention /{feature}/{id}/{verb}. Each {name} is a required parameter, resolved like any
    # other entity, substituted into the path and not posted as a field.
    path_params = re.findall(r"\{([a-z][a-z0-9_]*)\}", str(action.get("endpoint") or ""))
    for pname in path_params:
        hint = next((p.get("note") or p.get("hint") or "" for p in (action.get("params") or []) if p.get("name") == pname), "")
        fields[pname] = (str, Field(..., description=hint or f"the {pname.replace('_', ' ')}"))
    for param in action.get("params") or []:
        pname = param.get("name")
        if not pname or pname in fields:
            continue
        note = param.get("note") or param.get("hint") or ""
        fields[pname] = (str, Field(..., description=note)) if param.get("required") else (Optional[str], Field(None, description=note))
    if action.get("confirm"):
        fields["confirmed"] = (bool, Field(False, description="Set true only after the user has explicitly agreed in this conversation."))
    model = create_model(f"{app_key.title()}{''.join(p.title() for p in action['action'].split('_'))}Input", __base__=_Base, **fields)
    endpoint = action["endpoint"] if str(action["endpoint"]).startswith("/") else "/" + str(action["endpoint"])
    repeated = {p["name"] for p in (action.get("params") or []) if p.get("repeated")}

    async def run(params) -> str:
        values = params.model_dump(exclude_none=True)
        if action.get("confirm") and not values.pop("confirmed", False):
            return json.dumps({"status": "needs_confirmation", "message": (
                f"{action['action']} is destructive or cannot be undone. Ask the user to confirm, then call again with confirmed=true.")})
        values.pop("confirmed", None)
        fields_out: dict = {}
        resolved: dict = {}
        for pname, value in values.items():
            entity = param_entity.get(pname)
            spec = resolve_map.get(entity) if entity else None
            if spec and records_url and not str(value).isdigit():
                try:
                    rows = await resolve_via_mcp(records_url, action_token() or "", spec["tool"], {spec.get("query_param", "q"): str(value)})
                except Exception as exc:      # noqa: BLE001
                    return json.dumps({"status": "error", "message": f"Could not look up '{value}' in {app_name}: {exc}"})
                id_field, label_field = spec.get("id_field", f"{entity}_id"), spec.get("label_field", "name")
                matches = [r for r in rows if isinstance(r, dict) and r.get(id_field) is not None]
                if not matches:
                    return json.dumps({"status": "error", "message": f"No {entity} matching '{value}' in {app_name} that you can see."})
                if len(matches) > 1:
                    names = ", ".join(f"{m.get(label_field)} (id {m[id_field]})" for m in matches[:6])
                    return json.dumps({"status": "error", "message": f"Several match '{value}': {names}. Ask the user which one, or pass the id."})
                fields_out[pname] = str(matches[0][id_field])
                resolved[pname] = str(matches[0].get(label_field, matches[0][id_field]))
            elif pname in repeated:
                fields_out[pname + "[]"] = [v.strip() for v in str(value).split(",") if v.strip()]
            else:
                fields_out[pname] = str(value)
        if action.get("partial"):
            fields_out["_partial"] = "1"
        for key, value in (action.get("fixed") or {}).items():       # a manifest row that fixes a field ("state (event=clean)")
            fields_out.setdefault(key, str(value))
        path = endpoint
        for pname in path_params:
            value = fields_out.pop(pname, None)
            if value is None or value == "":
                return json.dumps({"status": "error", "message": f"{pname} is required for {action['action']}."})
            path = path.replace("{" + pname + "}", quote(str(value), safe=""))

        # The approval hook: the kernel decides before the application is asked.
        if action.get("approval"):
            gate = await app_post("/approvals/hook.php", {
                "action_key": action["action"], "log_event": action.get("log_event") or action.get("log") or action["action"],
                "summary": f"{action['action'].replace('_', ' ')} in {app_name}",
                "parameters": json.dumps(fields_out), "body": json.dumps(fields_out),
                "handler_url": base + path,
                "amount": fields_out.get("amount", ""), "currency": fields_out.get("currency", ""),
            })
            if gate.get("status") == "pending_approval":
                gate.update({"application": app_key, "action": action["action"]})
                if resolved:
                    gate["resolved"] = resolved
                return json.dumps(gate)
            if gate.get("status") not in ("success", "recorded"):
                gate.setdefault("message", "The approval check could not be made; nothing was changed.")
                return json.dumps({**gate, "status": "error", "application": app_key, "action": action["action"]})
            if gate.get("status") == "recorded":        # an evaluation: the hook itself was not sent; nor is the action
                return json.dumps({**gate, "would_have_called": base + endpoint, "application": app_key, "action": action["action"]})

        result = await app_post(path, fields_out, base=base)
        if result.get("status") == "pending_approval" or (isinstance(result.get("message"), str) and "pending_approval" in str(result)):
            result["status"] = "pending_approval"
        if resolved:
            result["resolved"] = resolved
        result.setdefault("action", action["action"])
        result["application"] = app_key
        return json.dumps(result)

    run.__name__ = tool_name(action)
    run.__annotations__ = {"params": model, "return": str}
    mcp.add_tool(run, name=tool_name(action), description=describe(action, app_name),
                 annotations={"title": f"{app_name}: {action['action'].replace('_', ' ')}", "readOnlyHint": False,
                              "destructiveHint": bool(action.get("confirm"))})
