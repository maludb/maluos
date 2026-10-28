import { z } from "zod";

/** The contract with app/features/approvals/present.php and policies.php — change both together. */
const id = z.number().int();
const who = z.object({ member_id: id, name: z.string(), kind: z.string().nullable().optional() });

export const approvalRequest = z.object({
  approval_request_id: id,
  status: z.string(),
  action_key: z.string(),
  summary: z.string(),
  parameters: z.record(z.string(), z.unknown()),
  amount: z.string().nullable(),
  currency: z.string().nullable(),
  entity_type: z.string().nullable(),
  entity_id: id.nullable(),
  policy: z.string().nullable(),
  policy_id: id.nullable().default(null),
  requested_by: who,
  agent_run_id: id.nullable(),
  approver: who,
  created_at: z.string().nullable(),
  expires_at: z.string().nullable(),
  decided_at: z.string().nullable(),
  decision_note: z.string().nullable(),
  executed_at: z.string().nullable(),
  execution_error: z.string().nullable(),
  executed_activity_id: id.nullable(),
});
export type ApprovalRequest = z.infer<typeof approvalRequest>;

export const approvalsQueue = z.object({
  role: z.enum(["approver", "requester"]),
  status: z.string().nullable(),
  requests: z.array(approvalRequest),
});

export const approvalView = z.object({
  request: approvalRequest,
  can: z.object({ decide: z.boolean(), cancel: z.boolean() }),
});

export const approvalPolicy = z.object({
  id: id.nullable(),
  name: z.string(),
  category: z.string(),
  category_label: z.string(),
  action_pattern: z.string(),
  applies_to: z.string(),
  applies_to_label: z.string(),
  agent_member_id: id.nullable(),
  department_id: id.nullable(),
  amount_threshold: z.string().nullable(),
  amount_threshold_display: z.string().nullable(),
  currency: z.string().nullable(),
  approver_member_id: id.nullable(),
  approver_name: z.string().nullable(),
  expires_after_hours: z.number().int(),
  active: z.boolean(),
});

export const approvalPoliciesScreen = z.object({
  policies: z.array(approvalPolicy),
  can: z.object({ edit: z.boolean() }),
});

const named = z.object({ id: z.string(), name: z.string() });
const member = z.object({ id, name: z.string(), kind: z.string() });
export const approvalPolicyFormData = z.object({
  policy: approvalPolicy,
  options: z.object({
    categories: z.array(named),
    applies_to: z.array(named),
    agents: z.array(member),
    approvers: z.array(member),
    departments: z.array(z.object({ id, name: z.string() })),
  }),
  base_currency: z.string(),
});
export type ApprovalPolicyFormData = z.infer<typeof approvalPolicyFormData>;
