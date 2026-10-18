"""Tests for the runner's pure parts. Standard library only:
    cd mcp && ./venv/bin/python -m unittest agent_runner.tests.test_runner -v
The end-to-end path is covered by mcp/hermes_conformance and the H2 acceptance runs."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import unittest
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("RUNNER_ENV_FILE", "/nonexistent")
from agent_runner import hermes_render, pricing, run_token          # noqa: E402
from agent_runner import claude_launch, config                        # noqa: E402
from agent_runner.ledger_proxy import _Assembler, _upstream          # noqa: E402

KEY = "k" * 40


class RunTokens(unittest.TestCase):
    def test_run_token_is_what_mcp_db_verifies(self):
        token = run_token.mint_run_token(44, 7, 600, KEY)
        mid, exp, run, sig = token.split(".")
        self.assertEqual((mid, run), ("44", "7"))
        self.assertEqual(sig, hmac.new(KEY.encode(), f"run:{mid}.{exp}.{run}".encode(), hashlib.sha256).hexdigest())

    def test_run_token_verifies_in_the_servers_module(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        try:
            import db
        except Exception as exc:                       # config/.env unreadable for this user
            self.skipTest(f"mcp/db.py not importable here: {exc}")
        db.ENV["ACTION_TOKEN_KEY"] = KEY
        self.assertEqual(db.verify_run_token(run_token.mint_run_token(44, 7, 600, KEY)), (44, 7))
        self.assertEqual(db.verify_action_token(run_token.mint_run_token(44, 7, 600, KEY)), 44)
        self.assertIsNone(db.verify_run_token(run_token.mint_run_token(44, 7, -5, KEY)), "expired")
        self.assertIsNone(db.verify_run_token(run_token.mint_run_token(44, 7, 600, "x" * 40)), "wrong key")
        db.ENV["ACTION_TOKEN_KEY"] = ""
        self.assertIsNone(db.verify_run_token(run_token.mint_run_token(44, 7, 600, KEY)), "unset key verifies nothing")

    def test_a_short_key_is_refused(self):
        with self.assertRaises(RuntimeError):
            run_token.mint_run_token(1, 1, 60, "short")

    def test_proxy_key_round_trip(self):
        key = run_token.mint_proxy_key(12, 600, KEY)
        self.assertEqual(run_token.verify_proxy_key(key, KEY), 12)
        self.assertEqual(run_token.verify_proxy_key("Bearer " + key, KEY), 12)
        self.assertIsNone(run_token.verify_proxy_key(key, "y" * 40))
        self.assertIsNone(run_token.verify_proxy_key(run_token.mint_proxy_key(12, -1, KEY), KEY))
        forged = key.replace("run.12.", "run.13.")
        self.assertIsNone(run_token.verify_proxy_key(forged, KEY), "the run id is inside the signature")

    def test_a_run_token_is_not_a_proxy_key(self):
        self.assertIsNone(run_token.verify_proxy_key(run_token.mint_run_token(44, 7, 600, KEY), KEY))


class Pricing(unittest.TestCase):
    MODEL = {"price_input_per_mtok": "10", "price_output_per_mtok": "50",
             "price_cache_read_per_mtok": "1", "price_cache_write_per_mtok": "12.5"}

    def test_cost_reconciles_to_registry_prices(self):
        tokens = pricing.normalise_usage("openai", {"prompt_tokens": 7822, "completion_tokens": 14})
        self.assertEqual(pricing.cost(tokens, self.MODEL), Decimal("0.078920"))

    def test_openai_cached_tokens_are_not_counted_twice(self):
        tokens = pricing.normalise_usage("openai", {"prompt_tokens": 1000, "completion_tokens": 0,
                                                    "prompt_tokens_details": {"cached_tokens": 400}})
        self.assertEqual((tokens["input"], tokens["cache_read"]), (600, 400))

    def test_deepseek_reports_cache_hits_under_its_own_names(self):
        newer = pricing.normalise_usage("openai", {"prompt_tokens": 1000, "completion_tokens": 50, "prompt_tokens_details": {
            "cached_tokens": 800, "prompt_cache_hit_tokens": 800, "prompt_cache_miss_tokens": 200}})
        older = pricing.normalise_usage("openai", {"prompt_tokens": 1000, "completion_tokens": 50,
                                                   "prompt_cache_hit_tokens": 800, "prompt_cache_miss_tokens": 200})
        self.assertEqual(newer, {"input": 200, "output": 50, "cache_read": 800, "cache_write": 0})
        self.assertEqual(older, newer)                       # and never 1600: the two names are one number
        flash = {"price_input_per_mtok": "0.3", "price_output_per_mtok": "1.2", "price_cache_read_per_mtok": "0.006"}
        self.assertEqual(pricing.cost(newer, flash), Decimal("0.000125"))

    def test_anthropic_counters(self):
        tokens = pricing.normalise_usage("anthropic", {"input_tokens": 10, "output_tokens": 5,
                                                       "cache_read_input_tokens": 100, "cache_creation_input_tokens": 200})
        self.assertEqual(tokens, {"input": 10, "output": 5, "cache_read": 100, "cache_write": 200})
        self.assertEqual(pricing.cost(tokens, self.MODEL), Decimal("0.002950"))


class Render(unittest.TestCase):
    AGENT = {"member_id": 44, "display_name": "Sasha", "job_title": "AP processor", "departments": ["Accounting"],
             "manager_name": "Edward", "job_description": "You are the ap processor", "runtime_config": {},
             "model": {"provider": "anthropic", "provider_model_id": "claude-x", "context_window_tokens": 200000},
             "endpoints": [{"name": "Records MCP", "url": "http://localhost/mcp/records", "auth_kind": "bearer",
                            "app_key": "platform", "tools": ["find_contacts", "find_agents"]},
                           {"name": "QuickBooks", "url": "https://qb.example/mcp", "auth_kind": "oauth",
                            "app_key": "quickbooks", "tools": ["post_bill"]}]}

    def render(self, **over):
        return hermes_render.render({**self.AGENT, **over}, ["compression", "title_generation", "vision"],
                                    Path("/var/lib/business-os/agents/44"))

    def test_no_secret_is_ever_rendered(self):
        r = self.render()
        self.assertIn("${BOS_RUN_TOKEN}", r["config"])
        self.assertIn("${BOS_PROXY_KEY}", r["config"])
        self.assertNotRegex(r["config"] + r["soul"], r"[0-9a-f]{64}")

    def test_every_model_slot_points_at_the_proxy(self):
        cfg = json.loads(self.render()["config"])
        self.assertEqual(cfg["providers"]["bos-ledger"]["transport"], "anthropic_messages")
        self.assertTrue(cfg["providers"]["bos-ledger"]["api"].endswith(":8816/anthropic"))
        for task, slot in cfg["auxiliary"].items():
            self.assertTrue(slot["base_url"].endswith(":8816/openai/v1"), task)
        self.assertIs(cfg["auxiliary"]["title_generation"]["enabled"], False)

    def test_the_tool_surface_is_the_grants_and_nothing_else(self):
        r = self.render()
        cfg = json.loads(r["config"])
        self.assertEqual(r["toolsets"], ["skills", "records"])
        self.assertEqual(cfg["mcp_servers"]["records"]["tools"],
                         {"include": ["find_agents", "find_contacts"], "resources": False, "prompts": False})
        self.assertIs(cfg["tools"]["tool_search"]["enabled"], False)
        self.assertEqual(cfg["memory"], {"memory_enabled": False, "user_profile_enabled": False})
        self.assertNotIn("quickbooks", cfg["mcp_servers"])
        self.assertTrue(any("QuickBooks" in w for w in r["warnings"]))

    def test_an_agent_with_no_grants_never_gets_an_empty_allow_list(self):
        self.assertEqual(self.render(endpoints=[])["toolsets"], ["skills"])     # empty -t would mean ALL toolsets

    def test_rendering_is_deterministic_and_the_hash_follows_the_content(self):
        self.assertEqual(self.render()["hash"], self.render()["hash"])
        self.assertNotEqual(self.render()["hash"], self.render(job_description="Something else")["hash"])

    HANDBOOK = {"department_id": 3, "department_name": "Accounting", "document_id": 9,
                "title": "How Accounting works", "body_markdown": "Bills are filed the day they arrive."}

    def test_the_department_handbook_is_in_the_persona_and_in_the_hash(self):
        r = self.render(handbooks=[self.HANDBOOK])
        self.assertIn("# Your department's handbook", r["soul"])
        self.assertIn("## Accounting: How Accounting works", r["soul"])
        self.assertIn("Bills are filed the day they arrive.", r["soul"])
        self.assertLess(r["soul"].index("# Your job description"), r["soul"].index("# Your department's handbook"))
        self.assertNotEqual(r["hash"], self.render()["hash"])
        self.assertNotIn("handbook", self.render()["soul"])                 # none written: no empty section

    def test_one_handbook_serving_two_departments_is_rendered_once_and_a_long_one_is_cut(self):
        twice = self.render(handbooks=[self.HANDBOOK, {**self.HANDBOOK, "department_id": 4, "department_name": "Audit"}])
        self.assertEqual(twice["soul"].count("Bills are filed"), 1)
        long = self.render(handbooks=[{**self.HANDBOOK, "body_markdown": "x" * 20000}])
        self.assertLess(len(long["soul"]), 14000)
        self.assertIn("[The handbook continues", long["soul"])
        self.assertTrue(any("longer than" in w for w in long["warnings"]))

    def test_native_toolsets_are_refused_with_a_warning(self):
        r = self.render(runtime_config={"native_toolsets": ["terminal"]})
        self.assertNotIn("terminal", r["toolsets"])
        self.assertTrue(any("native_toolsets" in w for w in r["warnings"]))


class Assembler(unittest.TestCase):
    def test_openai_stream_split_across_chunks(self):
        a = _Assembler("openai")
        stream = (b'data: {"id":"c1","choices":[{"delta":{"role":"assistant"}}]}\n\n'
                  b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"t1","function":{"name":"find","arguments":""}}]}}]}\n\n'
                  b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"a\\":1}"}}]}}]}\n\n'
                  b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
                  b'data: {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":3}}\n\ndata: [DONE]\n\n')
        for i in range(0, len(stream), 17):
            a.feed(stream[i:i + 17])
        m = a.message()
        self.assertEqual(m["tool_calls"], [{"id": "t1", "name": "find", "arguments": '{"a":1}'}])
        self.assertEqual((m["stop_reason"], m["usage"]["prompt_tokens"]), ("tool_calls", 9))

    def test_anthropic_stream(self):
        a = _Assembler("anthropic")
        for e in ({"type": "message_start", "message": {"id": "m1", "usage": {"input_tokens": 20, "cache_read_input_tokens": 5}}},
                  {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                  {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}},
                  {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
                  {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}}):
            a.feed(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode())
        m = a.message()
        self.assertEqual((m["text"], m["stop_reason"]), ("Hello", "end_turn"))
        self.assertEqual(pricing.normalise_usage("anthropic", m["usage"]),
                         {"input": 20, "output": 2, "cache_read": 5, "cache_write": 0})


if __name__ == "__main__":
    unittest.main()


class Memory(unittest.TestCase):
    def test_core_memory_never_changes_the_profile_hash(self):
        from agent_runner import memory
        agent = Render.AGENT
        plain = hermes_render.render(agent, ["compression"], Path("/x"))
        learned = hermes_render.render(agent, ["compression"], Path("/x"),
                                       memory_block=memory.persona_block({"vendor_naming": "legal name, never the DBA"}))
        self.assertEqual(plain["hash"], learned["hash"], "an agent learning something is not a configuration change")
        self.assertIn("legal name, never the DBA", learned["soul"])
        self.assertNotIn("core memory", plain["soul"])

    def test_recalled_context_is_marked_as_information(self):
        from agent_runner import memory
        asked = memory.instructions_with_recall("File the Acme bill.", [
            {"text": "Acme pays on the 15th.", "from": "agent:44", "about": "Acme"},
            {"text": "Bills use the legal name.", "from": "dept:3", "about": "vendor bills"},
            {"text": "We close on the 5th.", "from": "org", "about": None}])
        self.assertTrue(asked.startswith("File the Acme bill."))
        self.assertIn("INFORMATION", asked)
        self.assertIn("(your own memory, about Acme) Acme pays on the 15th.", asked)
        self.assertIn("(your department's memory, about vendor bills)", asked)
        self.assertIn("(the organisation's memory) We close on the 5th.", asked)
        self.assertEqual(memory.instructions_with_recall("Do it.", []), "Do it.")

    def test_scope_set_matches_the_memory_server(self):
        from agent_runner import memory
        self.assertEqual(memory.scope_set({"member_id": 44, "department_ids": [3, 9]}), ["agent:44", "dept:3", "dept:9", "org"])

    def test_anthropic_transcript(self):
        from agent_runner import memory
        context = {"system": "persona", "messages": [
            {"role": "user", "content": [{"type": "text", "text": "File it.\n\n---\nRecalled from shared memory…"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Looking."},
                                              {"type": "tool_use", "id": "t1", "name": "find_contacts", "input": {"q": "Acme"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "1 contact"}]}]}]}
        out = memory.transcript_from_payload(context, {"text": "Filed under the legal name."}, "File it.")
        self.assertEqual([(m["role"], m["text"][:28]) for m in out], [
            ("user", "File it."), ("assistant", "Looking.\n[called find_contac"), ("tool", "1 contact"),
            ("assistant", "Filed under the legal name.")])
        self.assertEqual(out[2]["tool_call_id"], "t1")
        self.assertNotIn("Recalled", out[0]["text"], "the first turn is the ORIGINAL instructions")

    def test_openai_transcript(self):
        from agent_runner import memory
        context = {"messages": [{"role": "system", "content": "persona"}, {"role": "user", "content": "Do it."},
                                {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "f", "arguments": "{}"}}]},
                                {"role": "tool", "content": "ok", "tool_call_id": "c1"}]}
        out = memory.transcript_from_payload(context, {"text": "Done."}, "Do it.")
        self.assertEqual([m["role"] for m in out], ["user", "assistant", "tool", "assistant"])


class Skills(unittest.TestCase):
    def test_the_most_specific_assignment_of_a_name_wins(self):
        from agent_runner import skills
        chosen = skills.choose([
            {"skill_name": "file-a-bill", "scope_kind": "org", "pinned_bundle_hash": None},
            {"skill_name": "file-a-bill", "scope_kind": "department", "pinned_bundle_hash": "dept-hash"},
            {"skill_name": "file-a-bill", "scope_kind": "agent", "pinned_bundle_hash": "agent-hash"},
            {"skill_name": "close-the-books", "scope_kind": "role", "pinned_bundle_hash": None}], None)
        self.assertEqual(chosen, {"file-a-bill": "agent-hash", "close-the-books": None})

    def test_order_of_rows_does_not_matter(self):
        from agent_runner import skills
        rows = [{"skill_name": "s", "scope_kind": "agent", "pinned_bundle_hash": "a"},
                {"skill_name": "s", "scope_kind": "org", "pinned_bundle_hash": "o"}]
        self.assertEqual(skills.choose(rows, None), skills.choose(list(reversed(rows)), None))

    def test_the_config_versions_pins_override_every_assignment(self):
        from agent_runner import skills
        chosen = skills.choose([{"skill_name": "s", "scope_kind": "agent", "pinned_bundle_hash": "a"}],
                               [{"name": "s", "bundle_hash": "evaluated"}, {"name": "only-pinned", "bundle_hash": "h"}, "junk"])
        self.assertEqual(chosen, {"s": "evaluated", "only-pinned": "h"})

    def test_paths_that_leave_the_skill_are_refused(self):
        from agent_runner import skills
        for bad in ("", "/etc/passwd", "../x", "a/../../x", "a\\b"):
            self.assertFalse(skills._safe(bad), bad)
        self.assertTrue(skills._safe("references/vendors.md"))

    def test_the_outbox_is_read_as_bundles(self):
        import tempfile
        from agent_runner import skills
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "accounting" / "reconcile" / "references").mkdir(parents=True)
            (root / "accounting" / "reconcile" / "SKILL.md").write_text("---\nname: reconcile\n---\n")
            (root / "accounting" / "reconcile" / "references" / "a.md").write_text("x")
            (root / "stray.txt").write_text("not a skill")
            found = skills.collect_outbox(root)
            self.assertEqual([(n, sorted(f["relative_path"] for f in files)) for n, _, files in found],
                             [("reconcile", ["SKILL.md", "references/a.md"])])
        self.assertEqual(skills.collect_outbox(Path("/nonexistent")), [])


class Cron(unittest.TestCase):
    def nxt(self, line, after, tz="UTC"):
        from datetime import datetime, timezone
        from agent_runner import cron
        return cron.next_after(line, datetime.fromisoformat(after).replace(tzinfo=timezone.utc), tz).strftime("%Y-%m-%d %H:%M")

    def test_common_lines(self):
        self.assertEqual(self.nxt("*/15 * * * *", "2026-09-19 10:07"), "2026-09-19 10:15")
        self.assertEqual(self.nxt("0 9 * * *", "2026-09-19 10:07"), "2026-09-20 09:00")
        self.assertEqual(self.nxt("0 9 * * 1-5", "2026-09-19 10:07"), "2026-09-21 09:00")      # a Saturday -> Monday
        self.assertEqual(self.nxt("30 17 1 * *", "2026-09-19 10:07"), "2026-10-01 17:30")
        self.assertEqual(self.nxt("0 0 1 jan *", "2026-09-19 10:07"), "2027-01-01 00:00")
        self.assertEqual(self.nxt("0 8 * * mon,thu", "2026-09-21 08:00"), "2026-09-24 08:00")  # strictly after
        self.assertEqual(self.nxt("0 8 * * 7", "2026-09-19 10:07"), "2026-09-20 08:00")        # 7 is Sunday

    def test_timezone(self):
        # 09:00 in New York is 13:00 UTC while daylight time is in force
        self.assertEqual(self.nxt("0 9 * * *", "2026-09-19 10:07", "America/New_York"), "2026-09-19 13:00")

    def test_both_day_fields_restricted_means_either(self):
        self.assertEqual(self.nxt("0 9 15 * mon", "2026-09-19 10:07"), "2026-09-21 09:00")     # the Monday, before the 15th

    def test_bad_lines(self):
        from agent_runner import cron
        for bad in ("", "* * * *", "61 * * * *", "* * * * mon-xyz", "*/0 * * * *", "0 0 31 2 *"):
            with self.assertRaises(cron.CronError, msg=bad):
                self.nxt(bad, "2026-09-19 10:07")
        with self.assertRaises(cron.CronError):
            self.nxt("0 9 * * *", "2026-09-19 10:07", "Mars/Olympus")


class SubscriptionAuth(unittest.TestCase):
    """The owner's Max login (docs/build-specs/claude-subscription-auth.md): off unless switched on, token swapped in by the proxy."""

    TOKEN = "sk-ant-oat01-" + "t" * 40

    def setUp(self):
        self._saved = {k: config.ENV.get(k) for k in ("ALLOW_CLAUDE_SUBSCRIPTION", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")}
        config.ENV["ANTHROPIC_API_KEY"] = "sk-ant-api03-" + "a" * 30

    def tearDown(self):
        for k, v in self._saved.items():
            config.ENV.pop(k, None)
            if v is not None:
                config.ENV[k] = v

    def _model(self, mode):
        return {"model": {"provider": "anthropic", "provider_model_id": "claude-sonnet-5", "endpoint_url": None, "auth_mode": mode}}

    def test_off_without_the_switch_or_without_the_token(self):
        config.ENV.pop("ALLOW_CLAUDE_SUBSCRIPTION", None); config.ENV["CLAUDE_CODE_OAUTH_TOKEN"] = self.TOKEN
        self.assertFalse(config.subscription_enabled(), "a token alone switches nothing on")
        config.ENV["ALLOW_CLAUDE_SUBSCRIPTION"] = "1"; config.ENV["CLAUDE_CODE_OAUTH_TOKEN"] = ""
        self.assertFalse(config.subscription_enabled(), "the switch alone is not enough")
        config.ENV["CLAUDE_CODE_OAUTH_TOKEN"] = "short"
        self.assertFalse(config.subscription_enabled(), "a stub is not a token")
        config.ENV["ALLOW_CLAUDE_SUBSCRIPTION"] = "yes"; config.ENV["CLAUDE_CODE_OAUTH_TOKEN"] = self.TOKEN
        self.assertFalse(config.subscription_enabled(), "only an explicit 1 switches it on")

    def test_on_with_both(self):
        config.ENV["ALLOW_CLAUDE_SUBSCRIPTION"] = "1"; config.ENV["CLAUDE_CODE_OAUTH_TOKEN"] = self.TOKEN
        self.assertTrue(config.subscription_enabled())

    def test_a_subscription_model_gets_the_bearer_token_and_never_the_api_key(self):
        config.ENV["ALLOW_CLAUDE_SUBSCRIPTION"] = "1"; config.ENV["CLAUDE_CODE_OAUTH_TOKEN"] = self.TOKEN
        url, auth = _upstream(self._model("claude_subscription"), "anthropic")
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(auth, {"authorization": "Bearer " + self.TOKEN})
        self.assertNotIn("x-api-key", auth)

    def test_an_api_key_model_is_unchanged(self):
        config.ENV["ALLOW_CLAUDE_SUBSCRIPTION"] = "1"; config.ENV["CLAUDE_CODE_OAUTH_TOKEN"] = self.TOKEN
        url, auth = _upstream(self._model("api_key"), "anthropic")
        self.assertEqual(auth, {"x-api-key": config.ENV["ANTHROPIC_API_KEY"]})

    def test_a_subscription_call_is_priced_notionally_by_the_same_table(self):
        model = {"price_input_per_mtok": 2, "price_output_per_mtok": 10, "price_cache_read_per_mtok": Decimal("0.2"), "price_cache_write_per_mtok": Decimal("2.5")}
        tokens = {"input": 2, "output": 4, "cache_read": 3289, "cache_write": 5308}
        self.assertEqual(pricing.cost(tokens, model), Decimal("0.013972"), "list price, whatever it is billed to")


class ClaudeLaunch(unittest.TestCase):
    """The two ways the Claude Code CLI is launched (agent_runner/claude_launch.py); the conformance suite proves the fences."""

    PROXY, KEY = "http://127.0.0.1:8816/anthropic", "run.7.9999999999.abc"

    def test_an_api_key_model_stays_bare_and_authenticates_with_the_proxy_key_as_a_key(self):
        model = {"auth_mode": "api_key"}
        self.assertEqual(claude_launch.fence_flags(model), ["--bare"])
        env = claude_launch.auth_env(model, self.KEY, self.PROXY)
        self.assertEqual(env, {"ANTHROPIC_BASE_URL": self.PROXY, "ANTHROPIC_API_KEY": self.KEY})

    def test_a_subscription_model_is_not_bare_and_is_fenced_by_flag_and_environment(self):
        model = {"auth_mode": "claude_subscription"}
        flags = claude_launch.fence_flags(model)
        self.assertNotIn("--bare", flags)
        self.assertEqual(flags[:2], ["--setting-sources", ""], "no settings source is loaded")
        env = claude_launch.auth_env(model, self.KEY, self.PROXY)
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], self.KEY, "the credential is the run's proxy key, never a real token")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        for name in ("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_DISABLE_CLAUDE_MDS", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"):
            self.assertEqual(env[name], "1")

    def test_a_missing_model_is_api_key(self):
        self.assertFalse(claude_launch.is_subscription({}))
        self.assertFalse(claude_launch.is_subscription(None))
