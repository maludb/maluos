import { z } from "zod";
import { defaultApplication } from "./settings";

/** The contract with app/features/team/present.php — change both together. */
const id = z.number().int();
const option = z.object({ id, name: z.string() });
const memberOption = z.object({ id, name: z.string(), kind: z.string() });

export const teamMemberRow = z.object({
  id,
  display_name: z.string(),
  kind: z.string(),
  business_role: z.string(),
  departments: z.array(z.string()),
  /** Step 3 (db/151): the same departments with their ids, so the list links them. */
  department_links: z.array(z.object({ id, name: z.string() })).default([]),
  email: z.string().nullable(),
});

export const teamMember = teamMemberRow.extend({
  job_title: z.string().nullable(),
  status: z.string().nullable(),
  timezone: z.string().nullable(),
  phone: z.string().nullable().default(null),
  has_2fa: z.boolean().nullable(),
  last_login_display: z.string().nullable(),
});

export const memberDepartment = z.object({ id, name: z.string(), is_admin: z.boolean(), is_primary: z.boolean() });
export const moduleAccess = z.object({ key: z.string(), label: z.string(), access: z.string() });

export const teamList = z.object({
  members: z.array(teamMemberRow),
  pagination: z.object({ page: id, total_pages: id, total: id }),
  filters: z.object({ q: z.string(), kind: z.string(), role: z.string(), department: z.string() }),
  options: z.object({ departments: z.array(option) }),
});

export const memberView = z.object({
  member: teamMember,
  departments: z.array(memberDepartment),
  modules: z.array(moduleAccess),
  /** Applications and scopes a grant reaches them through (db/141). */
  applications: z.array(z.object({
    id, name: z.string(), scope: z.string().nullable(), role: z.string().nullable(), capability: z.string(), route: z.string(),
    /** Step 3: what the route goes through — a department or a location — and the scope's own target. */
    route_department_id: id.nullable().default(null), route_location_id: id.nullable().default(null),
    scope_location_id: id.nullable().default(null), scope_department_id: id.nullable().default(null),
  })).default([]),
  /** Where app.<domain>/ takes them after sign-in (db/142); null for an agent. */
  default_application: defaultApplication.nullable().default(null),
  can: z.object({
    admin: z.boolean(), set_default_application: z.boolean().default(false),
    update: z.boolean().default(false), suspend: z.boolean().default(false), reinstate: z.boolean().default(false),
  }),
});

/** A live application grant reaching a member (present_member_application_grant()); route = member | department | residents. */
export const memberApplicationGrant = z.object({
  id,
  application_id: id,
  application_name: z.string(),
  route: z.enum(["member", "department", "residents"]),
  through_id: id.nullable(),
  through_name: z.string().nullable(),
  scope_name: z.string().nullable(),
  role_key: z.string().nullable(),
  role_name: z.string().nullable(),
  capability: z.string(),
  expires_at: z.string().nullable(),
  /** Every role the grant gives (db/145). */
  roles: z.array(z.object({ key: z.string(), name: z.string(), withdrawn: z.boolean() })).default([]),
});
export type MemberApplicationGrant = z.infer<typeof memberApplicationGrant>;

/** An application that can be granted, with its roles and the sites or departments it serves (present_grantable_application()). */
export const grantableApplication = z.object({
  id,
  name: z.string(),
  scope_kind: z.string(),
  roles: z.array(z.object({
    key: z.string(), name: z.string(), capability: z.string(),
    description: z.string().nullable().default(null),
    rights: z.array(z.object({ key: z.string(), description: z.string() })).default([]),
  })),
  scopes: z.array(option),
});
export type GrantableApplication = z.infer<typeof grantableApplication>;

export const memberAccess = z.object({
  member: teamMember,
  departments: z.array(memberDepartment),
  modules: z.array(moduleAccess),
  application_grants: z.array(memberApplicationGrant).default([]),
  application_options: z.array(grantableApplication).default([]),
  options: z.object({ departments: z.array(option) }),
  can: z.object({
    set_role: z.boolean(), update: z.boolean().default(false),
    manage_applications: z.boolean().default(false), kernel_modules: z.boolean().default(true),
  }),
  timezones: z.array(z.string()).default([]),
});

export const department = z.object({
  id: id.nullable(),
  name: z.string(),
  description: z.string().nullable(),
  handbook_markdown: z.string().nullable(),
  parent_id: id.nullable(),
  parent_name: z.string().nullable(),
  manager_member_id: id.nullable(),
  manager_name: z.string().nullable(),
  home_location_id: id.nullable(),
  home_location_name: z.string().nullable(),
  member_count: id,
  monthly_budget_amount: z.string().nullable(),
  budget_currency: z.string().nullable(),
  budget_display: z.string().nullable(),
  is_system: z.boolean(),
  system_key: z.string().nullable(),
});

export const departmentsList = z.object({ departments: z.array(department) });

/** Everything of one kind that names a department (present_department_tie()); `blocks` = the delete waits on it. */
export const departmentTie = z.object({
  key: z.string(),
  label: z.string(),
  blocks: z.boolean(),
  items: z.array(z.object({ id, name: z.string(), detail: z.string().nullable() })),
});
export type DepartmentTie = z.infer<typeof departmentTie>;

export const departmentView = z.object({
  department,
  members: z.array(z.object({
    id, name: z.string(), kind: z.string(), is_admin: z.boolean(), is_primary: z.boolean(),
    applications: z.array(z.object({ id, name: z.string(), capability: z.string() })),
  })),
  applications: z.array(z.object({
    id, name: z.string(), status: z.string(), tie: z.enum(["owns", "serves", "granted"]),
    role: z.string().nullable(), capability: z.string().nullable(), scope_name: z.string().nullable(),
  })),
  options: z.object({ members: z.array(memberOption) }),
  can: z.object({ delete: z.boolean() }),
  delete_blockers: z.array(z.string()),
  ties: z.array(departmentTie).default([]),
});

export const departmentFormData = z.object({
  department,
  selected_parent_id: id.nullable(),
  selected_location_id: id.nullable(),
  options: z.object({
    members: z.array(memberOption),
    departments: z.array(option),
    locations: z.array(z.object({ id, name: z.string(), kind: z.string(), siting: z.string().nullable() })),
  }),
  can: z.object({ delete: z.boolean() }),
  delete_blockers: z.array(z.string()),
  ties: z.array(departmentTie).default([]),
});
export type DepartmentFormData = z.infer<typeof departmentFormData>;
