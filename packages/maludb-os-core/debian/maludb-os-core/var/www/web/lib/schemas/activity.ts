import { z } from "zod";

/** The contract with app/features/activity/present.php — change both together. */
export const activityRow = z.object({
  id: z.number().int(),
  occurred_at: z.string().nullable(),
  actor_name: z.string().nullable(),
  /** Step 2 (additive): the actor's id, so the Who column links (kind from actor_is_agent). */
  actor_member_id: z.number().int().nullable().default(null),
  actor_is_agent: z.boolean(),
  action: z.string(),
  entity_type: z.string().nullable(),
  entity_id: z.number().int().nullable(),
  /** The record\'s name (db/152), when its kind has one; else the screen shows "kind #id". */
  entity_label: z.string().nullable().default(null),
  source: z.string(),
});

export const activityTrail = z.object({
  rows: z.array(activityRow),
  pagination: z.object({ page: z.number().int(), total_pages: z.number().int(), total: z.number().int() }),
  filters: z.object({
    period: z.string(), source: z.string(), member: z.string(), entity_type: z.string(),
    entity_id: z.string(), views: z.boolean(),
  }),
  options: z.object({
    actors: z.array(z.object({ id: z.number().int(), name: z.string() })),
    entity_types: z.array(z.string()),
  }),
});
