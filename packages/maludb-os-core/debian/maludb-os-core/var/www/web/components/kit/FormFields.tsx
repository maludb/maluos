import type { ReactNode } from "react";

/**
 * The design system's horizontal form row: col-lg-4 label / col-lg-8 control. Screens compose
 * these; the markup is components.md's, so a form built from them is the template's form.
 */
export function FieldRow({ label, htmlFor, children }: { label: string; htmlFor?: string; children: ReactNode }) {
  return (
    <div className="row mb-3">
      {htmlFor ? (
        <label className="col-lg-4 col-form-label" htmlFor={htmlFor}>{label}</label>
      ) : (
        <span className="col-lg-4 col-form-label">{label}</span>
      )}
      <div className="col-lg-8">{children}</div>
    </div>
  );
}

/** An input with the theme's icon prefix. */
export function IconInput({ icon, children }: { icon: string; children: ReactNode }) {
  return (
    <div className="input-group">
      <span className="input-group-text"><i className={icon}></i></span>
      {children}
    </div>
  );
}

/** Owner picker (app/views/shared/owner-select.php). */
export function OwnerSelect({
  id, name = "owner_member_id", label = "Owner", selected, members,
}: {
  id: string;
  name?: string;
  label?: string;
  selected: number | null;
  members: { id: number; name: string; kind: string }[];
}) {
  return (
    <FieldRow label={label} htmlFor={id}>
      <select className="form-select" id={id} name={name} defaultValue={selected ?? ""}>
        <option value="">Nobody</option>
        {members.map((m) => (
          <option value={m.id} key={m.id}>{m.name}{m.kind === "agent" ? " (agent)" : ""}</option>
        ))}
      </select>
    </FieldRow>
  );
}

/** Department picker (app/views/shared/department-select.php). */
export function DepartmentSelect({
  id, name = "department_id", selected, departments,
}: {
  id: string;
  name?: string;
  selected: number | null;
  departments: { id: number; name: string }[];
}) {
  return (
    <FieldRow label="Department" htmlFor={id}>
      <select className="form-select" id={id} name={name} defaultValue={selected ?? ""}>
        <option value="">No department</option>
        {departments.map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}
      </select>
      <div className="form-text">A record with no department is visible to anyone holding the module grant.</div>
    </FieldRow>
  );
}

/** The six address inputs (address_line1 … address_country), as address_from_request() reads them. */
export function AddressFields({
  prefix, address,
}: {
  prefix: string;
  address: { line1: string; line2: string; city: string; region: string; postal: string; country: string };
}) {
  return (
    <div className="row mb-3">
      <label className="col-lg-4 col-form-label" htmlFor={`${prefix}-field-address-line1`}>Address</label>
      <div className="col-lg-8 d-flex flex-column gap-2">
        <input type="text" className="form-control" id={`${prefix}-field-address-line1`} name="address_line1"
               placeholder="Line 1" defaultValue={address.line1} maxLength={120} />
        <input type="text" className="form-control" id={`${prefix}-field-address-line2`} name="address_line2"
               placeholder="Line 2" defaultValue={address.line2} maxLength={120} />
        <div className="d-flex flex-wrap gap-2">
          <input type="text" className="form-control" id={`${prefix}-field-address-city`} name="address_city"
                 placeholder="City" defaultValue={address.city} maxLength={120} style={{ minWidth: "8rem" }} />
          <input type="text" className="form-control" id={`${prefix}-field-address-region`} name="address_region"
                 placeholder="Region" defaultValue={address.region} maxLength={120} style={{ minWidth: "7rem" }} />
          <input type="text" className="form-control" id={`${prefix}-field-address-postal`} name="address_postal"
                 placeholder="Postal" defaultValue={address.postal} maxLength={120} style={{ minWidth: "6rem" }} />
          <input type="text" className="form-control" id={`${prefix}-field-address-country`} name="address_country"
                 placeholder="Country" defaultValue={address.country} maxLength={120} style={{ minWidth: "7rem" }} />
        </div>
      </div>
    </div>
  );
}
