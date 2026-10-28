import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import type { BusinessHours } from "@/lib/schemas/settings";

/**
 * The week's opening hours (action `business_hours_save`, super-admin). SLA clocks count only
 * inside them, in the business timezone. One small form per weekday — no modal, works at 375px.
 */
export default function BusinessHoursCard({ hours, timezone, editable }: { hours: BusinessHours; timezone: string; editable: boolean }) {
  return (
    <div className="card" id="business-hours-card">
      <div className="card-header"><h5 className="card-title">Business hours <span className="text-muted fs-12 fw-normal">· {timezone}</span></h5></div>
      <div className="card-body">
        <p className="text-muted fs-12">When the business is open. An application that keeps SLA clocks reads these hours from the kernel. Holidays are not kept yet.</p>
        {hours.map((h) => editable ? (
          <ActionForm path="/settings/business/hours-save.php" key={h.weekday} id={`business-hours-form-${h.weekday}`} className="d-flex flex-wrap gap-2 align-items-center mb-2">
            <input type="hidden" name="weekday" value={h.weekday} />
            <span style={{ width: 92 }} className="fw-semibold">{h.name}</span>
            <select name="is_open" className="form-select form-select-sm w-auto" aria-label={`${h.name} open or closed`} defaultValue={h.is_open ? "1" : "0"} key={String(h.is_open)}>
              <option value="1">Open</option><option value="0">Closed</option>
            </select>
            <input type="time" name="opens" className="form-control form-control-sm w-auto" aria-label={`${h.name} opens`} defaultValue={h.opens} required />
            <input type="time" name="closes" className="form-control form-control-sm w-auto" aria-label={`${h.name} closes`} defaultValue={h.closes} required />
            <SubmitButton className="btn btn-sm btn-light-brand" id={`business-hours-save-${h.weekday}`}>Save</SubmitButton>
          </ActionForm>
        ) : (
          <div key={h.weekday} className="d-flex gap-2 py-1"><span style={{ width: 92 }} className="fw-semibold">{h.name}</span><span className={h.is_open ? "" : "text-muted"}>{h.is_open ? `${h.opens} – ${h.closes}` : "Closed"}</span></div>
        ))}
      </div>
    </div>
  );
}
