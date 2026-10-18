import { z } from "zod";

/** The contract with app/features/home/present.php — change both together. */
export const homeAgent = z.object({
  id: z.number().int(),
  display_name: z.string(),
  initials: z.string(),
  picture_url: z.string().nullable(),
  job_title: z.string().nullable(),
  /** The profile description, shown under the job title on the card. */
  description: z.string().nullable().default(null),
  status: z.string(),
  department_name: z.string().nullable(),
  /** Step 2 (additive): the department's id and the run the activity line speaks of. */
  department_id: z.number().int().nullable().default(null),
  run_id: z.number().int().nullable().default(null),
  model_key: z.string().nullable(),
  model_id: z.number().int().nullable().default(null),
  activity: z.object({ tone: z.string(), icon: z.string(), headline: z.string(), detail: z.string() }),
});
export type HomeAgent = z.infer<typeof homeAgent>;

const n = z.number().int();
export const dashboard = z.object({
  brand: z.string(),
  counts: z.object({
    locations: n, offices: n, desks: n, departments: n, department_members: n, active_agents: n,
    candidate_agents: n, suspended_agents: n, applications: n, builtin_applications: n,
    pending_approvals: n, pending_approvals_others: n,
  }),
  agents: z.array(homeAgent),
  agent_total: n,
  /** The people who work here, under the agents (2026-09-26). */
  team_members: z.array(z.object({
    id: n, display_name: z.string(), initials: z.string(), job_title: z.string().nullable(),
    business_role: z.string(), status: z.string(), departments: z.array(z.string()), last_login_display: z.string().nullable(),
    /** Step 3 (db/151): the departments with their ids, in the same order as `departments`. */
    department_links: z.array(z.object({ id: n, name: z.string() })).default([]),
  })).default([]),
});
export type HomeTeamMember = z.infer<typeof dashboard>["team_members"][number];
