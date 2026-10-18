#!/bin/bash
# Re-version the Accounting team for the kernel (2026-09-22): the modules their first versions
# read — Books, Expenses, Sales, Documents, Projects — left with the kernel cut (db/133), which
# also deleted their grants on the removed tools. Everything goes through the real PHP handlers as
# member 1. Safe to re-run: grants upsert; a config-save makes a new version each time.
H=/home/maludb/hermes-spike; PY=/var/www/mcp/venv/bin/python; D=/var/www/docs/agents/accounting
post() { local path=$1; shift; local out; out=$(curl -s -m 60 -H "X-Action-Token: $($PY $H/mint.py 1)" -H "Accept: application/json" "$@" http://127.0.0.1:8080$path); echo "  $path -> $(echo "$out" | cut -c1-150)"; }
REC=8; ACT=7; MEM=13
MODEL=$(sudo -u postgres psql -d maludb_os -Atc "select id from model_registry where model_key='hermes:claude-sonnet-5';")
grant() { local agent=$1 ep=$2; shift 2; for t in "$@"; do post /agents/tool-grant.php --data-urlencode "agent=$agent" --data-urlencode "application_endpoint_id=$ep" --data-urlencode "tool_name=$t"; done; }

echo "== module access (read): the AI Ops grant"
for m in 42 43 44; do post /team/grant.php --data-urlencode "member=$m" --data-urlencode "module=ledger" --data-urlencode "access=read"; done

echo "== tool grants on the kernel's tools"
for a in 42 43 44; do grant $a $MEM recall core_memory session_search; grant $a $ACT escalation_raise memory_remember; done
grant 44 $REC ai_spend model_catalog ledger_calls
grant 43 $REC ai_spend ledger_calls agent_runs
grant 42 $REC ai_spend ledger_calls agent_runs agent_performance approval_queue

echo "== configuration versions with duties"
save() { # agent jd-file duty-name cron instructions
  post /agents/config-save.php --data-urlencode "agent=$1" --data-urlencode "job_description@$D/$2" --data-urlencode "model_id=$MODEL" \
    --data-urlencode "monthly_budget_amount=10" --data-urlencode "max_turns=40" --data-urlencode "run_timeout_seconds=900" \
    --data-urlencode "change_note=The kernel cut (2026-09-22): the books are an application now; this job is the token ledger and its period statements" \
    --data-urlencode "duties[0][name]=$3" --data-urlencode "duties[0][schedule_cron]=$4" --data-urlencode "duties[0][timezone]=UTC" --data-urlencode "duties[0][instructions]=$5"
  local V=$(sudo -u postgres psql -d maludb_os -Atc "select id from agent_config_versions where agent_member_id=$1 order by version_no desc limit 1;")
  post /agents/config-activate.php --data-urlencode "agent=$1" --data-urlencode "version=$V" --data-urlencode "confirmed=1"
}
save 44 sasha.md "Morning provider cost check" "0 7 * * 1-5" "Do your morning provider cost check: what each model provider has cost so far this month and what the month will come to, which calls failed or were refused, and what looks odd. Raise one escalation for each thing a person must act on (look for an open one first), remember what will matter next time, and finish with your report."
save 43 becky.md "Morning ledger check" "30 7 * * 1-5" "Do your morning ledger check: this month's spend by provider and agent against budget, whether last month's period statement is closed and exported, and any figure that does not add up. Raise one escalation for each thing a person must act on (look for an open one first), and finish with your report."
save 42 jack.md "Morning brief for the owner" "0 8 * * 1-5" "Prepare this morning's brief for the owner. Read the spend by agent, model and provider yourself, against budget; look at what Sasha and Becky reported this morning (agent_runs); delegate at most two questions that are worth a run; then write the brief."
