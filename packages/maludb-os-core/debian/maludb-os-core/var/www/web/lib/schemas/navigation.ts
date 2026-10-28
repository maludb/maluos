import { z } from "zod";

/** The contract with app/features/navigation/present.php — change both together. */
const id = z.number().int();
const option = z.object({ id, name: z.string() });

export const navStatus = z.enum(["active", "hidden", "disabled"]);

export const navItem = z.object({
  id,
  key: z.string(),
  group_id: id,
  label: z.string(),
  icon: z.string(),
  url: z.string(),
  opens: z.enum(["same", "new_tab"]),
  module: z.string().nullable(),
  audience: z.enum(["everyone", "internal", "admin"]),
  status: navStatus,
  status_label: z.string(),
  is_locked: z.boolean(),
  is_builtin: z.boolean(),
  /** Added on the settings screen; belongs to no application. */
  is_link: z.boolean(),
  /** The address and open-in are the entry's own (a link, or an external application's entry). */
  address_editable: z.boolean(),
  deletable: z.boolean(),
  application_name: z.string().nullable(),
  /** Step 2 (additive): the application's id, so the entry links it. */
  application_id: z.number().int().nullable().default(null),
  allowed_statuses: z.array(z.object({ id: navStatus, name: z.string() })),
  siblings: z.array(z.object({ label: z.string(), status: navStatus })),
});
export type NavSettingsItem = z.infer<typeof navItem>;

export const navigationScreen = z.object({
  groups: z.array(z.object({ id, name: z.string(), items: z.array(navItem) })),
  options: z.object({ groups: z.array(option) }),
});

/** `item` is null for the add page; `group_id` then carries the preselected group, if any. */
export const navigationItemScreen = z.object({
  item: navItem.nullable(),
  group_id: id.nullable().optional(),
  options: z.object({ groups: z.array(option) }),
});
export type NavigationItemData = z.infer<typeof navigationItemScreen>;
