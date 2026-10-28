import { z } from "zod";

/** The seven weekdays of opening hours (present_business_hours() in app/features/settings/hours.php). The Helpdesk's until the kernel cut. */
export const businessHours = z.array(z.object({ weekday: z.number().int(), name: z.string(), is_open: z.boolean(), opens: z.string(), closes: z.string() }));
export type BusinessHours = z.infer<typeof businessHours>;

/** The contract with app/features/settings/present.php — change both together. */

export const businessSettings = z.object({
  settings: z.object({
    business_name: z.string(), legal_name: z.string().nullable(), base_currency: z.string(), timezone: z.string(),
    fiscal_year_start_month: z.number().int(), default_payment_terms_days: z.number().int(),
    deal_quiet_days: z.number().int(), prompt_payload_retention_days: z.number().int().nullable(),
    default_hourly_rate: z.string().nullable(),
  }),
  saved: z.boolean(),
  timezones: z.array(z.string()),
  business_hours: businessHours,
  /** The uploaded logo (db/134); null while the shipped logo-full.png is in use. */
  logo: z.object({ url: z.string(), mime: z.string(), size_bytes: z.number().int(), updated_at: z.string().nullable() }).nullable(),
});
export type BusinessSettings = z.infer<typeof businessSettings>;


export const model = z.object({
  id: z.number().int().nullable(),
  model_key: z.string(),
  display_name: z.string(),
  provider: z.string(),
  provider_model_id: z.string().nullable(),
  harness: z.string(),
  context_window_tokens: z.number().int().nullable(),
  price_input_per_mtok: z.string().nullable(),
  price_output_per_mtok: z.string().nullable(),
  price_cache_read_per_mtok: z.string().nullable(),
  price_cache_write_per_mtok: z.string().nullable(),
  currency: z.string(),
  status: z.string(),
  /** What it bills to (db/164): an API key, or the owner's Claude Max plan (Claude Code harness only). */
  auth_mode: z.enum(["api_key", "claude_subscription"]).default("api_key"),
});

export const modelsSettings = z.object({ models: z.array(model), statuses: z.array(z.string()) });

export const modelFormData = z.object({
  // The form — and only the form — carries the stored endpoint (find_model_endpoint_url()).
  model: model.extend({ endpoint_url: z.string().nullable() }),
  options: z.object({
    providers: z.array(z.string()), harnesses: z.array(z.string()), statuses: z.array(z.string()),
    // Which harnesses the runner actually has a class for; null when it could not be asked.
    built_harnesses: z.array(z.string()).nullable().optional(),
    /** Whether the runner has the Max-plan switch on; null when it could not be asked. */
    subscription: z.boolean().nullable().optional(),
  }),
});
export type ModelFormData = z.infer<typeof modelFormData>;

export const systemPrompt = z.object({
  id: z.number().int(), prompt_key: z.string(), name: z.string(), description: z.string().nullable(),
  role_key: z.string().nullable(), current_version: z.number().int(), version_count: z.number().int(),
  used_by_configs: z.number().int(), archived: z.boolean(),
});

export const promptLibrary = z.object({
  prompts: z.array(systemPrompt),
  filters: z.object({ role: z.string() }),
  can: z.object({ write: z.boolean() }),
});

export const promptView = z.object({
  prompt: systemPrompt,
  versions: z.array(z.object({
    id: z.number().int(), version_no: z.number().int(), body: z.string(), change_note: z.string().nullable(),
    created_by_name: z.string().nullable(), created_at: z.string().nullable(), parameters_summary: z.string(),
    /** Step 2 (additive): the author's member id. */
    created_by: z.number().int().nullable().default(null),
  })),
  used_by_count: z.number().int(),
  new_version: z.object({ body: z.string(), temperature: z.string(), max_tokens: z.string(), thinking_budget: z.string() }).nullable(),
  can: z.object({ write: z.boolean() }),
});

export const promptFormData = z.object({ ready: z.boolean() });

/** Where app.<domain>/ takes a person after sign-in, and what they may choose (db/142). */
export const defaultApplication = z.object({
  application_id: z.number().int().nullable(),
  scope_id: z.number().int().nullable(),
  options: z.array(z.object({ id: z.number().int(), name: z.string(), scopes: z.array(z.object({ id: z.number().int(), name: z.string() })) })),
});
export type DefaultApplication = z.infer<typeof defaultApplication>;

/** The member's own Settings screen. No token value is ever part of a read. */
export const mySettings = z.object({
  profile: z.object({ display_name: z.string(), timezone: z.string(), organization: z.string(), bio: z.string() }),
  notifications: z.object({ notify_reply: z.boolean(), notify_event: z.boolean(), notify_exam: z.boolean(), notify_digest: z.boolean() }),
  security: z.object({ enabled: z.boolean() }),
  tokens: z.array(z.object({ id: z.number().int(), label: z.string(), last_used_at: z.string().nullable(), created_at: z.string().nullable() })),
  mcp: z.object({ records_url: z.string(), activity_url: z.string() }),
  /** db/187: the person's enrolled MaluOS desks (Settings → Desks); a code value is never in a read. */
  desks: z.array(z.object({ id: z.number().int(), name: z.string(), presence: z.string(), last_seen_at: z.string().nullable(),
    enrolled_at: z.string().nullable(), hostname: z.string().nullable(), os: z.string().nullable(), app_version: z.string().nullable() })).default([]),
  /** db/188: for an operator (super-admin), the estate's nodes and open alerts under Settings → Desks; null for everyone else. */
  estate: z.object({
    nodes: z.array(z.object({ id: z.number().int(), kind: z.string(), name: z.string(), hostname: z.string().nullable(), presence: z.string(),
      last_seen_at: z.string().nullable(), last_report_at: z.string().nullable(), health: z.string(), summary: z.string(),
      units: z.object({ up: z.number().int(), down: z.number().int() }), agents: z.object({ count: z.number().int(), running: z.number().int(), failed: z.number().int() }),
      disk_max_pct: z.number().nullable(), memory_available_pct: z.number().nullable(), enrolled_at: z.string().nullable(),
      /** db/189: the node's address on the estate's overlay network, or null. */
      overlay: z.object({ address: z.string() }).nullable().default(null) })),
    alerts: z.array(z.object({ id: z.number().int(), ts: z.string().nullable(), node_id: z.number().int(), node: z.string(), kind: z.string(), severity: z.string(), title: z.string() })),
    /** db/189: the estate's overlay network: its range, the hub (null until the coordinator's host joins with --hub), the members with an address. */
    overlay: z.object({ enabled: z.boolean(), range: z.string(), members: z.number().int(),
      hub: z.object({ id: z.number().int(), name: z.string(), endpoint: z.string(), address: z.string() }).nullable() }).nullable().default(null),
    /** db/190: the agent directory, the last tasks across the estate with their provenance, the actions log (maluos docs/phase13-slice2-delegation.md). */
    delegation: z.object({
      agents: z.array(z.object({ id: z.number().int(), name: z.string(), display_name: z.string().nullable(), description: z.string(), capabilities: z.array(z.string()),
        owner: z.string().nullable(), accept_from: z.array(z.string()), max_classification: z.string().nullable(), presence: z.string(), state: z.string(), hired: z.boolean(),
        node: z.object({ id: z.number().int().nullable(), kind: z.string(), name: z.string(), ref: z.string() }), last_seen_at: z.string().nullable() })),
      tasks: z.array(z.object({ id: z.string(), state: z.string(), ts: z.string().nullable(), done_ts: z.string().nullable(), agent: z.string(), node: z.string(), node_name: z.string(),
        originator: z.string(), sender: z.object({ principal: z.string(), node: z.string() }), text: z.string(), reason: z.string().nullable(), envelope_id: z.string(), hop: z.number().int(),
        models: z.number().int(), usd: z.number().nullable() })),
      actions: z.array(z.object({ id: z.string(), node: z.object({ id: z.number().int(), name: z.string().nullable() }), action: z.string(), agent: z.string().nullable(), state: z.string(),
        reason: z.string().nullable(), created_at: z.string().nullable(), done_at: z.string().nullable() })),
      coordinator_key: z.string(),
    }).nullable().default(null),
  }).nullable().default(null),
  section: z.enum(["profile", "notifications", "security", "tokens", "desks"]),
  timezones: z.array(z.string()),
  default_application: defaultApplication.default({ application_id: null, scope_id: null, options: [] }),
});
export type MySettings = z.infer<typeof mySettings>;
