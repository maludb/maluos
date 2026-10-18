import type { Metadata } from "next";
import ActionForm from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import SubmitButton from "@/components/kit/SubmitButton";
import { ucfirst } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { modelsSettings } from "@/lib/schemas/settings";

export const metadata: Metadata = { title: "Models" };

const STATUS_COLOR: Record<string, string> = { active: "success", deprecated: "warning", disabled: "secondary" };

/** Screen `models-settings` — the model registry. Data: GET /settings/models (super-admin only). */
export default async function ModelsPage() {
  const here = await herePath();
  return renderScreen("/settings/models", modelsSettings, (data) => (
    <>
      <PageHeader title="Models" crumbs={[{ label: "Models" }]} id="models-settings">
        <Link href={withBack("/settings/models/new", here)} id="models-settings-add-btn" className="btn btn-primary">
          <i className="feather-plus me-2"></i><span>Register a model</span>
        </Link>
      </PageHeader>

      <div className="main-content" data-screen="models-settings">
        <div className="card stretch stretch-full" id="models-settings-card">
          <div className="card-header">
            <h5 className="card-title">The model registry</h5>
            <span className="fs-11 text-muted">no API keys yet — that arrives with the Stripe slice&rsquo;s tenant secret store</span>
          </div>
          <div className="card-body p-0">
            <div className="table-responsive">
              <table className="table table-hover mb-0" id="models-settings-table">
                <thead className="thead-light">
                  <tr><th>Key</th><th>Provider</th><th>Harness</th><th>Prices (in / out per Mtok)</th><th>Status</th><th className="text-end">Actions</th></tr>
                </thead>
                <tbody>
                  {data.models.length === 0 ? (
                    <tr><td colSpan={6} className="text-center text-muted py-5">
                      <i className="feather-cpu fs-1 d-block mb-2 opacity-50"></i>
                      No models yet — hiring an agent needs one. <Link href={withBack("/settings/models/new", here)}>Register one</Link>.
                    </td></tr>
                  ) : data.models.map((m) => {
                    const c = STATUS_COLOR[m.status] ?? "secondary";
                    return (
                      <tr id={`model-row-${m.id}`} key={m.id}>
                        <td>
                          <Link href={withBack(`/settings/models/${m.id}/edit`, here)} className="fw-medium">{m.model_key}</Link>
                          <div className="fs-11 text-muted">{m.display_name}
                            {m.auth_mode === "claude_subscription" && <span className="badge bg-soft-warning text-warning ms-2" id={`model-max-plan-${m.id}`}>Max plan</span>}</div>
                        </td>
                        <td className="text-muted fs-12">{ucfirst(m.provider)}</td>
                        <td className="text-muted fs-12">{m.harness}</td>
                        <td className="text-muted fs-12">{m.price_input_per_mtok} / {m.price_output_per_mtok} {m.currency}</td>
                        <td><span className={`badge bg-soft-${c} text-${c}`}>{ucfirst(m.status)}</span></td>
                        <td className="text-end">
                          <div className="d-inline-flex gap-1">
                            {data.statuses.filter((s) => s !== m.status).map((s) => (
                              <ActionForm path="/settings/models/status.php" key={s}>
                                <input type="hidden" name="model" value={m.id ?? ""} />
                                <input type="hidden" name="status" value={s} />
                                <SubmitButton className="btn btn-sm btn-light-brand" id={`model-status-${m.id}-${s}`}>{ucfirst(s)}</SubmitButton>
                              </ActionForm>
                            ))}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </>
  ));
}
