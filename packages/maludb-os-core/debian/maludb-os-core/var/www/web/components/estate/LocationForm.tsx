"use client";

import { useState } from "react";
import DeleteLocation from "./DeleteLocation";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";
import type { LocationFormData } from "@/lib/schemas/estate";

const KIND_LABELS: Record<string, string> = { building: "Building", office: "Office", desk: "Desk", site: "Site" };

/** IANA zone names for the site's time zone field — the browser's own list. */
const TIME_ZONES: string[] = typeof Intl !== "undefined" && "supportedValuesOf" in Intl
  ? (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf("timeZone") : [];

/**
 * Location form (screens `location-add` / `location-edit`) — app/views/estate/location-form.php.
 *
 * Every field that depends on Kind lives in one block (#location-form-parent-wrap), exactly as
 * parent-options.php renders it — the schema's rules:
 *   a building has no siting and no parent (it IS the host); an office or desk states siting;
 *   an office may pick a building; a desk must pick its office and a human owner.
 * The HTMX form re-fetched that block on every Kind change; here Kind is state and both parent
 * lists arrived with the page. Kind is fixed once a location exists.
 */
export default function LocationForm({ data, back: carried = null }: { data: LocationFormData; back?: string | null }) {
  const { location: l, options } = data;
  const isEdit = l.id !== null;
  const [kind, setKind] = useState(l.kind);
  // Where the form was opened from (click-around R5), else the location on edit and the list on create.
  const parent = isEdit ? `/locations/${l.id}` : "/locations";
  const back = carried ?? parent;
  const { state, pending, onSubmit } = useRecordForm("/locations/save.php", carried);
  const parents = kind === "desk" ? options.parents.desk : kind === "office" ? options.parents.office : [];
  const tri = (v: boolean | null) => (v === null ? "" : v ? "1" : "0");

  return (
    <>
      <PageHeader title={isEdit ? "Edit location" : "New location"} id="location-form"
                  crumbs={[{ label: "Work Locations", href: "/locations" }, ...(isEdit ? [{ label: l.name, href: parent }] : []), { label: isEdit ? "Edit" : "New location" }]}
                  back={{ href: parent, label: isEdit ? "the location" : "Work locations" }}>
        <Link href={back} id="location-form-cancel" className="btn btn-light-brand">Cancel</Link>
        <button type="submit" form="location-form" id="location-form-save" className="btn btn-primary" disabled={pending}>
          <i className="feather-check me-2"></i><span>{pending ? "Saving…" : "Save"}</span>
        </button>
        {isEdit && data.can.delete && <DeleteLocation locationId={l.id as number} blockers={data.delete_blockers} buttonId="location-form-delete" />}
      </PageHeader>

      <div className="main-content" data-screen={isEdit ? "location-edit" : "location-add"} data-entity="location" data-record-id={l.id ?? ""}>
        <ActionOutcome state={state} id="location-form-errors" />
        <div className="row">
          <div className="col-lg-8">
            <div className="card stretch stretch-full">
              <div className="card-body">
                <form id="location-form" onSubmit={onSubmit}>
                  {isEdit && <input type="hidden" name="location" value={l.id ?? ""} />}
                  <FieldRow label="Name" htmlFor="location-form-field-name">
                    <input type="text" className="form-control" id="location-form-field-name" name="name"
                           defaultValue={l.name} maxLength={200} required />
                  </FieldRow>
                  <FieldRow label="Kind" htmlFor="location-form-field-kind">
                    {isEdit ? (
                      <>
                        <input type="text" className="form-control" value={KIND_LABELS[kind] ?? kind} disabled readOnly />
                        <input type="hidden" name="kind" value={kind} />
                        <div className="form-text">Kind is fixed once a location is created — a desk does not become a building.</div>
                      </>
                    ) : (
                      <>
                        <select className="form-select" id="location-form-field-kind" name="kind" value={kind}
                                onChange={(e) => setKind(e.target.value)}>
                          {Object.entries(KIND_LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
                        </select>
                        <div className="form-text">
                          <strong>Building</strong> = the host a machine stands in · <strong>Office</strong> = a machine departments
                          and agents work in — a remote one is an office sited <em>offsite</em>, not a desk ·{" "}
                          <strong>Desk</strong> = one person&rsquo;s own machine, which sits in an office and needs an owner ·{" "}
                          <strong>Site</strong> = a place the business trades from — a restaurant, a shop, a branch — not a machine.
                        </div>
                      </>
                    )}
                  </FieldRow>

                  {kind === "site" && (
                    <div id="location-form-site-wrap">
                      <FieldRow label="Address" htmlFor="location-form-field-address">
                        <textarea className="form-control" id="location-form-field-address" name="address" rows={2}
                                  maxLength={500} defaultValue={l.address ?? ""}></textarea>
                      </FieldRow>
                      <FieldRow label="Time zone" htmlFor="location-form-field-timezone">
                        <input type="text" className="form-control" id="location-form-field-timezone" name="timezone"
                               list="location-form-timezones" defaultValue={l.timezone ?? ""} placeholder="America/New_York" />
                        <datalist id="location-form-timezones">
                          {TIME_ZONES.map((z) => <option value={z} key={z} />)}
                        </datalist>
                        <div className="form-text">The applications that serve this site keep its hours in this zone.</div>
                      </FieldRow>
                    </div>
                  )}

                  {kind !== "site" && (
                  <div id="location-form-parent-wrap" key={kind}>
                    {kind !== "building" ? (
                      <FieldRow label="Siting *" htmlFor="location-form-field-siting">
                        <select className="form-select" id="location-form-field-siting" name="siting" required defaultValue={l.siting ?? ""}>
                          <option value="">— choose —</option>
                          <option value="onsite">Onsite</option>
                          <option value="offsite">Offsite</option>
                        </select>
                        <div className="form-text">
                          Onsite = a VM inside our own host. Offsite = reached over the internet — an office in another building,
                          or a rented one, is an <strong>offsite office</strong>.
                        </div>
                      </FieldRow>
                    ) : (
                      <input type="hidden" name="siting" value="" />
                    )}
                    {kind !== "building" ? (
                      <FieldRow label={kind === "desk" ? "Office it sits in *" : "Building"} htmlFor="location-form-field-parent_location_id">
                        <select className="form-select" id="location-form-field-parent_location_id" name="parent_location_id"
                                required={kind === "desk"} defaultValue={l.kind === kind ? l.parent_location_id ?? "" : ""}>
                          <option value="">— none —</option>
                          {parents.map((p) => <option value={p.id} key={p.id}>{p.name}</option>)}
                        </select>
                        {kind === "office" ? (
                          <div className="form-text">
                            Optional{parents.length === 0
                              ? " — no building exists yet, so this office will sit outside any building, which is normal (the minimum platform is one office and one desk)"
                              : ": leave it on none unless this office runs on a host you have recorded as a building"}.
                          </div>
                        ) : parents.length === 0 ? (
                          <div className="form-text">No office exists yet — add one first.</div>
                        ) : (
                          <div className="form-text">A desk is one person&rsquo;s machine, and it works out of an office.</div>
                        )}
                      </FieldRow>
                    ) : (
                      <input type="hidden" name="parent_location_id" value="" />
                    )}
                    {kind === "desk" ? (
                      <FieldRow label="Owner *" htmlFor="location-form-field-owner_member_id">
                        <select className="form-select" id="location-form-field-owner_member_id" name="owner_member_id" required
                                defaultValue={l.owner_member_id ?? ""}>
                          <option value="">Pick a person…</option>
                          {options.owners.map((o) => <option value={o.id} key={o.id}>{o.name}</option>)}
                        </select>
                        <div className="form-text">A desk must have a human owner (the schema requires it).</div>
                      </FieldRow>
                    ) : (
                      <input type="hidden" name="owner_member_id" value="" />
                    )}
                  </div>
                  )}

                  <FieldRow label="Description" htmlFor="location-form-field-description">
                    <textarea className="form-control" id="location-form-field-description" name="description" rows={2}
                              defaultValue={l.description ?? ""}></textarea>
                  </FieldRow>
                  {kind !== "site" && (<>
                  <FieldRow label="Platform" htmlFor="location-form-field-platform">
                    <select className="form-select" id="location-form-field-platform" name="platform" defaultValue={l.platform ?? ""}>
                      <option value="">—</option>
                      {options.platforms.map((p) => <option value={p.value} key={p.value}>{p.label}</option>)}
                    </select>
                  </FieldRow>
                  <FieldRow label="Operating system" htmlFor="location-form-field-operating_system">
                    <input type="text" className="form-control" id="location-form-field-operating_system" name="operating_system"
                           maxLength={100} defaultValue={l.operating_system ?? ""} placeholder="Ubuntu, Windows 11, macOS" />
                  </FieldRow>
                  <FieldRow label="OS version" htmlFor="location-form-field-os_version">
                    <input type="text" className="form-control" id="location-form-field-os_version" name="os_version"
                           maxLength={50} defaultValue={l.os_version ?? ""} placeholder="24.04 LTS" />
                  </FieldRow>
                  {/* Yes / No / not recorded. An unanswered question is stored as NULL, never as a denial —
                      "we have not checked" and "we have no access" are different facts. */}
                  {([["ssh_access", "SSH access", l.ssh_access], ["root_access", "Root access", l.root_access]] as const).map(([name, label, value]) => (
                    <FieldRow label={label} htmlFor={`location-form-field-${name}`} key={name}>
                      <select className="form-select" id={`location-form-field-${name}`} name={name} defaultValue={tri(value)}>
                        <option value="">Not recorded</option>
                        <option value="1">Yes</option>
                        <option value="0">No</option>
                      </select>
                    </FieldRow>
                  ))}
                  <FieldRow label="Host reference" htmlFor="location-form-field-external_ref">
                    <input type="text" className="form-control" id="location-form-field-external_ref" name="external_ref"
                           defaultValue={l.external_ref ?? ""} maxLength={200} />
                    <div className="form-text">Proxmox node name or VMID, for example.</div>
                  </FieldRow>
                  <FieldRow label="Hostname" htmlFor="location-form-field-hostname">
                    <input type="text" className="form-control" id="location-form-field-hostname" name="hostname"
                           defaultValue={l.hostname ?? ""} maxLength={255} />
                  </FieldRow>
                  <FieldRow label="IP address" htmlFor="location-form-field-ip_address">
                    <input type="text" className="form-control" id="location-form-field-ip_address" name="ip_address"
                           defaultValue={l.ip_address ?? ""} maxLength={45} placeholder="10.120.0.170" />
                  </FieldRow>
                  <FieldRow label="CPU cores" htmlFor="location-form-field-cpu_cores">
                    <input type="number" min={1} step={1} className="form-control" id="location-form-field-cpu_cores"
                           name="cpu_cores" defaultValue={l.cpu_cores ?? ""} />
                  </FieldRow>
                  <FieldRow label="Memory (MB)" htmlFor="location-form-field-memory_mb">
                    <input type="number" min={1} step={1} className="form-control" id="location-form-field-memory_mb"
                           name="memory_mb" defaultValue={l.memory_mb ?? ""} />
                  </FieldRow>
                  <FieldRow label="Storage (GB)" htmlFor="location-form-field-storage_gb">
                    <input type="number" min={1} step={1} className="form-control" id="location-form-field-storage_gb"
                           name="storage_gb" defaultValue={l.storage_gb ?? ""} />
                  </FieldRow>
                  <FieldRow label="Always on" htmlFor="location-form-field-is_always_on">
                    <div className="form-check">
                      <input className="form-check-input" type="checkbox" name="is_always_on" value="1"
                             id="location-form-field-is_always_on" defaultChecked={l.is_always_on} />
                      <label className="form-check-label fs-12" htmlFor="location-form-field-is_always_on">
                        Usually on for an office, off for a desk.
                      </label>
                    </div>
                  </FieldRow>
                  </>)}
                </form>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
