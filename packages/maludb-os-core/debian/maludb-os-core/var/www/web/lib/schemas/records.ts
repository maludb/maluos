import { z } from "zod";

/** The contract with app/features/records/present.php — change both together. */
export const tagging = z.object({ tag_id: z.number().int(), name: z.string() });
export type Tagging = z.infer<typeof tagging>;

export const recordComment = z.object({
  id: z.number().int(),
  author_name: z.string().nullable(),
  body: z.string(),
  created_at: z.string().nullable(),
  mine: z.boolean(),
});
export type RecordComment = z.infer<typeof recordComment>;
