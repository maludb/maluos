"""Smoke harness for the actions MCP server (docs/react-cutover-runbook.md, the flip's step 2).

Connects the way the assistant does — streamable HTTP on 127.0.0.1:8813 with a signed action
token — and calls action tools. Every call WRITES, under the member the token names; the owner
authorised that on 2026-09-19 ("smoke tests can write to anything"). Records it creates are
named SMOKE so they can be told apart.

  venv/bin/python smoke_actions.py list                 # the tool surface
  venv/bin/python smoke_actions.py run <scenario.json>  # [{"tool":…, "args":{…}, "save":{…}}, …]
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "http://127.0.0.1:8813/mcp"


def mint_token(member_id: int) -> str:
    php = f'require "/var/www/app/bootstrap.php"; echo mint_action_token({member_id}, 3600);'
    return subprocess.run(["php", "-r", php], capture_output=True, text=True, check=True).stdout.strip()


async def session(member_id: int):
    headers = {"Authorization": f"Bearer {mint_token(member_id)}"}
    return streamablehttp_client(URL, headers=headers)


async def list_tools(member_id: int) -> None:
    async with await session(member_id) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            print(len(tools), "tools")
            for t in sorted(tools, key=lambda t: t.name):
                props = t.inputSchema.get("$defs", {})
                params = next(iter(props.values()), t.inputSchema) if props else t.inputSchema
                req = set(params.get("required", []))
                names = [("*" if k in req else "") + k for k in params.get("properties", {})]
                print(f"{t.name}({', '.join(names)})")


def fill(value, saved: dict):
    """{{name}} in a scenario argument is replaced by something an earlier step saved."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)          # the tools take every scalar as a string, as a form does
    if isinstance(value, str):
        for k, v in saved.items():
            value = value.replace("{{" + k + "}}", str(v))
        return value
    if isinstance(value, dict):
        return {k: fill(v, saved) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, saved) for v in value]
    return value


async def run(member_id: int, path: str) -> int:
    steps = json.load(open(path))
    # {{run}} makes every SMOKE name unique, so a name resolves to exactly one record.
    saved: dict = {"run": time.strftime("%m%d-%H%M%S"), "code": time.strftime("%H%M%S")[-3:]}
    failed = 0
    async with await session(member_id) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for i, step in enumerate(steps, 1):
                if "shell" in step:
                    # Something that happens OUTSIDE the agents' door between two calls — mail arriving, a
                    # timer firing. {"shell": "cmd with {{vars}}", "as": "www-data"?, "save": "name"?}
                    cmd = fill(step["shell"], saved)
                    done = subprocess.run((["sudo", "-n", "-u", step["as"]] if step.get("as") else []) + ["bash", "-c", cmd],
                                          capture_output=True, text=True, cwd="/var/www")
                    said = (done.stdout.strip() or done.stderr.strip()).split("\n")[-1][:300]
                    if step.get("save"):
                        saved[step["save"]] = said
                    print(f"{'     ' if done.returncode == 0 else 'FAIL '}{i:3} shell -> {said}")
                    failed += 0 if done.returncode == 0 else 1
                    continue
                if "lookup" in step:
                    # A create answers a sentence, not an id — so ids are read back, as postgres,
                    # from the base tables. {"lookup": {"org": "SELECT id FROM … WHERE name = '…'"}}
                    for name, sql in step["lookup"].items():
                        got = subprocess.run(["sudo", "-n", "-u", "postgres", "psql", "-d", "maludb_os", "-Atc", fill(sql, saved)],
                                             capture_output=True, text=True).stdout.strip().split("\n")[0]
                        saved[name] = got
                        print(f"     {i:3} lookup {name} = {got!r}")
                        if not got:
                            failed += 1
                            print(f"FAIL {i:3} lookup {name}: nothing found — steps that use it will be refused")
                    continue
                args = fill(step.get("args", {}), saved)
                # A variable that came back empty must never reach a tool: '' resolves by NAME and can match anything.
                empty = [k for k, v in step.get("args", {}).items() if isinstance(v, str) and "{{" in v and args.get(k) in ("", None)]
                if empty:
                    failed += 1
                    print(f"FAIL {i:3} {step['tool']:36} not called — no value for {', '.join(empty)}")
                    continue
                try:
                    res = await s.call_tool(step["tool"], {"params": args})
                    text = res.content[0].text if res.content else ""
                    try:
                        out = json.loads(text)
                    except ValueError:
                        out = {"status": "error" if res.isError else "?", "message": text[:300]}
                except Exception as ex:  # a transport or schema failure is a finding too
                    out = {"status": "exception", "message": str(ex)[:300]}
                want = step.get("expect", "success")
                ok = out.get("status") == want
                failed += 0 if ok else 1
                for name, key in (step.get("save") or {}).items():
                    if key in out:
                        saved[name] = out[key]
                brief = {k: v for k, v in out.items() if k not in ("refresh",)}
                print(f"{'ok  ' if ok else 'FAIL'} {i:3} {step['tool']:36} {json.dumps(brief)[:230]}")
    print(f"\n{len(steps) - failed}/{len(steps)} as expected; saved: {json.dumps(saved)}")
    return failed


if __name__ == "__main__":
    member = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    if sys.argv[1] == "list":
        asyncio.run(list_tools(member))
    else:
        sys.exit(1 if asyncio.run(run(member, sys.argv[2])) else 0)
