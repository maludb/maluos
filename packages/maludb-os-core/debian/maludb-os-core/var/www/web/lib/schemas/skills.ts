import { z } from "zod";

/** The contract with app/features/skills/present.php and queries.php — change both together. */
const id = z.number().int();
const option = z.object({ id, name: z.string() });

export const skillAssignment = z.object({
  skill_assignment_id: id,
  skill_name: z.string(),
  /** skill, or runbook — an application's generic skill (db/153). */
  kind: z.string().default("skill"),
  pinned_bundle_hash: z.string().nullable(),
  scope_kind: z.enum(["org", "department", "role", "agent", "application"]),
  department: z.object({ id, name: z.string().nullable() }).nullable(),
  role_key: z.string().nullable(),
  agent: z.object({ member_id: id, name: z.string().nullable() }).nullable(),
  application: z.object({ id, name: z.string().nullable() }).nullable(),
  note: z.string().nullable(),
  assigned_by: z.string().nullable(),
  assigned_by_member_id: id.nullable().default(null),
  created_at: z.string().nullable(),
});
export type SkillAssignment = z.infer<typeof skillAssignment>;

const finding = z.object({ kind: z.string(), file: z.string(), detail: z.string() });

export const skillProposal = z.object({
  skill_proposal_id: id,
  skill_name: z.string(),
  status: z.enum(["proposed", "approved", "rejected", "withdrawn"]),
  agent: z.object({ member_id: id, name: z.string().nullable() }),
  agent_run_id: id.nullable(),
  bundle_hash: z.string(),
  parent_bundle_hash: z.string().nullable(),
  is_change: z.boolean(),
  file_count: z.number().int(),
  scan_findings: z.array(finding),
  decided_by: z.string().nullable(),
  decided_by_member_id: id.nullable().default(null),
  decided_at: z.string().nullable(),
  decision_note: z.string().nullable(),
  created_at: z.string().nullable(),
  skill_markdown: z.string().nullable().optional(),
  parent_markdown: z.string().nullable().optional(),
});
export type SkillProposal = z.infer<typeof skillProposal>;

export const skillAssignOptions = z.object({ departments: z.array(option), agents: z.array(option), roles: z.array(z.string()) });
export type SkillAssignOptions = z.infer<typeof skillAssignOptions>;

export const skillsScreen = z.object({
  assignments: z.array(skillAssignment),
  proposals: z.array(skillProposal),
  proposal_status: z.string(),
  can: z.object({ assign_anywhere: z.boolean(), assign: z.boolean() }),
  options: skillAssignOptions,
});

export const skillProposalView = z.object({ proposal: skillProposal, can: z.object({ decide: z.boolean() }) });
