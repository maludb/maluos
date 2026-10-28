/** A role as the application published it (app_roles, db/145). */
export type PublishedRole = {
  key: string;
  name: string;
  capability: string;
  description?: string | null;
  rights?: { key: string; description: string }[];
};

/**
 * The roles a grant gives, as tick boxes posted as `roles[]` — several may be held, and the grant
 * amounts to the highest. Under each role, what it lets its holder do inside the application, in the
 * application's own words. `checked` pre-ticks the roles a grant already gives.
 */
export default function RoleChecklist({ roles, checked = [], idPrefix, compact = false }: {
  roles: PublishedRole[];
  checked?: string[];
  idPrefix: string;
  compact?: boolean;
}) {
  return (
    <div className="d-flex flex-column gap-1" id={`${idPrefix}-roles`}>
      {roles.map((r) => (
        <div className="form-check" key={r.key}>
          <input className="form-check-input" type="checkbox" name="roles[]" value={r.key}
                 id={`${idPrefix}-role-${r.key}`} defaultChecked={checked.includes(r.key)} />
          <label className="form-check-label" htmlFor={`${idPrefix}-role-${r.key}`}>
            <span className="fw-semibold">{r.name}</span> <span className="text-muted fs-11">({r.capability})</span>
            {!compact && r.description && <div className="fs-11 text-muted">{r.description}</div>}
            {!compact && r.rights && r.rights.length > 0 && (
              <ul className="fs-11 text-muted mb-0 ps-3">
                {r.rights.map((x) => <li key={x.key}>{x.description || x.key}</li>)}
              </ul>
            )}
          </label>
        </div>
      ))}
    </div>
  );
}
