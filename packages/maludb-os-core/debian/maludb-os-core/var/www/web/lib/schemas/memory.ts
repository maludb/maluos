import { z } from "zod";

/** The contract with app/features/memory/present.php and html/memory/{index,core}.php — change both together. */
const id = z.number().int();

export const memoryResult = z.object({
  text: z.string(),
  about: z.string().nullable(),
  from: z.string(),
  from_kind: z.enum(["self", "department", "org"]),
  department_id: id.nullable().default(null),
});
export type MemoryResult = z.infer<typeof memoryResult>;

const departments = z.array(z.object({ id, name: z.string() }));
export type MemoryDepartments = z.infer<typeof departments>;

export const memoryScreen = z.object({
  search: z.object({ q: z.string(), subject: z.string(), scope: z.enum(["all", "self", "department", "org"]), asked: z.boolean() }),
  searched: z.array(z.string()),
  results: z.array(memoryResult),
  note: z.string().nullable(),
  memory_available: z.boolean(),
  memory_error: z.string().nullable(),
  me: z.object({ member_id: id }),
  agents: z.array(z.object({ member_id: id, name: z.string(), job_title: z.string().nullable() })),
  options: z.object({ departments }),
  can: z.object({ remember_org: z.boolean() }),
});

export const coreMemoryScreen = z.object({
  member: z.object({ member_id: id, name: z.string(), is_agent: z.boolean(), is_me: z.boolean() }),
  entries: z.array(z.object({ key: z.string(), value: z.string(), note: z.string().nullable(), updated_at: z.string().nullable() })),
  memory_available: z.boolean(),
  memory_error: z.string().nullable(),
  can: z.object({ set: z.boolean() }),
});
