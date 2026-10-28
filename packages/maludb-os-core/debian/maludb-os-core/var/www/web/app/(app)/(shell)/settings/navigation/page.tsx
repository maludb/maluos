import type { Metadata } from "next";
import ActionForm from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import SubmitButton from "@/components/kit/SubmitButton";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { navigationScreen, type NavSettingsItem } from "@/lib/schemas/navigation";

export const metadata: Metadata = { title: "Navigation · Settings" };

const AUDIENCE: Record<NavSettingsItem["audience"], string> = { everyone: "", internal: "Not for external members", admin: "Admins only" };

/**
 * Screen `navigation-settings` — the whole menu as the super-admin arranges it: groups, the
 * entries in them, and each application's status (docs/build-specs/data-driven-nav.md).
 * Data: GET /settings/navigation/ (super-admin only). Born after the cut-over: no PHP template.
 */
export default async function NavigationSettingsPage() {
  const here = await herePath();
  return renderScreen("/settings/navigation/", navigationScreen, ({ groups }) => (
    <>
      <PageHeader title="Navigation" id="navigation-settings" crumbs={[{ label: "Settings", href: "/settings" }, { label: "Navigation" }]} />

      <div className="main-content" data-screen="navigation-settings">
        <div className="row">
          <div className="col-12">
            <div className="alert alert-info fs-12 mb-4" id="navigation-status-help" role="note">
              <strong>Active</strong> — in the menu. <strong>Hidden</strong> — out of the menu; still works for people who
              have the address, for agents and for MCP. <strong>Disabled</strong> — switched off for the whole business:
              out of the menu and closed to people, agents and MCP. Nothing is ever deleted; switch it back and it is all there.
            </div>
          </div>

          {groups.map((g, gi) => (
            <div className="col-12" key={g.id}>
              <div className="card stretch stretch-full" id={`nav-group-card-${g.id}`}>
                <div className="card-header d-flex flex-wrap align-items-center gap-2">
                  <ActionForm path="/settings/navigation/group-save.php" className="d-flex flex-wrap align-items-center gap-2 flex-grow-1">
                    <input type="hidden" name="group" value={g.id} />
                    <input type="text" name="name" defaultValue={g.name} maxLength={40} className="form-control form-control-sm w-auto flex-grow-1"
                           style={{ maxWidth: 280 }} aria-label="Group heading" placeholder="No heading — sits at the top" id={`nav-group-name-${g.id}`} />
                    <SubmitButton className="btn btn-sm btn-light-brand">Rename</SubmitButton>
                  </ActionForm>
                  <span className="d-inline-flex gap-1">
                    <Link href={withBack(`/settings/navigation/items/new?group=${g.id}`, here)} className="btn btn-sm btn-light-brand" id={`nav-group-add-item-${g.id}`}>
                      <i className="feather-plus me-1"></i>Add entry
                    </Link>
                    <MoveButtons path="/settings/navigation/group-move.php" field="group" id={g.id} first={gi === 0} last={gi === groups.length - 1} what={g.name || "the top group"} />
                    {g.items.length === 0 && (
                      <ActionForm path="/settings/navigation/group-delete.php" confirm={`Remove the group ${g.name}?`}>
                        <input type="hidden" name="group" value={g.id} />
                        <SubmitButton className="btn btn-sm btn-light-brand text-danger">Remove</SubmitButton>
                      </ActionForm>
                    )}
                  </span>
                </div>
                <div className="card-body p-0">
                  {g.items.length === 0 ? (
                    <div className="text-center text-muted py-4 fs-12">Nothing in this group. Add an entry, move one here from its Edit page, or remove the group.</div>
                  ) : (
                    <ul className="list-group list-group-flush" id={`nav-group-items-${g.id}`}>
                      {g.items.map((i, ii) => (
                        <li className="list-group-item d-flex flex-wrap align-items-center gap-2 py-3" id={`nav-item-row-${i.id}`} key={i.id}>
                          <div className="d-flex align-items-center gap-3 flex-grow-1" style={{ minWidth: 200 }}>
                            <i className={`${i.icon} fs-16 ${i.status === "active" ? "text-primary" : "text-muted"}`}></i>
                            <div>
                              <div className={`fw-semibold ${i.status === "active" ? "text-dark" : "text-muted"}`}>
                                {i.label}
                                {i.opens === "new_tab" && <i className="feather-external-link fs-11 ms-2 opacity-50" title="Opens in a new tab"></i>}
                                {i.is_locked && <i className="feather-lock fs-11 ms-2 opacity-50" title="Always active"></i>}
                              </div>
                              <div className="fs-11 text-muted">
                                {i.url}{AUDIENCE[i.audience] ? ` · ${AUDIENCE[i.audience]}` : ""}
                              </div>
                            </div>
                          </div>
                          <StatusPicker item={i} />
                          <span className="d-inline-flex gap-1">
                            <MoveButtons path="/settings/navigation/item-move.php" field="item" id={i.id} first={ii === 0} last={ii === g.items.length - 1} what={i.label} />
                            <Link href={withBack(`/settings/navigation/items/${i.id}`, here)} className="btn btn-sm btn-light-brand" id={`nav-item-edit-${i.id}`}>Edit</Link>
                            {i.deletable && (
                              <ActionForm path="/settings/navigation/item-delete.php" confirm={`Remove ${i.label} from the menu? Nothing else is touched.`}>
                                <input type="hidden" name="item" value={i.id} />
                                <SubmitButton className="btn btn-sm btn-light-brand text-danger px-2" ariaLabel={`Remove ${i.label}`} id={`nav-item-delete-${i.id}`}><i className="feather-trash-2"></i></SubmitButton>
                              </ActionForm>
                            )}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          ))}

          <div className="col-lg-6">
            <div className="card stretch stretch-full" id="nav-group-add-card">
              <div className="card-header"><h5 className="card-title">Add a group</h5></div>
              <div className="card-body">
                <ActionForm path="/settings/navigation/group-save.php" id="nav-group-add-form" resetOnSuccess className="d-flex flex-wrap gap-2">
                  <input type="text" name="name" id="nav-group-add-field-name" className="form-control w-auto flex-grow-1" maxLength={40} required
                         placeholder="Heading, e.g. Marketing" aria-label="Heading" />
                  <SubmitButton className="btn btn-primary" id="nav-group-add-btn"><i className="feather-plus me-2"></i>Add group</SubmitButton>
                </ActionForm>
                <p className="fs-12 text-muted mt-3 mb-0">A new group goes last and stays out of the menu until it holds an active entry. Each group's <strong>Add entry</strong> adds a link there: any page of ours or a full web address, opening in this tab or a new one.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  ));
}

const STATUS_TONE: Record<NavSettingsItem["status"], string> = { active: "success", hidden: "warning", disabled: "danger" };

/**
 * The three statuses as one row of buttons; the current one is filled. Only the statuses this
 * entry may take are offered (a locked entry shows its one). Disabling asks first — and says
 * what it will and will not close, because entries can share a module.
 */
function StatusPicker({ item: i }: { item: NavSettingsItem }) {
  if (i.allowed_statuses.length === 1) {
    return <span className="badge bg-soft-success text-success" id={`nav-item-status-${i.id}`}>Always active</span>;
  }
  const open = i.siblings.filter((s) => s.status !== "disabled").map((s) => s.label);
  const warning = i.is_builtin
    ? open.length > 0
      ? `Disable ${i.label}? It leaves the menu, but its module stays open because ${open.join(" and ")} shares it — disable that too to close it.`
      : `Disable ${i.label}? It is switched off for the whole business: out of the menu and closed to people, agents and MCP. Nothing is deleted.`
    : `Disable ${i.label}? It leaves everyone's menu.`;
  return (
    <span className="d-inline-flex gap-1" id={`nav-item-status-${i.id}`} role="group" aria-label={`Status of ${i.label}`}>
      {i.allowed_statuses.map((s) => (
        <ActionForm path="/settings/navigation/item-status.php" key={s.id} confirm={s.id === "disabled" && i.status !== "disabled" ? warning : undefined}>
          <input type="hidden" name="item" value={i.id} />
          <input type="hidden" name="status" value={s.id} />
          <SubmitButton className={`btn btn-sm ${i.status === s.id ? `btn-${STATUS_TONE[s.id]}` : "btn-light-brand"}`} disabled={i.status === s.id}>
            {s.name}
          </SubmitButton>
        </ActionForm>
      ))}
    </span>
  );
}

function MoveButtons({ path, field, id, first, last, what }: { path: string; field: string; id: number; first: boolean; last: boolean; what: string }) {
  return (
    <>
      {(["up", "down"] as const).map((direction) => (
        <ActionForm path={path} key={direction}>
          <input type="hidden" name={field} value={id} />
          <input type="hidden" name="direction" value={direction} />
          <SubmitButton className="btn btn-sm btn-light-brand px-2" disabled={direction === "up" ? first : last} ariaLabel={`Move ${what} ${direction}`}>
            <i className={`feather-arrow-${direction}`}></i>
          </SubmitButton>
        </ActionForm>
      ))}
    </>
  );
}
