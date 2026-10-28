import { z } from "zod";

/** The contract with app/features/invitations/present.php — change both together. */
const id = z.number().int();

export const invitationsScreen = z.object({
  invitations: z.array(z.object({
    id,
    email: z.string(),
    business_role: z.string(),
    business_role_label: z.string(),
    invited_by_name: z.string(),
    invited_by_member_id: z.number().int().nullable().default(null),
    sent_at: z.string().nullable(),
    expires_at: z.string().nullable(),
    expired: z.boolean(),
  })),
  options: z.object({
    departments: z.array(z.object({ id, name: z.string() })),
    business_roles: z.array(z.object({ id: z.string(), name: z.string() })),
  }),
  can: z.object({ invite_without_department: z.boolean() }),
  ttl_days: z.number().int(),
});
