"""Business OS navigation and action tools, generated from the action manifest.

`bin/build_action_registry.php` parses docs/business-os-action-manifest.md into
action_registry.json; this module turns that registry into the tools the assistant routes
through: `find_screen` and `navigate` over all 237 registered screens, and one action tool
per *built* action. An action whose endpoint does not exist yet is registered and findable
but never exposed as a tool, because a tool that would 404 is worse than no tool.

Nothing about routing lives in the assistant's system prompt: the tool descriptions carry it,
and they are written from the manifest's own words, so the document and the tool list cannot
drift.

This module deliberately does NOT use `from __future__ import annotations` — the generated
tools carry real model classes in __annotations__, which FastMCP resolves at registration.
"""

import difflib
import json
import pathlib
from typing import Optional, Union
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, create_model

REGISTRY_PATH = pathlib.Path(__file__).with_name("action_registry.json")
REGISTRY = json.loads(REGISTRY_PATH.read_text())
SCREENS: dict = REGISTRY["screens"]
ACTIONS: dict = REGISTRY["actions"]

RO = {"readOnlyHint": True, "openWorldHint": False}


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------
# Entity resolution: a param may carry a name, and the tool resolves it to an id.
# Each entry is (view, id column, label column) — all from this table, never from input.
# --------------------------------------------------------------------------
ENTITY_SOURCES = {
    "interaction": ("mcp_interactions", "interaction_id", "subject"),
    "member": ("mcp_team_directory", "member_id", "display_name"),
    "department": ("mcp_departments", "department_id", "name"),
    "pipeline": ("mcp_pipelines", "pipeline_id", "name"),
    "stage": ("mcp_pipelines", "stage_id", "stage_name"),
}

# Param name → the entity it names. Anything not here is passed through as typed.
PARAM_ENTITY = {
    "organization": "organization", "organization_id": "organization",
    "contact": "contact", "contact_id": "contact", "primary_contact_id": "contact",
    "deal": "deal", "deal_id": "deal",
    "interaction": "interaction",
    "member": "member", "owner_member_id": "member", "manager_member_id": "member",
    "approver": "member", "assignee": "member", "reviewer": "member", "owner": "member",
    "assign_member": "member", "assign_to": "member",   # forms: who a submission is routed to
    "department": "department", "department_id": "department", "parent_id": "department",
    "pipeline": "pipeline", "pipeline_id": "pipeline",
    "stage": "stage", "stage_id": "stage",
    "project": "project", "project_id": "project",
    "invoice": "invoice", "invoice_id": "invoice",
    "ticket": "ticket", "ticket_id": "ticket",
}

# `into` (a merge target) is the same kind of thing as the action's own record.
MERGE_TARGET_ENTITY = {"organization_merge": "organization", "contact_merge": "contact"}

# How each entity reads in a tool description and an error message.
ENTITY_LABEL = {
    "organization": "company", "contact": "person", "deal": "deal",
    "interaction": "logged conversation", "member": "person on the team",
    "department": "department", "pipeline": "pipeline", "stage": "pipeline stage",
    "project": "project", "invoice": "invoice", "ticket": "ticket",
}

# Words for the action's own subject and verb, so a generated description reads like English.
SUBJECT = {
    "organization": "a company", "contact": "a person", "deal": "a deal",
    "interaction": "a logged conversation (call, email, meeting, message or note)",
    "member": "a member's account", "module_grant": "a member's access to a module",
    "department": "a department", "department_member": "a department's membership",
    "business_settings": "the business settings", "pipeline": "a sales pipeline",
    "pipeline_stage": "a pipeline stage", "tag": "a tag on a record",
    "comment": "a note on a record", "invitation": "an invitation",
}
VERB = {
    "create": "Create", "add": "Add", "log": "Log", "update": "Change", "save": "Create or change",
    "set": "Set", "delete": "Delete", "remove": "Remove", "archive": "Archive (or restore)",
    "merge": "Merge", "revoke": "Revoke", "move": "Move", "mark": "Mark", "enable": "Enable",
    "set_primary": "Make primary", "set_role": "Change the role of", "move_stage": "Move to another stage",
    "mark_won": "Mark won", "mark_lost": "Mark lost", "add_member": "Add a member to",
    "remove_member": "Remove a member from", "set_status": "Set the status of",
}


def describe_action(action: dict) -> str:
    """The tool description: what it does, who may, what it costs, and how to end the turn."""
    name = action["action"]
    entity, _, verb = name.partition("_")
    subject = SUBJECT.get(entity, "a record")
    lead = VERB.get(verb) or VERB.get(verb.split("_")[0]) or "Perform"
    lines = [f"{lead} {subject}. Writes the activity event `{action['log_event']}`."]

    if action["who"]:
        lines.append(f"Allowed for: {action['who'].replace('`', '')} — the endpoint enforces it, "
                     f"so a caller without that access gets a refusal, not a change.")
    if action["confirm"]:
        lines.append("DESTRUCTIVE or irreversible: ask the user to confirm in your reply FIRST, "
                     "then call again with confirmed=true once they say yes.")
    if action["approval"]:
        lines.append(f"An approval policy may apply (category: {action['approval']}). If it does, the "
                     f"result is status=pending_approval, nothing changes, and you say it is waiting "
                     f"for approval.")
    if action["undo"]:
        lines.append(f"Undo: {action['undo']}.")
    lines.append("Do NOT call this to answer a question (use the record tools) or to move the user "
                 "(use navigate). After success, say what you did in ONE short sentence and END THE TURN.")
    return "\n".join(lines)


def param_description(action: dict, param: dict) -> str:
    """Field description, including how a name becomes an id."""
    entity = PARAM_ENTITY.get(param["name"])
    if param["name"] == "into":
        entity = MERGE_TARGET_ENTITY.get(action["action"])
    bits = []
    if entity:
        bits.append(f"The {ENTITY_LABEL.get(entity, entity)}: a name as the user said it, or its id. "
                    f"Never invent an id — a name that matches nothing, or matches several, comes back "
                    f"as an error listing the candidates.")
    if param["repeated"]:
        bits.append("Several values, comma-separated.")
    if param["hint"]:
        bits.append(param["hint"])
    if not bits:
        bits.append("As the user said it.")
    return " ".join(bits)


def register(mcp, app_post, resolve_one, current_member_id) -> None:
    """Attach the navigation and action tools.

    `app_post(path, fields)` POSTs to an app endpoint with the caller's action token;
    `resolve_one(sql, *args)` runs one member-scoped read; `current_member_id()` is the caller.
    """

    # find_screen and navigate — the command bar's two tools — retired with the bar in the kernel
    # cut of 2026-09-22. The registry's screens are still loaded (SCREENS) for describe_action.

    # ---- one tool per built action ---------------------------------------
    async def resolve_entity(entity: str, value: str) -> tuple[int | None, str]:
        """A name or an id → (id, label). Returns (None, message) when it cannot be settled."""
        view, id_column, label_column = ENTITY_SOURCES[entity]
        if str(value).isdigit():
            row = await resolve_one(f"SELECT {id_column} AS id, {label_column} AS label "
                                    f"FROM {view} WHERE {id_column} = $1", int(value))
            if row is None:
                return None, f"No {ENTITY_LABEL.get(entity, entity)} with id {value} that you can see."
            return int(row["id"]), str(row["label"])

        rows = await resolve_one(
            # DISTINCT: a view may hold a record on several rows (mcp_pipelines has one per stage),
            # and one record named twice is not an ambiguity.
            f"SELECT json_agg(t) AS matches FROM (SELECT DISTINCT {id_column} AS id, {label_column} AS label "
            f"FROM {view} WHERE {label_column} ILIKE $1 ORDER BY {label_column} LIMIT 6) t",
            f"%{value}%")
        matches = (rows or {}).get("matches") or []
        if not matches:
            return None, f"No {ENTITY_LABEL.get(entity, entity)} matching '{value}' that you can see."
        if len(matches) > 1:
            names = ", ".join(f"{m['label']} (id {m['id']})" for m in matches)
            return None, (f"Several match '{value}': {names}. Ask the user which one, "
                          f"or pass the id.")
        return int(matches[0]["id"]), str(matches[0]["label"])

    def make_tool(action: dict):
        fields: dict = {}
        for param in action["params"]:
            name = param.get("name")
            if not name or name in fields:
                continue
            description = param_description(action, param)
            # A model often passes an id as a number: take it, and send it on as text (str(value) below).
            if param["required"]:
                fields[name] = (Union[str, int, float], Field(..., description=description))
            else:
                fields[name] = (Optional[Union[str, int, float]], Field(None, description=description))
        if action["confirm"]:
            fields["confirmed"] = (bool, Field(False, description=(
                "Set true only after the user has explicitly agreed in this conversation. "
                "Calling without it returns a refusal telling you to ask first.")))

        model = create_model(
            "".join(part.title() for part in action["action"].split("_")) + "Input",
            __base__=_Base, **fields)

        endpoint = action["endpoint"]
        repeated = {p["name"] for p in action["params"] if p.get("repeated")}
        notes = [p["note"] for p in action["params"] if p.get("name") is None and p.get("note")]

        async def run(params) -> str:
            values = params.model_dump(exclude_none=True)

            if action["confirm"] and not values.pop("confirmed", False):
                return json.dumps({"status": "needs_confirmation", "message": (
                    f"{action['action']} is destructive or cannot be undone. Ask the user to confirm, "
                    f"then call again with confirmed=true.")})
            values.pop("confirmed", None)

            fields_out: dict = {}
            resolved: dict = {}

            # `entity` is whatever `entity_type` says it is (tags and notes attach to any
            # record), so its kind is only known at call time.
            dynamic_entity = None
            if "entity" in values and "entity_type" in values:
                dynamic_entity = str(values["entity_type"])

            for name, value in values.items():
                entity = PARAM_ENTITY.get(name)
                if name == "into":
                    entity = MERGE_TARGET_ENTITY.get(action["action"])
                if name == "entity" and dynamic_entity:
                    if str(value).strip().isdigit():
                        fields_out[name] = str(value).strip()     # an id is an id, whatever the kind
                        continue
                    if dynamic_entity not in ENTITY_SOURCES:
                        return json.dumps({"status": "error", "message": (
                            f"I cannot look up a '{dynamic_entity}' by name yet — pass its id.")})
                    entity = dynamic_entity
                if entity and entity in ENTITY_SOURCES:
                    record_id, label = await resolve_entity(entity, str(value))
                    if record_id is None:
                        return json.dumps({"status": "error", "message": label})
                    fields_out[name] = str(record_id)
                    resolved[name] = label
                elif name in repeated:
                    fields_out[name + "[]"] = [v.strip() for v in str(value).split(",") if v.strip()]
                else:
                    fields_out[name] = str(value)

            # An update sends the record and only what changes; PHP keeps the rest as it is
            # (app/partial_update.php). Without the mark the save handler reads a missing field
            # as "cleared", which is what a form's blank input means.
            if action.get("partial"):
                fields_out["_partial"] = "1"

            result = await app_post(endpoint, fields_out)
            if result.get("status") == "pending_approval" or (
                    isinstance(result.get("message"), str) and "pending_approval" in str(result)):
                result["status"] = "pending_approval"
            if resolved:
                result["resolved"] = resolved
            result.setdefault("action", action["action"])
            return json.dumps(result)

        run.__name__ = action["action"]
        run.__annotations__ = {"params": model, "return": str}
        description = describe_action(action)
        if notes:
            description += "\n" + " ".join(notes)
        mcp.add_tool(run, name=action["action"], description=description,
                     annotations={"title": action["action"].replace("_", " ").title(),
                                  "readOnlyHint": False,
                                  "destructiveHint": bool(action["confirm"])})

    for action in ACTIONS.values():
        if action["built"]:
            make_tool(action)


