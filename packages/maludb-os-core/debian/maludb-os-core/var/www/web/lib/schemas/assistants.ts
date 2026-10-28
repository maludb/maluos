import { z } from "zod";

/** The contract with html/assistant/index.php, html/agents/org.php and html/settings/channels.php (db/154–157). */
const id = z.number().int();

export const myAssistant = z.object({
  assistant: z.object({ id, name: z.string() }).nullable(),
  channels: z.array(z.object({ channel: z.string(), label: z.string(), preferred: z.boolean() })).default([]),
  messages: z.array(z.object({
    id, thread_id: id, thread_subject: z.string(), mine: z.boolean(), kind: z.string(), priority: z.string(),
    subject: z.string(), body: z.string(), channel: z.string(), delivery_channel: z.string().nullable(),
    delivered: z.boolean(), delivery_error: z.string().nullable(), created_at: z.string().nullable(),
  })),
  handoffs: z.array(z.object({
    run_id: id, agent_id: id, agent_name: z.string(), department: z.string().nullable(), reason: z.string().nullable(),
    status: z.string(), instructions: z.string(), result: z.string(), started_at: z.string().nullable(), finished_at: z.string().nullable(),
  })),
});
export type MyAssistant = z.infer<typeof myAssistant>;

export const agentOrg = z.object({
  nodes: z.array(z.object({
    id, name: z.string(), kind: z.string(), principal_id: id.nullable(), principal_name: z.string().nullable(),
    parent_id: id.nullable(), departments: z.string().nullable(),
  })),
  proposals: z.array(z.object({
    id, name: z.string(), department_id: id, department_name: z.string(), job_description: z.string(),
    parent_name: z.string().nullable(), model_name: z.string().nullable(),
    roster: z.array(z.object({ id, name: z.string() })), proposed_at: z.string().nullable(),
  })),
  can: z.object({ decide: z.boolean() }),
});
export type AgentOrg = z.infer<typeof agentOrg>;

export const myChannels = z.object({
  assistant: z.object({ id, name: z.string() }).nullable(),
  identities: z.array(z.object({
    id, channel: z.string(), label: z.string().nullable(), preferred: z.boolean(), verified: z.boolean(), code_expires_at: z.string().nullable(),
  })),
  endpoints: z.array(z.object({ channel: z.string(), address: z.string() })),
});

export const agentInbox = z.object({
  messages: z.array(z.object({
    id, thread_id: id, thread_subject: z.string(), outgoing: z.boolean(), other_id: id, other_name: z.string(), other_kind: z.string(),
    kind: z.string(), priority: z.string(), subject: z.string(), body: z.string(), channel: z.string(), status: z.string(),
    created_at: z.string().nullable(),
  })),
  endpoints: z.array(z.object({ channel: z.string(), address: z.string() })),
});
export type AgentInbox = z.infer<typeof agentInbox>;
