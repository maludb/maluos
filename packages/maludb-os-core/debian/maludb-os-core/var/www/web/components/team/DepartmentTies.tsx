import Link from "@/components/kit/Link";
import { withBack } from "@/lib/routes";
import type { DepartmentTie } from "@/lib/schemas/team";

/** Where one row of a tie is looked after; null = nowhere to go (the row is only named). */
function tieHref(key: string, id: number): string | null {
  switch (key) {
    case "manager": case "people": case "past_memberships": return `/team/${id}`;
    case "agents": return `/agents/${id}`;
    case "approval_policies": return `/settings/approval-policies/${id}/edit`;
    case "child_departments": return `/team/departments/${id}`;
    case "owned_applications": case "serving_applications": case "access_grants": return `/applications/${id}`;
    case "open_invitations": return "/team/invitations";
    case "ledger_lines": return "/ai/spend/statements";
    case "eval_sets": return `/ai/evals/${id}`;
    case "skill_assignments": return "/skills";
    default: return null;
  }
}

/** What to do about a blocker, said on the Edit page beside the refusal. */
const REMEDY: Record<string, string> = {
  manager: "clear the Manager field below and save",
  people: "remove them on the department page, or move them to another department",
  agents: "remove them on the department page, or move them to another department",
  child_departments: "give each one another parent department on its Edit page",
  owned_applications: "name another owning department on each application",
  serving_applications: "remove this department's scope on each application",
  open_invitations: "revoke them under Invitations",
  ledger_lines: "these are AI spend posted to the department — ledger history is kept, so the department stays",
  eval_sets: "move each eval set to another department, or delete it",
};

function TieItems({ tie, here = null }: { tie: DepartmentTie; here?: string | null }) {
  if (tie.items.length === 0) return <span className="text-muted">none</span>;
  return (
    <>
      {tie.items.map((i, n) => {
        const href = tieHref(tie.key, i.id);
        return (
          <span key={`${i.id}-${n}`}>
            {n > 0 && ", "}
            {href ? <Link href={withBack(href, here)}>{i.name}</Link> : i.name}
            {i.detail && <span className="text-muted"> ({i.detail})</span>}
          </span>
        );
      })}
    </>
  );
}

/**
 * The department page's whole picture of what names the department: first what a delete waits on
 * (every kind listed, "none" when empty), then what would go with it. The same rows
 * department_delete_blockers() counts, so the page and the refusal never differ.
 */
export default function DepartmentTies({ ties, isSystem, canDelete, here = null }: { ties: DepartmentTie[]; isSystem: boolean; canDelete: boolean; here?: string | null }) {
  const blocking = ties.filter((t) => t.blocks);
  const going = ties.filter((t) => !t.blocks);
  const waiting = blocking.filter((t) => t.items.length > 0);
  return (
    <div className="card stretch stretch-full" id="department-view-ties-card">
      <div className="card-header"><h5 className="card-title">What is tied to it</h5></div>
      <div className="card-body">
        <p className="mb-3" id="department-view-delete-status">
          {isSystem ? (
            <span className="text-muted">A standing department — renameable, never deleted.</span>
          ) : waiting.length === 0 ? (
            <span className="badge bg-soft-success text-success">Nothing blocks a delete</span>
          ) : (
            <span className="badge bg-soft-warning text-warning">
              Delete waits on {waiting.length} {waiting.length === 1 ? "thing" : "things"}: {waiting.map((t) => t.label.toLowerCase()).join(", ")}
            </span>
          )}
          {!isSystem && !canDelete && <span className="text-muted fs-12 ms-2">Only the super-admin deletes a department.</span>}
        </p>
        <h6 className="fs-12 text-uppercase text-muted mb-2">Blocks a delete</h6>
        <dl className="row mb-3 fs-13" id="department-view-blocking">
          {blocking.map((t) => (
            <div key={t.key} id={`department-tie-${t.key}`} style={{ display: "contents" }}>
              <dt className={`col-sm-4 ${t.items.length > 0 ? "text-warning" : "text-muted"} fw-normal`}>
                {t.label}{t.items.length > 0 && ` (${t.items.length})`}
              </dt>
              <dd className="col-sm-8"><TieItems tie={t} here={here} /></dd>
            </div>
          ))}
        </dl>
        <h6 className="fs-12 text-uppercase text-muted mb-2">Goes with it if deleted</h6>
        <dl className="row mb-0 fs-13" id="department-view-cascade">
          {going.map((t) => (
            <div key={t.key} id={`department-tie-${t.key}`} style={{ display: "contents" }}>
              <dt className="col-sm-4 text-muted fw-normal">{t.label}{t.items.length > 0 && ` (${t.items.length})`}</dt>
              <dd className="col-sm-8"><TieItems tie={t} here={here} /></dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

/**
 * On the Edit page, beside a disabled Delete: each thing the delete waits on, its rows, and what
 * to do about it.
 */
export function DeleteBlockers({ ties }: { ties: DepartmentTie[] }) {
  const waiting = ties.filter((t) => t.blocks && t.items.length > 0);
  if (waiting.length === 0) return null;
  return (
    <div className="alert alert-warning fs-12 mb-3" id="department-form-delete-blockers">
      <div className="fw-semibold mb-1"><i className="feather-info me-2"></i>Delete is unavailable until these are cleared:</div>
      <ul className="mb-0 ps-3">
        {waiting.map((t) => (
          <li key={t.key} id={`department-blocker-${t.key}`}>
            <strong>{t.label}</strong> — <TieItems tie={t} />. <span className="text-muted">To clear: {REMEDY[t.key] ?? "remove them first"}.</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
