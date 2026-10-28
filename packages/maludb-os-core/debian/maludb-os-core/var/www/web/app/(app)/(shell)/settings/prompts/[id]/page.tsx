import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ActionForm from "@/components/kit/ActionForm";
import PageHeader from "@/components/kit/PageHeader";
import SubmitButton from "@/components/kit/SubmitButton";
import Who from "@/components/kit/Who";
import { getSession } from "@/lib/api";
import { herePath } from "@/lib/here";
import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { promptView } from "@/lib/schemas/settings";

export const metadata: Metadata = { title: "Prompt" };

/**
 * Screen `system-prompt-view` — a prompt, its immutable versions newest first, and "New version"
 * (there is no editing a version, by design). Data: GET /settings/prompts/{id} (any insider;
 * writing needs mod:hr).
 */
export default async function PromptPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: rawId } = await params;
  if (!/^\d+$/.test(rawId)) notFound();
  const timeZone = (await getSession()).member?.timezone ?? "UTC";
  const here = await herePath();

  return renderScreen(`/settings/prompts/${rawId}`, promptView, (data) => {
    const { prompt: p, versions, can, new_version: nv } = data;
    const tone = p.archived ? "secondary" : "success";
    return (
      <>
        <PageHeader title={p.name} crumbs={[{ label: "Prompt library", href: "/settings/prompts" }, { label: p.name }]} id="system-prompt-view" />

        <div className="main-content" data-screen="system-prompt-view" data-entity="system_prompt" data-record-id={p.id}>
          <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
            <span className={`badge bg-soft-${tone} text-${tone}`}>{p.archived ? "Archived" : "Active"}</span>
            <span className="text-muted fs-12">{p.prompt_key}</span>
            {p.role_key && <span className="badge bg-soft-info text-info">{p.role_key}</span>}
            <span className="text-muted fs-12">used by {data.used_by_count} agent configuration{data.used_by_count === 1 ? "" : "s"}</span>
          </div>

          <div className="row">
            <div className="col-xxl-8">
              {/* Stacked cards in both columns: plain .card, never stretch-full. */}
              {can.write && nv && (
                <div className="card" id="system-prompt-view-new-version-card">
                  <div className="card-header"><h5 className="card-title">New version</h5></div>
                  <div className="card-body">
                    {/* key: after a new version is saved the prefill is the new current version */}
                    <ActionForm path="/settings/prompts/version-save.php" id="system-prompt-view-new-version-form" key={versions[0]?.id ?? 0}>
                      <input type="hidden" name="system_prompt" value={p.id} />
                      <div className="mb-3">
                        <label className="form-label fs-11" htmlFor="prompt-version-form-field-body">Text</label>
                        <textarea className="form-control" id="prompt-version-form-field-body" name="body" rows={8} required defaultValue={nv.body}></textarea>
                      </div>
                      <div className="row g-2 mb-2">
                        <div className="col-4">
                          <label className="form-label fs-11" htmlFor="prompt-version-form-field-temperature">Temperature</label>
                          <input type="number" step="0.001" min={0} className="form-control form-control-sm" id="prompt-version-form-field-temperature"
                                 name="temperature" defaultValue={nv.temperature} />
                        </div>
                        <div className="col-4">
                          <label className="form-label fs-11" htmlFor="prompt-version-form-field-max_tokens">Max tokens</label>
                          <input type="number" step={1} min={1} className="form-control form-control-sm" id="prompt-version-form-field-max_tokens"
                                 name="max_tokens" defaultValue={nv.max_tokens} />
                        </div>
                        <div className="col-4">
                          <label className="form-label fs-11" htmlFor="prompt-version-form-field-thinking_budget">Thinking budget</label>
                          <input type="number" step={1} min={0} className="form-control form-control-sm" id="prompt-version-form-field-thinking_budget"
                                 name="thinking_budget" defaultValue={nv.thinking_budget} />
                        </div>
                      </div>
                      <div className="mb-3">
                        <label className="form-label fs-11" htmlFor="prompt-version-form-field-extra_parameters">Other parameters (JSON object)</label>
                        <textarea className="form-control form-control-sm" id="prompt-version-form-field-extra_parameters" name="extra_parameters"
                                  rows={2} placeholder={'{"top_p": 0.9}'}></textarea>
                      </div>
                      <div className="mb-3">
                        <label className="form-label fs-11" htmlFor="prompt-version-form-field-change_note">Change note</label>
                        <input type="text" className="form-control form-control-sm" id="prompt-version-form-field-change_note" name="change_note"
                               placeholder="What changed and why" />
                      </div>
                      <SubmitButton className="btn btn-sm btn-primary" id="system-prompt-view-new-version-btn">
                        <i className="feather-plus me-2"></i>Save as new version
                      </SubmitButton>
                      <div className="form-text mt-2">There is no &ldquo;edit a version&rdquo; — a change of wording or of a
                        setting is always a new version; the current one is prefilled above.</div>
                    </ActionForm>
                  </div>
                </div>
              )}

              <div className="card" id="system-prompt-view-versions-card">
                <div className="card-header"><h5 className="card-title">Every version — immutable, never edited</h5></div>
                <div className="card-body">
                  {versions.length === 0 ? (
                    <p className="text-muted text-center py-5 mb-0">No versions yet.</p>
                  ) : versions.map((v) => (
                    <div className="border rounded p-3 mb-3" id={`system-prompt-version-row-${v.id}`} key={v.id}>
                      <div className="d-flex flex-wrap align-items-center gap-2 mb-2">
                        <span className="badge bg-soft-primary text-primary">v{v.version_no}</span>
                        <span className="text-muted fs-12">{v.created_at ? formatTs(v.created_at, timeZone) : "—"}</span>
                        <span className="text-muted fs-12">by {v.created_by !== null ? <Who who={{ id: v.created_by, name: v.created_by_name ?? `#${v.created_by}` }} here={here} /> : v.created_by_name ?? "—"}</span>
                        {v.parameters_summary !== "" && <span className="badge bg-soft-secondary text-secondary">{v.parameters_summary}</span>}
                      </div>
                      {v.change_note && <p className="fs-12 text-muted mb-2">{v.change_note}</p>}
                      <p className="mb-0" style={{ whiteSpace: "pre-wrap" }}>{v.body}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="col-xxl-4">
              <div className="card" id="system-prompt-view-meta-card">
                <div className="card-header"><h5 className="card-title">Details</h5></div>
                <div className="card-body">
                  {can.write ? (
                    <ActionForm path="/settings/prompts/save.php" id="system-prompt-view-meta-form">
                      <input type="hidden" name="prompt" value={p.id} />
                      <div className="mb-2">
                        <label className="form-label fs-11" htmlFor="system-prompt-view-field-prompt_key">Key</label>
                        <input type="text" className="form-control form-control-sm" id="system-prompt-view-field-prompt_key" name="prompt_key"
                               defaultValue={p.prompt_key} maxLength={100} required />
                      </div>
                      <div className="mb-2">
                        <label className="form-label fs-11" htmlFor="system-prompt-view-field-name">Name</label>
                        <input type="text" className="form-control form-control-sm" id="system-prompt-view-field-name" name="name" defaultValue={p.name} required />
                      </div>
                      <div className="mb-2">
                        <label className="form-label fs-11" htmlFor="system-prompt-view-field-description">Description</label>
                        <input type="text" className="form-control form-control-sm" id="system-prompt-view-field-description" name="description" defaultValue={p.description ?? ""} />
                      </div>
                      <div className="mb-3">
                        <label className="form-label fs-11" htmlFor="system-prompt-view-field-role_key">Role</label>
                        <input type="text" className="form-control form-control-sm" id="system-prompt-view-field-role_key" name="role_key"
                               defaultValue={p.role_key ?? ""} maxLength={100} />
                      </div>
                      <SubmitButton className="btn btn-sm btn-light-brand" id="system-prompt-view-meta-save">Save details</SubmitButton>
                    </ActionForm>
                  ) : (
                    <dl className="row mb-0">
                      <dt className="col-5 text-muted fs-12">Key</dt><dd className="col-7">{p.prompt_key}</dd>
                      <dt className="col-5 text-muted fs-12">Description</dt><dd className="col-7">{p.description ?? "—"}</dd>
                    </dl>
                  )}
                </div>
              </div>
              {can.write && (
                <div className="card" id="system-prompt-view-danger-card">
                  <div className="card-header"><h5 className="card-title text-danger">Danger zone</h5></div>
                  <div className="card-body">
                    <ActionForm path="/settings/prompts/archive.php" id="system-prompt-view-archive-form"
                                confirm={p.archived ? "Restore this prompt?" : "Archive this prompt?"}>
                      <input type="hidden" name="system_prompt" value={p.id} />
                      <input type="hidden" name="archived" value={p.archived ? "0" : "1"} />
                      <SubmitButton className={`btn btn-sm ${p.archived ? "btn-light-brand" : "btn-outline-danger"} w-100`} id="system-prompt-view-archive-btn">
                        {p.archived ? "Restore" : "Archive"}
                      </SubmitButton>
                    </ActionForm>
                    {!p.archived && (
                      <div className="form-text mt-2">Refused while a live agent configuration cites this prompt —
                        the agents it is refused for are named here if you try.</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </>
    );
  });
}
