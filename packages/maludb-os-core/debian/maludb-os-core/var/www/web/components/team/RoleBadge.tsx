const ROLE: Record<string, [string, string]> = {
  super_admin: ["Super-admin", "danger"], dept_admin: ["Dept-admin", "warning"], user: ["User", "secondary"],
};

/** The three business roles, as both team templates badge them. */
export default function RoleBadge({ role }: { role: string }) {
  const [label, color] = ROLE[role] ?? ROLE.user;
  return <span className={`badge bg-soft-${color} text-${color}`}>{label}</span>;
}
