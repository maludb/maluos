"use client";

import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";
import type { EndpointFormData } from "@/lib/schemas/applications";

/**
 * Endpoint form (screens `application-endpoint-add` / `-edit`) — app/views/applications/
 * endpoint-form.php. It never collects a credential: those attach once the secret store exists.
 */
export default function EndpointForm({ data, back: carried = null }: { data: EndpointFormData; back?: string | null }) {
  const { application, endpoint: e, options } = data;
  const isEdit = e.id !== null;
  // Where the form was opened from (click-around R5), else the application's Endpoints tab.
  const parent = `/applications/${application.id}?tab=endpoints`;
  const back = carried ?? parent;
  const { state, pending, onSubmit } = useRecordForm("/applications/endpoints/save.php", carried);

  return (
    <>
      <PageHeader title={isEdit ? "Edit endpoint" : "Add endpoint"} id="endpoint-form"
                  crumbs={[{ label: "Applications", href: "/applications" }, { label: application.name, href: parent },
                           { label: isEdit ? e.name : "New endpoint" }]}
                  back={{ href: parent, label: "the application" }}>
        <Link href={back} id="endpoint-form-cancel" className="btn btn-light-brand">Cancel</Link>
        <button type="submit" form="endpoint-form" id="endpoint-form-save" className="btn btn-primary" disabled={pending}>
          <i className="feather-check me-2"></i><span>{pending ? "Saving…" : "Save"}</span>
        </button>
      </PageHeader>

      <div className="main-content" data-screen={isEdit ? "application-endpoint-edit" : "application-endpoint-add"} data-entity="application_endpoint" data-record-id={e.id ?? ""}>
        <ActionOutcome state={state} id="endpoint-form-errors" />
        <div className="row">
          <div className="col-lg-8">
            <div className="card stretch stretch-full">
              <div className="card-body">
                <form id="endpoint-form" onSubmit={onSubmit}>
                  <input type="hidden" name="application" value={application.id} />
                  {isEdit && <input type="hidden" name="endpoint" value={e.id ?? ""} />}
                  <FieldRow label="Name" htmlFor="endpoint-form-field-name">
                    <input type="text" className="form-control" id="endpoint-form-field-name" name="name"
                           defaultValue={e.name} maxLength={200} required />
                  </FieldRow>
                  <FieldRow label="Kind" htmlFor="endpoint-form-field-kind">
                    <select className="form-select" id="endpoint-form-field-kind" name="kind" required defaultValue={e.kind ?? options.kinds[0]}>
                      {options.kinds.map((k) => <option value={k} key={k}>{k}</option>)}
                    </select>
                    <div className="form-text">Only mcp, http_api and ui endpoints are checkable from the platform.</div>
                  </FieldRow>
                  <FieldRow label="URL" htmlFor="endpoint-form-field-url">
                    <input type="text" className="form-control" id="endpoint-form-field-url" name="url"
                           defaultValue={e.url ?? ""} maxLength={2000} placeholder="http://…" />
                  </FieldRow>
                  <FieldRow label="Auth kind" htmlFor="endpoint-form-field-auth_kind">
                    <select className="form-select" id="endpoint-form-field-auth_kind" name="auth_kind" defaultValue={e.auth_kind}>
                      {options.auth_kinds.map((k) => <option value={k} key={k}>{k}</option>)}
                    </select>
                    <div className="form-text">Credentials attach once the secret store exists (the Stripe slice) — this form never collects one.</div>
                  </FieldRow>
                  <FieldRow label="Agent-reachable" htmlFor="endpoint-form-field-agent_reachable">
                    <div className="form-check">
                      <input className="form-check-input" type="checkbox" name="agent_reachable" value="1"
                             id="endpoint-form-field-agent_reachable" defaultChecked={e.agent_reachable || !isEdit} />
                      <label className="form-check-label fs-12" htmlFor="endpoint-form-field-agent_reachable">
                        An agent-reachable MCP endpoint becomes grantable in Agent HR&rsquo;s tool-grant picker.
                      </label>
                    </div>
                  </FieldRow>
                  <FieldRow label="MCP surface version" htmlFor="endpoint-form-field-mcp_surface_version">
                    <input type="text" className="form-control" id="endpoint-form-field-mcp_surface_version" name="mcp_surface_version"
                           defaultValue={e.mcp_surface_version ?? ""} maxLength={50} placeholder="1.0" />
                  </FieldRow>
                  <FieldRow label="Notes" htmlFor="endpoint-form-field-notes">
                    <textarea className="form-control" id="endpoint-form-field-notes" name="notes" rows={2}
                              defaultValue={e.notes ?? ""}></textarea>
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
