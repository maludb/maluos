import { z } from "zod";

/** The contract with present_launcher_application() in app/features/applications/present.php — change both together. */
export const launcherApplication = z.object({
  id: z.number().int(),
  name: z.string(),
  description: z.string().nullable(),
  icon: z.string(),
  url: z.string().nullable(),
  sso: z.boolean(),
  business_area: z.string().nullable(),
  capability: z.string().nullable(),
  status: z.string(),
  /** A scoped application (db/141): one link per site or department the person holds. */
  scopes: z.array(z.object({ id: z.number().int(), name: z.string(), role: z.string().nullable() })).default([]),
});

export const launcherScreen = z.object({
  business: z.object({ name: z.string() }),
  member: z.object({ display_name: z.string(), is_super_admin: z.boolean() }),
  os_url: z.string().nullable(),
  /** The card app.<domain>/ opens after sign-in (db/142). */
  default_application_id: z.number().int().nullable().default(null),
  applications: z.array(launcherApplication),
});
export type LauncherApplication = z.infer<typeof launcherApplication>;
