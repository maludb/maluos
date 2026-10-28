import { z } from "zod";

/** The contract with app/features/applications/present.php — change both together. */
const id = z.number().int();
const named = z.object({ id, name: z.string() });
const health = z.object({ status: z.string(), detail: z.string() });

/** One card of the inventory: a registered application, or a catalog entry nothing carries (id null). */
export const applicationCard = z.object({
  key: z.string(), id: id.nullable(), catalog_key: z.string().nullable(), name: z.string(),
  description: z.string().nullable(), icon: z.string(), vendor: z.string().nullable(), is_builtin: z.boolean(),
  state: z.enum(["active", "off", "planned", "available", "retired"]), status: z.string().nullable(),
  health: health.nullable(), owner_department_name: z.string().nullable(), expert_name: z.string().nullable(),
  /** Step 2 (additive): the ids beside the names, so the card links them. */
  owner_department_id: id.nullable().default(null), expert_member_id: id.nullable().default(null),
  skill_count: id, endpoint_count: id, has_agent_mcp: z.boolean(), gaps: z.array(z.string()),
  /** The card's business area by name — shown on the running cards, which stand outside the areas. */
  business_area: z.string().default(""),
  /** Where "Open" launches the application: /launch/<id> (the hand-off) or its own address; null when it cannot launch. */
  open_url: z.string().nullable().default(null),
});
export type ApplicationCard = z.infer<typeof applicationCard>;

export const applicationsList = z.object({
  /** What runs, across every business area, by name; `areas` holds everything else. */
  running: z.array(applicationCard),
  areas: z.array(z.object({ id: id.nullable(), name: z.string(), applications: z.array(applicationCard) })),
  counts: z.object({ active: id, total: id }),
  filters: z.object({
    q: z.string(), area: z.string(), department: z.string(), health: z.string(),
    gaps: z.boolean(), active: z.boolean(), retired: z.boolean(),
  }),
  options: z.object({ areas: z.array(named), departments: z.array(named) }),
  can: z.object({ edit: z.boolean(), arrange_menu: z.boolean() }),
});

export const application = z.object({
  id: id.nullable(), name: z.string(), app_key: z.string().nullable(), category: z.string().nullable(),
  category_display: z.string(), description: z.string().nullable(), vendor: z.string().nullable(),
  is_self_hosted: z.boolean(), is_builtin: z.boolean(), location_id: id.nullable(), location_name: z.string().nullable(),
  siting: z.string().nullable(), owner_department_id: id.nullable(), owner_department_name: z.string().nullable(),
  owner_member_id: id.nullable(), owner_name: z.string().nullable(), url: z.string().nullable(),
  sso_path: z.string().nullable(), sso_logout_path: z.string().nullable(), directory_writes: z.boolean(),
  version: z.string().nullable(), criticality: z.string(), status: z.string(), health,
  notes: z.string().nullable(),
  catalog_key: z.string().nullable(), business_area_id: id.nullable(), business_area_name: z.string().nullable(),
  expert_member_id: id.nullable(), expert_name: z.string().nullable(),
  scope_kind: z.enum(["none", "location", "department"]).default("none"), scope_count: id.default(0),
});

export const endpoint = z.object({
  id: id.nullable(), name: z.string(), kind: z.string().nullable(), url: z.string().nullable(), auth_kind: z.string(),
  has_credential: z.boolean(), agent_reachable: z.boolean(), mcp_surface_version: z.string().nullable(), notes: z.string().nullable(),
});

export const accessGrant = z.object({
  id, grantee_kind: z.enum(["member", "department", "residents"]), grantee_name: z.string(), capability: z.string(),
  scope_id: id.nullable().default(null), scope_name: z.string().nullable().default(null),
  scope_location_id: id.nullable().default(null), scope_department_id: id.nullable().default(null),
  role_key: z.string().nullable().default(null), role_name: z.string().nullable().default(null),
  granted_by_display: z.string(), granted_at: z.string().nullable(), expires_at: z.string().nullable(),
  /** Step 2 (additive): who the grant is to, and who gave it. */
  member_id: id.nullable().default(null), member_kind: z.string().nullable().default(null),
  department_id: id.nullable().default(null), resident_location_id: id.nullable().default(null),
  granted_by_member_id: id.nullable().default(null),
  /** Every role the grant gives (db/145); `withdrawn` = the application no longer publishes it. */
  roles: z.array(z.object({ key: z.string(), name: z.string(), withdrawn: z.boolean() })).default([]),
});

export const applicationView = z.object({
  application,
  tab: z.enum(["overview", "endpoints", "access", "scopes", "expertise"]),
  gaps: z.array(z.string()),
  endpoints: z.array(endpoint),
  access: z.array(accessGrant),
  /** The application's own roles and the sites or departments it serves (db/141). */
  roles: z.array(z.object({
    key: z.string(), name: z.string(), capability: z.string(), is_admin: z.boolean(), live_grant_count: id,
    /** db/145: as the application publishes them (app_roles). */
    description: z.string().nullable().default(null),
    rights: z.array(z.object({ key: z.string(), description: z.string() })).default([]),
    withdrawn: z.boolean().default(false),
  })).default([]),
  /** When the roles were last read from the application itself; null = set by hand, or none. */
  roles_synced_at: z.string().nullable().default(null),
  /** Grants holding a role the application no longer publishes. */
  withdrawn_holdings: z.array(z.object({ grant_id: id, grantee: z.string(), role_key: z.string(), role_name: z.string(),
    grantee_member_id: id.nullable().default(null), grantee_member_kind: z.string().nullable().default(null),
    grantee_department_id: id.nullable().default(null), grantee_location_id: id.nullable().default(null) })).default([]),
  scopes: z.array(z.object({
    id, kind: z.enum(["location", "department"]), location_id: id.nullable(), department_id: id.nullable(), name: z.string(),
    address: z.string().nullable(), timezone: z.string().nullable(), live_grant_count: id, added_at: z.string().nullable(),
  })).default([]),
  retirement_counts: z.record(z.string(), z.number()),
  expertise: z.object({
    available: z.boolean(),
    skills: z.array(z.object({
      id, skill_name: z.string(), pinned_bundle_hash: z.string().nullable(), note: z.string().nullable(),
      created_at: z.string().nullable(), kind: z.string().default("skill"),
    })),
    agents: z.array(named),
    can_set_skills: z.boolean(),
    /** The agents a runbook or skill of this application can be given to, one at a time (owner, 2026-09-27). */
    agent_options: z.array(z.object({ id, name: z.string() })).default([]),
  }),
  options: z.object({
    members: z.array(z.object({ id, name: z.string(), kind: z.string() })),
    departments: z.array(named),
    capabilities: z.array(z.string()),
    sites: z.array(z.object({ id, name: z.string(), kind: z.string() })).default([]),
  }),
  kernel_token: z.object({ minted_at: z.string().nullable(), last_used_at: z.string().nullable() }).nullable(),
  can: z.object({
    edit: z.boolean(), manage_access: z.boolean(), mint_token: z.boolean(), set_roles: z.boolean().default(false),
    refresh_roles: z.boolean().default(false),
  }),
});
export type ApplicationView = z.infer<typeof applicationView>;

export const applicationFormData = z.object({
  application,
  options: z.object({
    categories: z.array(z.object({ value: z.string(), label: z.string() })),
    criticalities: z.array(z.string()),
    areas: z.array(named),
    locations: z.array(named), departments: z.array(named), owners: z.array(named),
  }),
});
export type ApplicationFormData = z.infer<typeof applicationFormData>;

export const endpointFormData = z.object({
  application: named,
  endpoint,
  options: z.object({ kinds: z.array(z.string()), auth_kinds: z.array(z.string()) }),
});
export type EndpointFormData = z.infer<typeof endpointFormData>;
