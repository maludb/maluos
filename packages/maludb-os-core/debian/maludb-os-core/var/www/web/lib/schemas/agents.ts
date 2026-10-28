import { z } from "zod";
import { agentInbox } from "./assistants";
import { agentOps } from "@/lib/schemas/aiops";
import { approvalRequest } from "@/lib/schemas/approvals";

/** The contract with app/features/agents/present.php — change both together. */

const option = z.object({ id: z.number().int(), name: z.string() });
const managerOption = z.object({ id: z.number().int(), name: z.string(), kind: z.string() });
const avatar = z.object({ initials: z.string(), picture_url: z.string().nullable() });

export const agentRow = z.object({
  id: z.number().int(),
  name: z.string(),
  avatar,
  department_name: z.string().nullable(),
  /** Step 3 (db/151, additive): the department and the model, so the card links them. */
  department_id: z.number().int().nullable().default(null),
  model_id: z.number().int().nullable().default(null),
  role_key: z.string().nullable(),
  kind: z.string(),
  kind_label: z.string(),
  subagent_count: z.number().int(),
  job_title: z.string().nullable(),
  /** The profile description, shown on the card (2026-09-29). */
  description: z.string().nullable().default(null),
  manager_name: z.string().nullable(),
  manager_member_id: z.number().int().nullable().default(null),
  model_key: z.string().nullable(),
  status: z.string(),
});

export const agentsList = z.object({
  agents: z.array(agentRow),
  page: z.number().int(),
  total_pages: z.number().int(),
  filters: z.object({ status: z.string(), department: z.string() }),
  options: z.object({ departments: z.array(option) }),
  can: z.object({ admin: z.boolean() }),
});

export const agent = z.object({
  id: z.number().int().nullable(),
  name: z.string(),
  avatar,
  email: z.string().nullable(),
  departments: z.array(z.string()),
  department_id: z.number().int().nullable(),
  job_title: z.string().nullable(),
  status: z.string(),
  kind: z.string(),
  kind_label: z.string(),
  subagent_count: z.number().int(),
  description: z.string().nullable(),
  role_key: z.string().nullable(),
  phone_number: z.string().nullable(),
  manager_member_id: z.number().int().nullable(),
  manager_name: z.string().nullable(),
  /** Step 2 (additive): the manager's kind (their page), the home location's name, the departments with ids. */
  manager_kind: z.string().nullable().default(null),
  home_location_id: z.number().int().nullable(),
  home_location_name: z.string().nullable().default(null),
  department_links: z.array(option).default([]),
  model_key: z.string().nullable(),
  harness: z.string().nullable(),
  budget_currency: z.string().nullable(),
  hired_at: z.string().nullable(),
});
export type Agent = z.infer<typeof agent>;

/** The two run limits a person sets on a version; "" = not set, the runner's default applies. */
const runLimits = z.object({ max_turns: z.string(), run_timeout_seconds: z.string() });

export const agentVersion = z.object({
  id: z.number().int(),
  version_no: z.number().int(),
  job_description: z.string().nullable(),
  system_prompt: z.object({ id: z.number().int(), name: z.string(), version: z.number().int() }).nullable(),
  parameters_summary: z.string(),
  run_limits: runLimits,
  monthly_budget_display: z.string().nullable(),
  change_note: z.string().nullable(),
  created_at: z.string().nullable(),
  activated_at: z.string().nullable(),
  gated: z.boolean(),
  model_id: z.number().int().nullable().default(null),
  model_name: z.string().nullable().default(null),
  gating_eval_run_id: z.number().int().nullable().default(null),
});
export type AgentVersion = z.infer<typeof agentVersion>;

export const agentDuty = z.object({
  id: z.number().int(), name: z.string(), instructions: z.string(), schedule_cron: z.string(),
  timezone: z.string(), next_run_at: z.string().nullable(), active: z.boolean(),
});

/** The Skills tab (owner, 2026-09-27): the set the next run carries, resolved as the runner resolves it (app/features/skills/resolve.php). */
export const agentSkills = z.object({
  harness: z.string(),
  /** inline: the Claude harness inlines the first `inline_max` by name and the rest are on request; folder: Hermes reads them all; none: this harness uses no skills. */
  rule: z.enum(["inline", "folder", "none"]),
  inline_max: z.number().int(), inline_chars: z.number().int(),
  resolved: z.array(z.object({
    name: z.string(), kind: z.string().default("skill"), description: z.string().nullable(), in_library: z.boolean(), enabled: z.boolean().nullable(), version: z.string().nullable(),
    source: z.object({ scope_kind: z.string(), label: z.string(), href: z.string().nullable() }),
    assignment_id: z.number().int().nullable(), assigned_by: z.object({ id: z.number().int(), name: z.string().nullable() }).nullable(), note: z.string().nullable(),
    pinned_bundle_hash: z.string().nullable(), pinned_by_config: z.boolean(),
    shadowed: z.array(z.object({ scope_kind: z.string(), label: z.string(), href: z.string().nullable() })),
    delivery: z.enum(["inline", "on_request", "folder", "none"]),
  })),
  assignable: z.array(z.object({ name: z.string(), kind: z.string().default("skill"), description: z.string() })),
  library_error: z.string().nullable(),
  can: z.object({ assign: z.boolean() }),
});
export type AgentSkills = z.infer<typeof agentSkills>;

/** One chat turn (agent-chat.md): what the person said, what the agent answered, where it stands. */
export const chatTurn = z.object({
  run_id: z.number().int(), status: z.enum(["running", "awaiting_approval", "succeeded", "failed", "cancelled"]), finished: z.boolean(),
  said: z.string(), reply: z.string().nullable(), error: z.string().nullable(), approval_request_id: z.number().int().nullable(),
  cost: z.string().nullable(), currency: z.string().nullable(), started_at: z.string().nullable(), finished_at: z.string().nullable(),
});
export type ChatTurn = z.infer<typeof chatTurn>;

export const chatConversation = z.object({
  id: z.number().int(), title: z.string(), turns: z.number().int(), created_at: z.string().nullable(), last_at: z.string().nullable(), archived: z.boolean(),
});
export type ChatConversation = z.infer<typeof chatConversation>;

/** The Chat tab (db/163): this person's conversations with this agent, the open one's turns, and whether a message can go now. */
export const agentChat = z.object({
  can_send: z.boolean(), reason: z.string().nullable(), busy_run_id: z.number().int().nullable(), archived_view: z.boolean(),
  conversations: z.array(chatConversation), conversation: chatConversation.nullable(), turns: z.array(chatTurn), message_max: z.number().int(),
});
export type AgentChat = z.infer<typeof agentChat>;

export const agentView = z.object({
  agent,
  tab: z.enum(["chat", "job", "tools", "skills", "duties", "roster", "inbox", "performance", "trail"]),
  /** The Inbox tab (db/155-156). */
  inbox: agentInbox.default({ messages: [], endpoints: [] }),
  /** The Chat tab (agent-chat.md); null on every other tab. */
  chat: agentChat.nullable().default(null),
  version: agentVersion.nullable(),
  pending_version: z.object({ id: z.number().int(), version_no: z.number().int() }).nullable(),
  tool_grants: z.array(z.object({
    id: z.number().int(), endpoint_id: z.number().int(), application_id: z.number().int().nullable().default(null), application_name: z.string(),
    endpoint_name: z.string(), tool_name: z.string(), constraints: z.string().nullable(),
  })),
  skills: agentSkills.nullable().default(null),
  duties: z.array(agentDuty),
  hr_events: z.array(z.object({ id: z.number().int(), occurred_at: z.string().nullable(), label: z.string(), note: z.string().nullable() })),
  reviews: z.array(z.object({
    id: z.number().int(), period_start: z.string(), period_end: z.string(),
    rating: z.number().int().nullable(), summary: z.string().nullable(),
  })),
  approvals: z.array(z.object({
    id: z.number().int(), summary: z.string(), status: z.string(), agent_run_id: z.number().int().nullable(),
    approver_name: z.string().nullable(), approver_member_id: z.number().int().nullable().default(null),
    created_at: z.string().nullable(), expires_at: z.string().nullable(), decided_at: z.string().nullable(),
  })),
  /** The runs paused for an approval, each with its pending requests and what this reader may do (2026-09-27). */
  paused: z.array(z.object({
    id: z.number().int(), started_at: z.string().nullable(), trigger: z.string(), duty_name: z.string().nullable(),
    requests: z.array(approvalRequest.extend({ can: z.object({ decide: z.boolean(), cancel: z.boolean() }) })),
  })),
  counts: z.object({ activity: z.number().int(), escalations: z.number().int(), approvals: z.number().int() }),
  /** Its model calls, runs, spend and evaluations, from the AI Ops views (2026-09-27). */
  ops: agentOps,
  /** A system_one agent (db/145): shadow records what it would do; live acts. */
  system_one: z.object({ mode: z.enum(["shadow", "live"]), can_switch: z.boolean() }).nullable().default(null),
  roster: z.array(z.object({
    member_id: z.number().int(), name: z.string(), role_key: z.string().nullable(),
    status: z.string().nullable(), note: z.string().nullable(), added_at: z.string().nullable(),
  })),
  options: z.object({ managers: z.array(managerOption), tool_endpoints: z.array(option), subagents: z.array(option) }),
  can: z.object({ edit: z.boolean(), offboard: z.boolean() }),
});
export type AgentView = z.infer<typeof agentView>;

export const agentFormData = z.object({
  agent,
  version: z.object({
    model_id: z.number().int().nullable(),
    system_prompt_id: z.number().int().nullable(),
    job_description: z.string(),
    cited_parameters: z.array(z.object({ name: z.string(), value: z.string() })),
    inline_parameters: z.object({
      temperature: z.string(), max_tokens: z.string(), thinking_budget: z.string(), extra_parameters: z.string(),
    }),
    monthly_budget_amount: z.string().nullable(),
    run_limits: runLimits,
  }).nullable(),
  duties: z.array(agentDuty),
  options: z.object({
    models: z.array(option),
    prompts: z.array(option),
    kinds: z.record(z.string(), z.string()),
    departments: z.array(option),
    managers: z.array(managerOption),
    locations: z.array(option),
    subagents: z.array(option),
    tool_endpoints: z.array(option),
  }),
  blank_rows: z.object({ duties: z.number().int(), tools: z.number().int() }),
});
export type AgentFormData = z.infer<typeof agentFormData>;

export const agentVersions = z.object({
  agent,
  versions: z.array(agentVersion),
  can: z.object({ edit: z.boolean() }),
});

export const escalationsList = z.object({
  escalations: z.array(z.object({
    id: z.number().int(), agent_member_id: z.number().int(), agent_name: z.string(), reason_label: z.string(),
    summary: z.string(), to_member_id: z.number().int().nullable(), created_at: z.string().nullable(), resolved: z.boolean(),
    to_member_name: z.string().nullable().default(null), to_member_kind: z.string().nullable().default(null),
    approval_request_id: z.number().int().nullable().default(null), entity_type: z.string().nullable().default(null), entity_id: z.number().int().nullable().default(null),
  })),
  page: z.number().int(),
  total_pages: z.number().int(),
  filters: z.object({ agent: z.string(), open: z.boolean() }),
  options: z.object({ agents: z.array(option) }),
});

export const reviewFormData = z.object({ member: option.extend({ kind: z.string().nullable().default(null) }) });
export type ReviewFormData = z.infer<typeof reviewFormData>;
