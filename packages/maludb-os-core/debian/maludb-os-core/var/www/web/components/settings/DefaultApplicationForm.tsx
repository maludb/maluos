"use client";

import { useState } from "react";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import type { DefaultApplication } from "@/lib/schemas/settings";

/**
 * "Open on sign-in" (db/142): the application app.<domain>/ takes a person to after sign-in, and on
 * a scoped one the site or department. Used by the person in /settings and by an administrator on the
 * member's page (memberId). Only what the person holds is offered; none chosen = the launcher decides
 * (straight into the only application they hold, else the list).
 */
export default function DefaultApplicationForm({ value, memberId, idPrefix = "default-app" }: {
  value: DefaultApplication; memberId?: number; idPrefix?: string;
}) {
  const [appId, setAppId] = useState<string>(value.application_id !== null ? String(value.application_id) : "");
  const chosen = value.options.find((o) => String(o.id) === appId);
  if (value.options.length === 0) {
    return <p className="fs-13 text-muted mb-0" id={`${idPrefix}-none`}>No application has been granted yet, so there is nothing to open on sign-in.</p>;
  }
  return (
    <ActionForm path="/settings/default-application.php" id={`${idPrefix}-form`} className="row g-2 align-items-end">
      {memberId !== undefined && <input type="hidden" name="member" value={memberId} />}
      <div className="col-sm-5">
        <label className="form-label fs-12" htmlFor={`${idPrefix}-application`}>Open on sign-in</label>
        <select name="application" id={`${idPrefix}-application`} className="form-select form-select-sm" value={appId}
                onChange={(e) => setAppId(e.target.value)}>
          <option value="">— the launcher decides —</option>
          {value.options.map((o) => <option value={o.id} key={o.id}>{o.name}</option>)}
        </select>
      </div>
      {chosen && chosen.scopes.length > 0 && (
        <div className="col-sm-4">
          <label className="form-label fs-12" htmlFor={`${idPrefix}-scope`}>At</label>
          <select name="scope" id={`${idPrefix}-scope`} className="form-select form-select-sm" key={appId}
                  defaultValue={value.application_id === chosen.id && value.scope_id !== null ? String(value.scope_id) : ""}>
            <option value="">— choose when it opens —</option>
            {chosen.scopes.map((s) => <option value={s.id} key={s.id}>{s.name}</option>)}
          </select>
        </div>
      )}
      <div className="col-sm-3">
        <SubmitButton className="btn btn-sm btn-primary w-100" id={`${idPrefix}-save`}>Save</SubmitButton>
      </div>
      <div className="col-12 form-text">
        With none chosen, someone who holds one application goes straight into it; with several, they choose on the launcher.
      </div>
    </ActionForm>
  );
}
