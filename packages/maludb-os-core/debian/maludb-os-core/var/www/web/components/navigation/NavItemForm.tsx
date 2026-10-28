"use client";

import ActionForm, { ActionOutcome } from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import SubmitButton from "@/components/kit/SubmitButton";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";
import type { NavigationItemData } from "@/lib/schemas/navigation";

const STATUS_HELP: Record<string, string> = {
  active: "In the menu.",
  hidden: "Out of the menu; still works by address, for agents and for MCP.",
  disabled: "Switched off for the whole business — closed to people, agents and MCP. Nothing is deleted.",
};

const OPENS = [
  { id: "same", name: "This tab", help: "The page replaces the one the person is on." },
  { id: "new_tab", name: "A new tab", help: "The platform stays open behind it — for another system." },
] as const;

/**
 * Menu entry form (screens `navigation-item` and `navigation-item-add`). Every entry: name, icon,
 * group, status. A link (added here) and an external application's entry: also the address — a
 * path of ours or a full web address — and whether it opens in this tab or a new one. A built-in
 * application's address is its own and is shown, not edited. A link can be removed from here.
 */
export default function NavItemForm({ data, back = null }: { data: NavigationItemData; back?: string | null }) {
  const { item: i, options } = data;
  const list = "/settings/navigation";   // an entry has no page of its own: Cancel and a save land on the menu (R5)
  const { state, pending, onSubmit } = useRecordForm("/settings/navigation/item-save.php", back);
  const adding = i === null;
  const addressEditable = adding || i.address_editable;
  const open = i ? i.siblings.filter((s) => s.status !== "disabled").map((s) => s.label) : [];
  const statuses = i ? i.allowed_statuses : [{ id: "active", name: "Active" }, { id: "hidden", name: "Hidden" }];
  const title = adding ? "Add a menu entry" : `Edit ${i.label}`;

  return (
    <>
      <PageHeader title={title} id="navigation-item-form"
                  crumbs={[{ label: "Settings", href: "/settings" }, { label: "Navigation", href: list }, { label: adding ? "Add" : i.label }]}
                  back={{ href: list, label: "Navigation" }}>
        <Link href={back ?? list} id="navigation-item-form-cancel" className="btn btn-light-brand">Cancel</Link>
        <button type="submit" form="navigation-item-form-el" id="navigation-item-form-save" className="btn btn-primary" disabled={pending}>
          <i className="feather-check me-2"></i><span>{pending ? "Saving…" : adding ? "Add to the menu" : "Save"}</span>
        </button>
      </PageHeader>

      <div className="main-content" data-screen={adding ? "navigation-item-add" : "navigation-item"}>
        <ActionOutcome state={state} id="navigation-item-form-errors" />
        <div className="row">
          <div className="col-lg-8">
            <div className="card stretch stretch-full">
              <div className="card-body">
                <form id="navigation-item-form-el" onSubmit={onSubmit}>
                  {i && <input type="hidden" name="item" value={i.id} />}
                  <FieldRow label="Name in the menu" htmlFor="navigation-item-form-field-label">
                    <input type="text" className="form-control" id="navigation-item-form-field-label" name="label" defaultValue={i?.label ?? ""} maxLength={40} required />
                  </FieldRow>
                  <FieldRow label="Icon" htmlFor="navigation-item-form-field-icon">
                    <input type="text" className="form-control" id="navigation-item-form-field-icon" name="icon" defaultValue={i?.icon ?? "feather-link"}
                           pattern="feather-[a-z0-9\-]{1,40}" maxLength={48} required />
                    <div className="form-text">A Feather icon name, like <code>feather-briefcase</code>.</div>
                  </FieldRow>
                  <FieldRow label="Group" htmlFor="navigation-item-form-field-group">
                    <select className="form-select" id="navigation-item-form-field-group" name="group" defaultValue={i?.group_id ?? data.group_id ?? options.groups[0]?.id} required>
                      {options.groups.map((g) => <option value={g.id} key={g.id}>{g.name || "No heading (top of the menu)"}</option>)}
                    </select>
                    <div className="form-text">{adding ? "A new entry goes to the end of its group." : "Moved to another group, it goes to the end of it."}</div>
                  </FieldRow>
                  {addressEditable ? (
                    <>
                      <FieldRow label="Address" htmlFor="navigation-item-form-field-url">
                        <input type="text" className="form-control" id="navigation-item-form-field-url" name="url" defaultValue={i?.url ?? ""}
                               maxLength={2000} required placeholder="/reports/sales or https://example.com/" inputMode="url" />
                        <div className="form-text">A page of ours, like <code>/reports</code>, or a full web address starting with <code>https://</code>.</div>
                      </FieldRow>
                      <FieldRow label="Opens in" htmlFor="navigation-item-form-field-opens-same">
                        {OPENS.map((o) => (
                          <div className="form-check mb-2" key={o.id}>
                            <input className="form-check-input" type="radio" name="opens" value={o.id} id={`navigation-item-form-field-opens-${o.id}`}
                                   defaultChecked={(i?.opens ?? "same") === o.id} />
                            <label className="form-check-label" htmlFor={`navigation-item-form-field-opens-${o.id}`}>
                              <span className="fw-semibold">{o.name}</span> <span className="text-muted">— {o.help}</span>
                            </label>
                          </div>
                        ))}
                      </FieldRow>
                    </>
                  ) : (
                    <FieldRow label="Address" htmlFor="navigation-item-form-field-url">
                      <input type="text" className="form-control" id="navigation-item-form-field-url" value={i.url} readOnly disabled />
                      <div className="form-text">The address of a built-in application is its own. To open somewhere else, add a link and hide this entry.</div>
                    </FieldRow>
                  )}
                  <FieldRow label="Status" htmlFor="navigation-item-form-field-status">
                    {statuses.map((s) => (
                      <div className="form-check mb-2" key={s.id}>
                        <input className="form-check-input" type="radio" name="status" value={s.id} id={`navigation-item-form-field-status-${s.id}`}
                               defaultChecked={(i?.status ?? "active") === s.id} />
                        <label className="form-check-label" htmlFor={`navigation-item-form-field-status-${s.id}`}>
                          <span className="fw-semibold">{s.name}</span> <span className="text-muted">— {STATUS_HELP[s.id]}</span>
                        </label>
                      </div>
                    ))}
                    {i?.is_locked && <div className="form-text">Always active: it is how people find their way back.</div>}
                    {(adding || i.is_link) && <div className="form-text">A link can be active or hidden — there is nothing of its own to switch off.</div>}
                    {i && !i.is_locked && !i.is_link && i.allowed_statuses.length === 2 && (
                      <div className="form-text">Part of the platform itself, so it can leave the menu but there is nothing to switch off.</div>
                    )}
                    {open.length > 0 && statuses.length === 3 && (
                      <div className="form-text">Shares its module with {open.join(" and ")}: the module closes only when all of them are disabled.</div>
                    )}
                  </FieldRow>
                </form>
              </div>
            </div>
          </div>
          <div className="col-lg-4">
            <div className="card stretch stretch-full" id="navigation-item-facts">
              <div className="card-header"><h5 className="card-title">{adding || i.is_link ? "A link" : "The application"}</h5></div>
              <div className="card-body fs-12">
                {adding ? (
                  <p className="mb-0 text-muted">A link is an entry of your own: any page of the platform, or another system on the web. It belongs to no application, so it admits everyone who can see the menu.</p>
                ) : (
                  <dl className="mb-0">
                    <dt className="text-muted fw-medium">Application</dt><dd>{i.application_name
                      ? (i.application_id !== null ? <Link href={`/applications/${i.application_id}`}>{i.application_name}</Link> : i.application_name)
                      : "— (a link)"}{i.is_builtin && !i.is_link ? " (built in)" : ""}</dd>
                    <dt className="text-muted fw-medium">Opens</dt><dd>{i.url}{i.opens === "new_tab" ? " — in a new tab" : ""}</dd>
                    <dt className="text-muted fw-medium">Who is admitted</dt>
                    <dd className="mb-0">
                      {i.audience === "admin" ? "Admins" : i.audience === "internal" ? "Everyone inside the business" : i.module ? `Holders of the ${i.module} grant, and admins` : "Everyone"}
                    </dd>
                  </dl>
                )}
              </div>
              {i?.deletable && (
                <div className="card-footer">
                  <ActionForm path="/settings/navigation/item-delete.php" follow confirm={`Remove ${i.label} from the menu? Nothing else is touched.`} id="navigation-item-delete-form">
                    <input type="hidden" name="item" value={i.id} />
                    <SubmitButton className="btn btn-sm btn-light-brand text-danger" id="navigation-item-delete-btn"><i className="feather-trash-2 me-2"></i>Remove from the menu</SubmitButton>
                  </ActionForm>
                </div>
              )}
              {i && !i.deletable && !i.is_locked && (
                <div className="card-footer fs-12 text-muted">Part of the platform: it cannot be removed, only hidden.</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
