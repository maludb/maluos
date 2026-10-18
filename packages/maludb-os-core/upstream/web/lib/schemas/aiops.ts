import { z } from "zod";

/** The contract with app/features/aiops/present.php — change both together. A list never carries a prompt. */
const id = z.number().int();
const keyed = z.object({ id: z.string(), name: z.string() });
const member = z.object({ id, name: z.string(), kind: z.string() });
const who = z.object({ id, name: z.string().nullable() });
/** A member with the kind that decides its page (click-around step 2): an agent's or a person's. */
export const whoKind = z.object({ id, name: z.string().nullable(), kind: z.string().nullable().default(null) });

export const ledgerCall = z.object({
  id, occurred_at: z.string().nullable(), agent: who.nullable(), acting: who, run_id: id.nullable(), harness: z.string(), provider: z.string(),
  model_name: z.string().nullable(), provider_model_id: z.string(), request_id: z.string(), call_kind: z.string(), status: z.string(), status_label: z.string(),
  error_code: z.string().nullable(), error_message: z.string().nullable(), input_tokens: z.number().int(), output_tokens: z.number().int(),
  cache_read_tokens: z.number().int(), cache_write_tokens: z.number().int(), latency_ms: z.number().int().nullable(), cost: z.string(), currency: z.string(),
  payload_expired: z.boolean(),
  /** Step 2 (additive): the model's registry id and the application the call served, when known. */
  model_id: id.nullable().default(null), application_id: id.nullable().default(null),
});
export type LedgerCall = z.infer<typeof ledgerCall>;
const trailRow = z.object({ id, action: z.string(), entity_type: z.string().nullable(), entity_id: id.nullable(), occurred_at: z.string().nullable() });

export const promptLogScreen = z.object({
  calls: z.array(ledgerCall), total: z.number().int(), page: z.number().int(), page_size: z.number().int(),
  totals: z.object({ cost: z.string(), tokens: z.number().int(), failed: z.number().int() }),
  filters: z.object({ agent: id.nullable(), run: id.nullable(), period: z.string(), status: z.string(), request_id: z.string(),
    /** Step 4: the deep-link filters an aggregate row arrives with. */
    acting: id.nullable().default(null), model: id.nullable().default(null), provider: z.string().default(""),
    department: id.nullable().default(null), application: id.nullable().default(null), month: z.string().default(""), day: z.string().default("") }),
  filter_labels: z.object({ acting: z.string().nullable(), model: z.string().nullable(), department: z.string().nullable(), application: z.string().nullable(), month: z.string().nullable(), day: z.string().nullable().default(null) })
    .default({ acting: null, model: null, department: null, application: null, month: null, day: null }),
  options: z.object({ periods: z.array(keyed), statuses: z.array(keyed), agents: z.array(member) }),
  can: z.object({ evals: z.boolean() }),
});

const side = z.object({ text: z.string(), truncated: z.boolean(), bytes: z.number().int() });

// db/124: what people said about a run or one assistant answer. `mine` drives the buttons' state.
const verdicts = z.object({
  mine: z.object({ verdict: z.string(), note: z.string().nullable(), updated_at: z.string().nullable() }).nullable(),
  all: z.array(z.object({ verdict: z.string(), note: z.string().nullable(), member_name: z.string().nullable(), member_id: id.nullable().default(null), updated_at: z.string().nullable() })),
});
export const promptCallScreen = z.object({
  call: ledgerCall, payload_state: z.enum(["none", "expired", "shown"]), context: side.nullable(), response: side.nullable(),
  actions: z.array(trailRow), verdicts,
  can: z.object({ promote: z.boolean(), verdict: z.boolean() }),
});

export const agentRunScreen = z.object({
  run: z.object({
    id, agent: who, trigger: z.string(), status: z.string(), error: z.string().nullable(), model_name: z.string().nullable(), harness: z.string().nullable(),
    request_id: z.string().nullable(), requested_by_name: z.string().nullable(), duty_name: z.string().nullable().default(null),
    parent_run_id: id.nullable(), approval_request_id: id.nullable(),
    model_id: id.nullable().default(null), requested_by: whoKind.nullable().default(null), application_id: id.nullable().default(null),
    config_version_id: id.nullable(), project_id: id.nullable(), task_id: id.nullable(), input_tokens: z.number().int(), output_tokens: z.number().int(),
    cache_read_tokens: z.number().int(), cache_write_tokens: z.number().int(), cost: z.string(), currency: z.string(),
    started_at: z.string().nullable(), finished_at: z.string().nullable(), instructions: z.string().nullable(), result: z.string().nullable(),
  }),
  calls: z.array(ledgerCall),
  children: z.array(z.object({ id, agent_name: z.string().nullable(), agent_member_id: id.nullable().default(null), status: z.string(), cost: z.string(), currency: z.string(), started_at: z.string().nullable() })),
  actions: z.array(trailRow), verdicts,
  // db/122: which tool ran, whether it failed, how long it took. The durable copy — the runner's
  // in-memory one was all there was until 2026-09-20, and a restart lost it.
  events: z.array(z.object({ seq: z.number().int(), at: z.string().nullable(), event: z.string(),
    tool_name: z.string().nullable(), status: z.string().nullable(),
    duration_ms: z.number().int().nullable(), error: z.string().nullable() })),
  can: z.object({ promote: z.boolean(), verdict: z.boolean() }),
});

export const aiSpendScreen = z.object({
  period: z.string(), group_by: z.string(),
  rows: z.array(z.object({
    key: z.string().nullable(), /** For the agent grouping: the key's member_kind, so the row links to the agent or the person. */ kind: z.string().nullable().default(null), label: z.string(), calls: z.number().int(), failed: z.number().int(), input_tokens: z.number().int(), output_tokens: z.number().int(),
    cache_read_tokens: z.number().int(), cache_write_tokens: z.number().int(), avg_latency_ms: z.number().int().nullable(), cost: z.string(), currency: z.string(), cache_saving: z.string(),
  })),
  totals: z.object({ calls: z.number().int(), failed: z.number().int(), cost: z.string(), cache_saving: z.string(), tokens: z.number().int(), currency: z.string() }),
  sees_everything: z.boolean(), options: z.object({ periods: z.array(keyed), groups: z.array(keyed) }),
});

export const evalSet = z.object({
  id: id.nullable(), name: z.string(), description: z.string().nullable(), agent: who.nullable(), role_key: z.string().nullable(), department_id: id.nullable(),
  department_name: z.string().nullable(), pass_threshold: z.string(), status: z.string(), status_label: z.string(), case_count: z.number().int(),
  active_case_count: z.number().int(), schedule_count: z.number().int(),
  /** The Auditor's trace checks (db/145) — the jevCheck shape below. */
  trace_checks: z.array(z.record(z.string(), z.unknown())).nullable().default(null),
});
/** One JEV check (db/144) — a typed question JEV answers about a trial, with its pass rule. */
export const jevCheck = z.object({
  id: z.string(), type: z.enum(["noul", "choice", "score"]), instructions: z.string(),
  criteria: z.union([z.record(z.string(), z.unknown()), z.array(z.string()), z.null()]).optional(),
  pass_at: z.number().optional(), uncertain: z.array(z.number()).optional(),
  accept: z.array(z.string()).optional(), min_level: z.number().int().optional(), min_confidence: z.number().optional(),
  required: z.boolean().optional(), weight: z.number().optional(),
});
export type JevCheck = z.infer<typeof jevCheck>;

export const evalCase = z.object({
  id: id.nullable(), eval_set_id: id, title: z.string(), input: z.string(), expected: z.string().nullable(), rubric: z.string().nullable(), grader: z.string(),
  grader_label: z.string().nullable(), weight: z.string(), origin: z.string(), source_ledger_id: id.nullable(), source_run_id: id.nullable(), active: z.boolean(),
  checks: z.array(jevCheck).nullable().default(null),
});
const evalSchedule = z.object({
  id, eval_set_id: id, eval_set_name: z.string(), agent_name: z.string().nullable(), kind: z.string(), kind_label: z.string(), cadence: z.string(), cadence_label: z.string(),
  sample_size: z.number().int().nullable(), regression_delta: z.string(), active: z.boolean(), next_run_at: z.string().nullable(), last_run_at: z.string().nullable(),
  /** Step 2 (additive). */
  agent_member_id: id.nullable().default(null), last_eval_run_id: id.nullable().default(null),
});
export const evalRun = z.object({
  id, eval_set_id: id, eval_set_name: z.string(), trigger: z.string(), status: z.string(), score: z.string().nullable(), pass_threshold: z.string(),
  cases_total: z.number().int(), cases_passed: z.number().int(), cost: z.string(), currency: z.string(), started_at: z.string().nullable(), finished_at: z.string().nullable(),
  /** Step 2 (additive): who was evaluated, on what, against which run, started by whom. */
  agent_member_id: id.nullable().default(null), agent_name: z.string().nullable().default(null), config_version_id: id.nullable().default(null),
  model_id: id.nullable().default(null), model_name: z.string().nullable().default(null), baseline_run_id: id.nullable().default(null),
  started_by: whoKind.nullable().default(null),
});
export const evalAlert = z.object({
  id, eval_set_id: id, eval_set_name: z.string(), agent: who.nullable(), eval_run_id: id.nullable(), kind: z.string(), severity: z.string(), score: z.string().nullable(),
  baseline_score: z.string().nullable(), detail: z.string(), status: z.string(), opened_at: z.string().nullable(), acknowledged_at: z.string().nullable(),
  resolved_at: z.string().nullable(), resolution: z.string().nullable(),
  /** Step 2 (additive). */
  schedule_id: id.nullable().default(null), acknowledged_by: whoKind.nullable().default(null),
});

/** One period of an agent's model usage, on its own page (present_agent_ledger_period()). */
export const agentLedgerPeriod = z.object({
  calls: z.number().int(), failed: z.number().int(), input_tokens: z.number().int(), output_tokens: z.number().int(), cache_read_tokens: z.number().int(),
  avg_latency_ms: z.number().int().nullable(), cost: z.string(), currency: z.string(), last_at: z.string().nullable(),
});
/** A run as the agent page lists it — the run screen's row without its texts. */
export const agentRunRow = z.object({
  id, trigger: z.string(), status: z.string(), error: z.string().nullable(), model_name: z.string().nullable(), harness: z.string().nullable(),
  requested_by_name: z.string().nullable(), duty_name: z.string().nullable().default(null), parent_run_id: id.nullable(), approval_request_id: id.nullable(),
  input_tokens: z.number().int(), output_tokens: z.number().int(), cost: z.string(), currency: z.string(),
  started_at: z.string().nullable(), finished_at: z.string().nullable(),
  /** Step 2 (additive): the model's registry id, who asked (with kind), and the application the run served. */
  model_id: id.nullable().default(null), requested_by: whoKind.nullable().default(null), application_id: id.nullable().default(null),
});
/** Everything AI Ops knows about one agent, carried on the agent's own page (html/agents/view.php `ops`). */
export const agentOps = z.object({
  ledger: z.object({ this_month: agentLedgerPeriod, last_month: agentLedgerPeriod, all: agentLedgerPeriod }),
  calls: z.array(ledgerCall), runs: z.array(agentRunRow),
  run_counts: z.object({ total: z.number().int(), active: z.number().int(), failed: z.number().int(), succeeded: z.number().int(), last_started_at: z.string().nullable() }),
  evals: z.object({ sets: z.array(evalSet), runs: z.array(evalRun), alerts: z.array(evalAlert) }).nullable(),
});
export type AgentOps = z.infer<typeof agentOps>;

export const evalSetsScreen = z.object({
  sets: z.array(evalSet), filters: z.object({ agent: id.nullable(), status: z.string() }), runner_built: z.boolean(), runner_note: z.string(),
  options: z.object({ agents: z.array(member) }), can: z.object({ write: z.boolean() }),
});
export const evalSetFormData = z.object({
  set: evalSet, options: z.object({ agents: z.array(member), departments: z.array(z.object({ id, name: z.string() })), statuses: z.array(keyed) }),
});
export type EvalSetFormData = z.infer<typeof evalSetFormData>;
/** How one JEV check has answered in a set, and how often a person agreed (mcp_eval_check_calibration). */
export const evalCalibration = z.object({
  check_id: z.string(), answers: z.number().int(), passes: z.number().int(), fails: z.number().int(), uncertain: z.number().int(),
  person_graded: z.number().int(), person_agreed: z.number().int(), agreement: z.number().nullable(), mean_confidence: z.number().nullable(),
});
export const evalSetScreen = z.object({
  set: evalSet, cases: z.array(evalCase), schedules: z.array(evalSchedule), runs: z.array(evalRun), runner_built: z.boolean(), runner_note: z.string(),
  calibration: z.array(evalCalibration).default([]),
  can: z.object({ write: z.boolean(), run: z.boolean() }),
});
export const evalCaseFormData = z.object({
  case: evalCase, set: evalSet, from: z.object({ kind: z.enum(["ledger", "run"]), id }).nullable(), options: z.object({ graders: z.array(keyed) }),
});
export type EvalCaseFormData = z.infer<typeof evalCaseFormData>;
export const evalScheduleScreen = z.object({
  set: evalSet, schedules: z.array(evalSchedule), runner_built: z.boolean(), options: z.object({ kinds: z.array(keyed), cadences: z.array(keyed) }),
});
export const evalRunScreen = z.object({
  run: evalRun,
  results: z.array(z.object({ id, case_id: id, case_title: z.string(), agent_run_id: id.nullable(), passed: z.boolean(),
    score: z.string().nullable(), grader_notes: z.string().nullable(), grader: z.string(), is_graded: z.boolean(),
    // Against the run's baseline: "regressed" is the word a reader is looking for.
    change: z.enum(["regressed", "fixed", "new"]).nullable(),
    awaiting_person: z.boolean().default(false), graded_by_person: z.boolean().default(false),
    // What JEV answered, trial by trial (db/144); null for other graders.
    jev: z.object({ verdict: z.string(), model: z.string().nullable(), trials: z.array(z.object({
      trial: z.number().int(), verdict: z.string(), score: z.number().nullable(), guard: z.number().nullable(), error: z.string().nullable(),
      checks: z.array(z.object({ id: z.string(), outcome: z.string(), value: z.number().nullable(), choice: z.string().nullable(),
        level: z.number().int().nullable(), confidence: z.number().nullable() })) })) }).nullable().default(null) })),
  // What the score covers. A number that is not yet the whole truth has to say so.
  coverage: z.object({ graded: z.number().int(), awaiting: z.number().int(), total: z.number().int(), note: z.string() }),
  can: z.object({ grade: z.boolean() }),
});
export type EvalRunScreen = z.infer<typeof evalRunScreen>;
export const gradedTracesScreen = z.object({
  traces: z.array(z.object({ id, agent_run_id: id, agent_name: z.string().nullable(), eval_set_id: id.nullable(), score: z.string().nullable(), passed: z.boolean().nullable(),
    grader_notes: z.string().nullable(), graded_at: z.string().nullable(),
    agent_member_id: id.nullable().default(null), eval_set_name: z.string().nullable().default(null) })),
  filters: z.object({ agent: id.nullable(), failed: z.boolean(), eval_set: id.nullable().default(null) }), runner_built: z.boolean(),
  options: z.object({ agents: z.array(member), sets: z.array(z.object({ id, name: z.string() })) }).default({ agents: [], sets: [] }),
});
export const evalWatchScreen = z.object({
  schedules: z.array(evalSchedule), alerts: z.array(evalAlert), filters: z.object({ agent: id.nullable(), severity: z.string(), status: z.string(), eval_set: id.nullable().default(null) }),
  runner_built: z.boolean(), can: z.object({ write: z.boolean() }),
  options: z.object({ agents: z.array(member), sets: z.array(z.object({ id, name: z.string() })) }).default({ agents: [], sets: [] }),
});
export const evalAlertScreen = z.object({ alert: evalAlert, can: z.object({ act: z.boolean() }) });

/** The AI Ops front page (html/ai/index.php): each section's headline numbers. `evals` is null for an agent, `ops` for a non-admin. */
export const aiOpsIndexScreen = z.object({
  spend: z.object({ cost: z.string(), currency: z.string(), calls: z.number().int(), failed: z.number().int(), tokens: z.number().int(),
    providers: z.array(z.object({ name: z.string(), cost: z.string() })) }),
  log: z.object({ calls_today: z.number().int(), failed_today: z.number().int(), cost_today: z.string() }),
  statements: z.object({ period: z.string(), status: z.string(), closed_at: z.string().nullable() }),
  evals: z.object({
    sets_active: z.number().int(), sets_total: z.number().int(),
    last_run: z.object({ id, set_name: z.string(), status: z.string(), score: z.string().nullable(), finished_at: z.string().nullable() }).nullable(),
    alerts_open: z.number().int(), alerts_critical: z.number().int(), schedules_active: z.number().int(),
    traces_graded: z.number().int(), traces_failed: z.number().int(),
  }).nullable(),
  ops: z.object({ probes_total: z.number().int(), probes_failed: z.number().int(), probes_warning: z.number().int(), events_open: z.number().int(),
    audit_decisions_7d: z.number().int(), system_decisions_7d: z.number().int() }).nullable(),
  models: z.object({ active: z.number().int(), total: z.number().int() }),
});

/** The ledger's period statements (A5) — the contract with app/features/aiops/statements.php. */
export const aiPeriodMonth = z.object({
  period: z.string(), period_start: z.string(), period_end: z.string(), status: z.string(), closed_at: z.string().nullable(),
  closed_by_name: z.string().nullable(), closed_by: id.nullable().default(null), rolled_up_at: z.string().nullable(), note: z.string().nullable(),
  ledger_calls: z.number().int(), ledger_cost: z.string(), currencies: z.string(), statement_lines: z.number().int(), statement_amount: z.string(), is_past: z.boolean(),
});
export const aiStatementLine = z.object({
  id, provider: z.string(), model_id: id.nullable(), model: z.string().nullable(), department_id: id.nullable(), department: z.string().nullable(),
  agent_id: id.nullable(), agent: z.string().nullable(), application_id: id.nullable(), application: z.string().nullable(),
  calls: z.number().int(), input_tokens: z.number().int(), output_tokens: z.number().int(), cache_read_tokens: z.number().int(), cache_write_tokens: z.number().int(),
  late_calls: z.number().int(), amount: z.string(), currency: z.string(), status: z.string(), note: z.string().nullable(),
});
export const aiStatementsScreen = z.object({
  period: z.string(),
  months: z.array(aiPeriodMonth),
  selected: z.object({ period: z.string(), period_start: z.string(), period_end: z.string(), status: z.string(), closed_at: z.string().nullable(),
    closed_by_name: z.string().nullable(), closed_by: id.nullable().default(null), rolled_up_at: z.string().nullable(), note: z.string().nullable(), is_past: z.boolean() }),
  lines: z.array(aiStatementLine),
  can: z.object({ rollup: z.boolean(), close: z.boolean() }),
});
export type AiStatementsScreen = z.infer<typeof aiStatementsScreen>;

/** The Sysadmin's view (html/ai/system, db/145). Samples are redacted before they are stored. */
const systemOneDecision = z.object({ id, agent_name: z.string(), playbook: z.string(), subject: z.string(), decision: z.string(),
  mode: z.string(), acted: z.boolean(), note: z.string().nullable(), at: z.string().nullable(),
  subject_kind: z.string().optional(), subject_id: id.nullable().optional(),
  /** Step 2 (additive): the run the decision was made in, when there was one. */
  agent_run_id: id.nullable().default(null) });
const systemOneAgent = z.object({ id, name: z.string(), mode: z.string() });
export const systemScreen = z.object({
  filters: z.object({ status: z.string() }),
  agents: z.array(systemOneAgent),
  probes: z.array(z.object({ probe: z.string(), status: z.string(), detail: z.string(), checked_at: z.string().nullable(), changed_at: z.string().nullable() })),
  events: z.array(z.object({ id, source: z.string(), sample: z.string(), category: z.string().nullable(), severity: z.number().int().nullable(),
    occurrences: z.number().int(), first_seen: z.string().nullable(), last_seen: z.string().nullable(), status: z.string(),
    status_by_name: z.string().nullable(), note: z.string().nullable() })),
  decisions: z.array(systemOneDecision),
  can: z.object({ act: z.boolean() }),
});
/** The Auditor's view (html/ai/audit, db/145). */
export const auditScreen = z.object({
  agents: z.array(systemOneAgent),
  decisions: z.array(systemOneDecision),
  alerts: z.array(z.object({ id, eval_set_name: z.string(), kind: z.string(), severity: z.string(), detail: z.string(), status: z.string(), opened_at: z.string().nullable(),
    eval_set_id: id.nullable().default(null), agent_member_id: id.nullable().default(null), agent_name: z.string().nullable().default(null) })),
  trace_grades: z.array(z.object({ id, agent_run_id: id, agent_name: z.string().nullable(), passed: z.boolean().nullable(), score: z.string().nullable(),
    notes: z.string().nullable(), graded_at: z.string().nullable(), agent_member_id: id.nullable().default(null) })),
});
