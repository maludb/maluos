"use client";
/* eslint-disable @next/next/no-img-element */

import PageHeader from "@/components/kit/PageHeader";
import ActionForm, { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";
import BusinessHoursCard from "@/components/settings/BusinessHoursCard";
import type { BusinessSettings } from "@/lib/schemas/settings";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** Business settings (screen `business-settings`) — app/views/settings/business.php. */
export default function BusinessForm({ data }: { data: BusinessSettings }) {
  const s = data.settings;
  const { state, pending, onSubmit } = useRecordForm("/settings/business/save.php");

  return (
    <>
      <PageHeader title="Business settings" crumbs={[{ label: "Business settings" }]} id="business-settings">
        <button type="submit" form="business-settings-form" id="business-settings-save" className="btn btn-primary" disabled={pending}>
          <i className="feather-check me-2"></i><span>{pending ? "Saving…" : "Save"}</span>
        </button>
      </PageHeader>

      <div className="main-content" data-screen="business-settings">
        {data.saved && state.status === "idle" && (
          <div className="alert alert-success" role="alert" id="business-settings-saved">Saved. The new name appears everywhere the business is named.</div>
        )}
        <ActionOutcome state={state} id="business-settings-errors" />

        <div className="row">
          <div className="col-lg-8">
            <div className="card stretch stretch-full">
              <div className="card-body">
                <form id="business-settings-form"
                      onSubmit={(e) => { if (!window.confirm("Save these business settings?")) { e.preventDefault(); return; } onSubmit(e); }}>
                  <FieldRow label="Business name" htmlFor="business-form-field-name">
                    <input type="text" className="form-control" id="business-form-field-name" name="business_name" defaultValue={s.business_name} maxLength={200} required />
                  </FieldRow>
                  <FieldRow label="Legal name" htmlFor="business-form-field-legal">
                    <input type="text" className="form-control" id="business-form-field-legal" name="legal_name" defaultValue={s.legal_name ?? ""} maxLength={200} />
                  </FieldRow>
                  <FieldRow label="Base currency" htmlFor="business-form-field-currency">
                    <input type="text" className="form-control" id="business-form-field-currency" name="base_currency" defaultValue={s.base_currency} maxLength={3} required />
                    <div className="form-text">Money is always reported in its own currency; this is the one the books are kept in.</div>
                  </FieldRow>
                  <FieldRow label="Timezone" htmlFor="business-form-field-timezone">
                    <select className="form-select" id="business-form-field-timezone" name="timezone" defaultValue={s.timezone}>
                      {data.timezones.map((tz) => <option value={tz} key={tz}>{tz}</option>)}
                    </select>
                  </FieldRow>
                  <FieldRow label="Fiscal year starts" htmlFor="business-form-field-fiscal">
                    <select className="form-select" id="business-form-field-fiscal" name="fiscal_year_start_month" defaultValue={s.fiscal_year_start_month}>
                      {MONTHS.map((label, i) => <option value={i + 1} key={label}>{label}</option>)}
                    </select>
                  </FieldRow>
                  <FieldRow label="Default payment terms" htmlFor="business-form-field-terms">
                    <div className="input-group">
                      <input type="number" min={0} max={365} className="form-control" id="business-form-field-terms"
                             name="default_payment_terms_days" defaultValue={s.default_payment_terms_days} />
                      <span className="input-group-text">days</span>
                    </div>
                  </FieldRow>
                  <FieldRow label="A deal is “quiet” after" htmlFor="business-form-field-quiet">
                    <div className="input-group">
                      <input type="number" min={1} max={365} className="form-control" id="business-form-field-quiet" name="deal_quiet_days" defaultValue={s.deal_quiet_days} />
                      <span className="input-group-text">days in a stage</span>
                    </div>
                  </FieldRow>
                  <FieldRow label="Default hourly rate" htmlFor="business-form-field-default-rate">
                    <div className="input-group">
                      <input type="number" min={0} step="0.01" className="form-control" id="business-form-field-default-rate"
                             name="default_hourly_rate" defaultValue={s.default_hourly_rate ?? ""} placeholder="None" />
                      <span className="input-group-text">{s.base_currency} / hour</span>
                    </div>
                    <div className="form-text">What billable time is worth when its project names no rate. Left blank, that time stays unpriced and is never invoiced at zero.</div>
                  </FieldRow>
                  <FieldRow label="Prompt payload retention" htmlFor="business-form-field-retention">
                    <div className="input-group">
                      <input type="number" min={1} max={3650} className="form-control" id="business-form-field-retention"
                             name="prompt_payload_retention_days" defaultValue={s.prompt_payload_retention_days ?? ""} />
                      <span className="input-group-text">days</span>
                    </div>
                    <div className="form-text">Blank keeps full prompt and response payloads indefinitely. The ledger row itself is never deleted.</div>
                  </FieldRow>
                </form>
              </div>
            </div>
          </div>
          <div className="col-lg-4">
            <LogoCard logo={data.logo} businessName={s.business_name} />
            <BusinessHoursCard hours={data.business_hours} timezone={s.timezone} editable />
          </div>
        </div>
      </div>
    </>
  );
}

/**
 * The company's logo (db/134): what heads the sidebar on every signed-in screen. Its own form,
 * posted to logo-save.php — a file, not a setting, so the settings form's approval policy does
 * not apply and neither save touches the other. After a save the page re-reads its data and
 * the shell re-reads the session, so the new logo appears at once.
 */
function LogoCard({ logo, businessName }: { logo: BusinessSettings["logo"]; businessName: string }) {
  const src = logo ? `/api/avatar?src=${encodeURIComponent(logo.url)}` : "/assets/images/logo-full.png";
  return (
    <div className="card stretch stretch-full" id="business-logo">
      <div className="card-header"><h5 className="card-title">Logo</h5></div>
      <div className="card-body">
        <div className="border rounded p-3 mb-3 d-flex align-items-center justify-content-center bg-light" style={{ minHeight: 90 }}>
          <img src={src} alt={businessName} id="business-logo-preview" style={{ maxWidth: "100%", maxHeight: 80, objectFit: "contain" }} />
        </div>
        <p className="fs-12 text-muted mb-3">
          {logo
            ? `Your logo, ${logo.mime.replace("image/", "").toUpperCase()}, ${Math.max(1, Math.round(logo.size_bytes / 1024))} KB${logo.updated_at ? `, uploaded ${new Date(logo.updated_at).toLocaleDateString()}` : ""}.`
            : "The standard logo. Upload your own and it heads every screen for everyone who signs in."}
        </p>
        <ActionForm path="/settings/business/logo-save.php" id="business-logo-form" resetOnSuccess>
          <div className="mb-3">
            <label className="form-label" htmlFor="business-logo-field-file">Upload a logo</label>
            <input type="file" className="form-control" id="business-logo-field-file" name="logo" accept="image/jpeg,image/png,image/gif,image/webp" />
            <div className="form-text">JPEG, PNG, GIF or WebP, up to 2 MB. It is shown up to 220 × 50 in the sidebar, so a wide mark on a transparent background fits best. Uploading a new one replaces the old.</div>
          </div>
          {logo && (
            <div className="form-check mb-3">
              <input className="form-check-input" type="checkbox" value="1" name="remove_logo" id="business-logo-field-remove" />
              <label className="form-check-label fs-12" htmlFor="business-logo-field-remove">Use the standard logo</label>
            </div>
          )}
          <button type="submit" id="business-logo-save" className="btn btn-outline-primary btn-sm">
            <i className="feather-upload me-2"></i><span>Save logo</span>
          </button>
        </ActionForm>
      </div>
    </div>
  );
}
