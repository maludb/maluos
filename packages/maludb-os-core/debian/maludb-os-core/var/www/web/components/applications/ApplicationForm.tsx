"use client";

import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";
import { ucfirst } from "@/lib/format";
import type { ApplicationFormData } from "@/lib/schemas/applications";

/** Application form (screens `application-add` / `application-edit`) — app/views/applications/application-form.php. */
export default function ApplicationForm({ data, back: carried = null }: { data: ApplicationFormData; back?: string | null }) {
  const { application: a, options } = data;
  const isEdit = a.id !== null;
  // Where the form was opened from (click-around R5), else the application on edit and the list on create.
  const parent = isEdit ? `/applications/${a.id}` : "/applications";
  const back = carried ?? parent;
  const { state, pending, onSubmit } = useRecordForm("/applications/save.php", carried);
  const pick = (id: string, name: string, selected: number | null, items: { id: number; name: string }[]) => (
    <select className="form-select" id={id} name={name} defaultValue={selected ?? ""}>
      <option value="">— none —</option>
      {items.map((o) => <option value={o.id} key={o.id}>{o.name}</option>)}
    </select>
  );

  return (
    <>
      <PageHeader title={isEdit ? "Edit application" : "New application"} id="application-form"
                  crumbs={[{ label: "Applications", href: "/applications" }, ...(isEdit ? [{ label: a.name, href: parent }] : []), { label: isEdit ? "Edit" : "New" }]}
                  back={{ href: parent, label: isEdit ? "the application" : "Applications" }}>
        <Link href={back} id="application-form-cancel" className="btn btn-light-brand">Cancel</Link>
        <button type="submit" form="application-form" id="application-form-save" className="btn btn-primary" disabled={pending}>
          <i className="feather-check me-2"></i><span>{pending ? "Saving…" : "Save"}</span>
        </button>
      </PageHeader>

      <div className="main-content" data-screen={isEdit ? "application-edit" : "application-add"} data-entity="application" data-record-id={a.id ?? ""}>
        <ActionOutcome state={state} id="application-form-errors" />
        <div className="row">
          <div className="col-lg-8">
            <div className="card stretch stretch-full">
              <div className="card-body">
                <form id="application-form" onSubmit={onSubmit}>
                  {isEdit && <input type="hidden" name="application" value={a.id ?? ""} />}
                  {!isEdit && a.catalog_key && <input type="hidden" name="catalog_key" value={a.catalog_key} />}
                  <FieldRow label="Name" htmlFor="application-form-field-name">
                    <input type="text" className="form-control" id="application-form-field-name" name="name"
                           defaultValue={a.name} maxLength={200} required />
                  </FieldRow>
                  <FieldRow label="Key" htmlFor="application-form-field-app_key">
                    {isEdit ? (
                      <>
                        <input type="text" className="form-control" value={a.app_key ?? ""} disabled readOnly />
                        <div className="form-text">The key is fixed once an application is registered — endpoints, access and agent tool grants point at it.</div>
                      </>
                    ) : (
                      <>
                        <input type="text" className="form-control" id="application-form-field-app_key" name="app_key"
                               defaultValue={a.app_key ?? ""} maxLength={100} placeholder="data_lake" required />
                        <div className="form-text">Lowercase letters, digits and underscores, starting with a letter.</div>
                      </>
                    )}
                  </FieldRow>
                  <FieldRow label="Category" htmlFor="application-form-field-category">
                    <select className="form-select" id="application-form-field-category" name="category" required defaultValue={a.category ?? ""}>
                      <option value="">— choose —</option>
                      {options.categories.map((c) => <option value={c.value} key={c.value}>{c.label}</option>)}
                    </select>
                  </FieldRow>
                  <FieldRow label="Business area" htmlFor="application-form-field-business_area_id">
                    <select className="form-select" id="application-form-field-business_area_id" name="business_area_id"
                            defaultValue={a.business_area_id ?? ""}>
                      <option value="">— other —</option>
                      {options.areas.map((g) => <option value={g.id} key={g.id}>{g.name}</option>)}
                    </select>
                    <div className="form-text">Where the card sits on the Applications page.</div>
                  </FieldRow>
                  <FieldRow label="Description" htmlFor="application-form-field-description">
                    <textarea className="form-control" id="application-form-field-description" name="description" rows={2}
                              defaultValue={a.description ?? ""}></textarea>
                  </FieldRow>
                  <FieldRow label="Vendor" htmlFor="application-form-field-vendor">
                    <input type="text" className="form-control" id="application-form-field-vendor" name="vendor"
                           defaultValue={a.vendor ?? ""} maxLength={200} />
                  </FieldRow>
                  <FieldRow label="Self-hosted" htmlFor="application-form-field-is_self_hosted">
                    <div className="form-check">
                      <input className="form-check-input" type="checkbox" name="is_self_hosted" value="1"
                             id="application-form-field-is_self_hosted" defaultChecked={a.is_self_hosted} />
                      <label className="form-check-label fs-12" htmlFor="application-form-field-is_self_hosted">We run this ourselves.</label>
                    </div>
                  </FieldRow>
                  <FieldRow label="Location" htmlFor="application-form-field-location_id">
                    {pick("application-form-field-location_id", "location_id", a.location_id, options.locations)}
                  </FieldRow>
                  <FieldRow label="Owner department" htmlFor="application-form-field-owner_department_id">
                    {pick("application-form-field-owner_department_id", "owner_department_id", a.owner_department_id, options.departments)}
                  </FieldRow>
                  <FieldRow label="Accountable person" htmlFor="application-form-field-owner_member_id">
                    {pick("application-form-field-owner_member_id", "owner_member_id", a.owner_member_id, options.owners)}
                  </FieldRow>
                  <FieldRow label="URL" htmlFor="application-form-field-url">
                    <input type="text" className="form-control" id="application-form-field-url" name="url"
                           defaultValue={a.url ?? ""} maxLength={2000} placeholder="https://…" />
                  </FieldRow>
                  <FieldRow label="Sign-on path" htmlFor="application-form-field-sso_path">
                    <input type="text" className="form-control" id="application-form-field-sso_path" name="sso_path"
                           defaultValue={a.sso_path ?? ""} maxLength={200} placeholder="/sso" />
                    <div className="form-text">Where the application receives the platform&apos;s hand-off token (its maludb-os.json, sso.path). Blank: the launcher opens the address as it is.</div>
                  </FieldRow>
                  <FieldRow label="Sign-out path" htmlFor="application-form-field-sso_logout_path">
                    <input type="text" className="form-control" id="application-form-field-sso_logout_path" name="sso_logout_path"
                           defaultValue={a.sso_logout_path ?? ""} maxLength={200} placeholder="/sso/logout" />
                  </FieldRow>
                  <FieldRow label="Directory" htmlFor="application-form-field-directory_writes">
                    <div className="form-check">
                      <input className="form-check-input" type="checkbox" id="application-form-field-directory_writes" name="directory_writes" value="1" defaultChecked={a.directory_writes} />
                      <label className="form-check-label fs-13" htmlFor="application-form-field-directory_writes">May change the directory (HR): invite people, edit them, move them between departments — as the person using it</label>
                    </div>
                    <div className="form-text">Its maludb-os.json says directory.writes. Reading the directory needs nothing: every application with a token may.</div>
                  </FieldRow>
                  <FieldRow label="Serves" htmlFor="application-form-field-scope_kind">
                    <select className="form-select" id="application-form-field-scope_kind" name="scope_kind" defaultValue={a.scope_kind}>
                      <option value="none">One set of data for the whole business</option>
                      <option value="location">Each site separately (a restaurant, a shop)</option>
                      <option value="department">Each department separately</option>
                    </select>
                    <div className="form-text">
                      Its maludb-os.json says scopes. A scoped application is granted per site or department — the Scopes tab lists
                      which it serves. Fixed while it has scopes or grants.
                    </div>
                  </FieldRow>
                  <FieldRow label="Version" htmlFor="application-form-field-version">
                    <input type="text" className="form-control" id="application-form-field-version" name="version"
                           defaultValue={a.version ?? ""} maxLength={50} />
                  </FieldRow>
                  <FieldRow label="Criticality" htmlFor="application-form-field-criticality">
                    <select className="form-select" id="application-form-field-criticality" name="criticality" defaultValue={a.criticality}>
                      {options.criticalities.map((c) => <option value={c} key={c}>{ucfirst(c)}</option>)}
                    </select>
                  </FieldRow>
                  <FieldRow label="Notes" htmlFor="application-form-field-notes">
                    <textarea className="form-control" id="application-form-field-notes" name="notes" rows={2}
                              defaultValue={a.notes ?? ""}></textarea>
                  </FieldRow>
                </form>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
