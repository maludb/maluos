import { z } from "zod";

/** The contract with app/features/skills/present.php (the skill library, AI Ops → Skills) — change both together. */
const version = z.object({ id: z.number().int(), version: z.string(), enabled: z.boolean(), created_at: z.string(), description: z.string() });

export const skillLibrary = z.object({
  skills: z.array(z.object({
    name: z.string(), kind: z.string().default("skill"), description: z.string(), current: version, enabled: z.boolean(),
    version_count: z.number().int(), assignment_count: z.number().int(),
  })),
  can: z.object({ edit: z.boolean() }),
});

export const skillLibraryView = z.object({
  skill: z.object({
    name: z.string(),
    versions: z.array(version),
    chosen: version,
    current_id: z.number().int(),
    markdown: z.string(),
    kind: z.string().default("skill"),
    body: z.string(),
    bundle_hash: z.string(),
    files: z.array(z.object({ path: z.string(), size: z.number().int(), content: z.string().nullable() })),
    assignments: z.array(z.object({
      skill_assignment_id: z.number().int(), scope_kind: z.string(), pinned_bundle_hash: z.string().nullable(),
      department: z.object({ id: z.number().int(), name: z.string().nullable() }).nullable(),
      role_key: z.string().nullable(),
      agent: z.object({ member_id: z.number().int(), name: z.string().nullable() }).nullable(),
      application: z.object({ id: z.number().int(), name: z.string().nullable() }).nullable().default(null),
    })),
  }),
  can: z.object({ edit: z.boolean() }),
});
export type SkillLibraryView = z.infer<typeof skillLibraryView>;
