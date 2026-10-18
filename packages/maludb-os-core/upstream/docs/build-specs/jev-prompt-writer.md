# The JEV prompt writer (agent 53, 2026-09-27)

**The owner's ask:** find the JEV prompt-writing skill for Claude Code, and make an agent on the Claude harness
that uses it to write JEV prompts for the system_one agents. On what it may read, the owner chose to open the
evidence to this agent.

## What it is

- **Hire:** "JEV Prompt Writer", member 53, `jev-writer@agents.subello.com`, in **Audit**; its manager is the hirer
  while Audit has none. It runs on Claude Fable 5.1 on the `claude_agent_sdk` harness, with a $10 monthly budget
  and role `jev_prompt_writer`.
- **Hire script:** `bin/hire_jev_prompt_writer.php`. Running it again grants any tools and skills added since
  and changes nothing else.
- **Job:** it drafts the JEV question sets the system_one agents ask:
  - the Auditor's eval-set trace checks and eval-case checks;
  - the playbooks' `DEFAULT_TRACE_CHECKS` and `LOG_QUESTIONS`;
  - their thresholds.

  It starts from the decision each answer drives, reads the evidence, diagnoses each wrong or unsure answer,
  and delivers a draft in the kernel's check format, with where it goes and a proof set of past runs or lines
  and what each should come out as.
- **It writes nothing.** Evals are written, changed and graded by people (the owner's rule, enforced by
  `aiops_require_evals()`), and the playbooks are code. To hand a person a draft, it raises an escalation to
  its manager.

## Its skills (repository `skills/`, imported into the library and assigned)

| Skill | What | Source |
|---|---|---|
| `typesafe-ai` | TypeSafe's own skill for building with System One | Vendored unchanged from `github.com/typesafe-ai/skills` @ `65a39f3` (MIT; the licence is kept as `LICENSE.txt`, because the library takes text files only). The community skill `dbreunig/building-with-jev-skill` was not used. |
| `typesafe-jev-docs` | The TypeSafe doc pages that skill says to read (System One, building, state, the three primitives, confidence, the API), copied **2026-09-27** from `docs.typesafe.ai/<page>.md` and screened. An agent here has no web tool. | TypeSafe's docs |
| `jev-prompts-for-system-one` | Where each prompt lives, the exact check format (`case-save.php`, `jev.validate_checks()`), the pass rules, the state each set sees, the sets in use and the Sysadmin's rules, and how to deliver. Kept under 6,000 characters. | Written here |

The Claude harness carries each skill in the persona only up to 6,000 characters (`claude_render.py`), and
gives no file tool. The agent reads the rest, including TypeSafe's whole skill and the doc pages, with
`skill_read` (`docs/build-specs/skill-library.md`).

## Its tools (read only, plus one hand-off)

- **Records MCP:** `system_one_decisions`, `audit_findings`, `eval_status`, `eval_findings`, `eval_calibration`,
  `system_events`, `system_health`, `records_search`, `skill_library`, `skill_read`.
- **Activity MCP:** `record_history`.
- **Actions MCP:** `escalation_raise`.

## What it may see (db/150)

- **The problem.** The judgement evidence was humans-only, so its first run concluded "nothing has happened"
  when 31 decisions existed.
- **The change.** `app_reads_judgement_evidence()` is true only for an active agent whose role is
  `jev_prompt_writer`. It opens, read only, these views:
  - the system_one decisions, events and probes;
  - the eval sets, cases, runs, results, schedules, alerts, calibration and trace grades.
  Each view keeps its rule for everyone else. The prompt ledger (every model call's full context) stays closed.

## Built and proven (2026-09-27)

- **Run 356:** it worked, but it was blind, as described above.
- **Run 363** ($1.27, after db/150):
  - It read all 8 of the Sysadmin's `logs_and_guardrails` decisions and their events.
  - It found all 3 shadow escalations false: two scanner 404s for WordPress files, and one duplicate line of
    a real outage.
  - It traced the cause to severity levels that ask JEV to guess repetition, a category set with no meaning
    for refused scanner requests and no no-match option, and `someone_probing` measuring background scanning
    rather than intrusion.
  - It drafted a replacement `LOG_QUESTIONS`, six rule and threshold proposals, and an 11-line proof set.
  - **The draft waits for a person to apply it.**
- **Run 373:** it read a 44 KB reference file and TypeSafe's whole skill through `skill_read`. Run 368 had failed
  on the harness's 64 KiB stream line limit, now 32 MiB.
- **Found on the way:**
  - Every MCP tool given a `period` raised a NameError, because `_PERIODS` was left behind by the kernel cut.
    Restored.
  - The skill frontmatter reader stored a YAML block description as ">". Fixed, and TypeSafe's description was
    corrected in MaluDB.
