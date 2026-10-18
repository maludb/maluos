import PageHeader from "./PageHeader";
import type { z } from "zod";
import type { moduleStub } from "@/lib/schemas/modules";

/**
 * A module that is registered and designed but not built (app/views/shared/module-stub.php).
 * Not the same thing as the migration's "not converted yet" card: this is the module's real
 * state in the product, and PHP says so.
 */
export default function ModuleStub({ data }: { data: z.infer<typeof moduleStub> }) {
  const s = data.stub;
  const app = s.application;
  return (
    <>
      <PageHeader title={s.label} crumbs={[{ label: s.label }]} id="module-stub">
        <span className="badge bg-soft-warning text-warning">Not built yet</span>
      </PageHeader>
      <div className="main-content">
        <div className="row">
          <div className="col-lg-8">
            <div className="card stretch stretch-full" id="module-stub-card">
              <div className="card-header">
                <h5 className="card-title"><i className={`${s.icon} me-2`}></i>{app.name ?? s.label}</h5>
              </div>
              <div className="card-body">
                <p className="mb-3">{app.description ?? "A built-in module of this platform."}</p>
                <p className="text-muted mb-0">
                  This module is registered and reachable, and its screens are specified — they are built in{" "}
                  <strong>phase {s.phase}{s.phase_name ? ` (${s.phase_name})` : ""}</strong> of the build plan. Its screens,
                  actions and questions are already designed in <code>docs/business-os-action-manifest.md</code>,{" "}
                  <code>docs/business-os-mcp-tool-surface.md</code> and <code>docs/business-os-questions.md</code>.
                </p>
              </div>
            </div>
          </div>
          <div className="col-lg-4">
            <div className="card stretch stretch-full" id="module-stub-registry-card">
              <div className="card-header"><h5 className="card-title">Registry</h5></div>
              <div className="card-body">
                <dl className="row mb-0 fs-12">
                  <dt className="col-5 text-muted">Category</dt><dd className="col-7">{app.category ?? "—"}</dd>
                  <dt className="col-5 text-muted">Runs at</dt><dd className="col-7">{app.location_name ?? "—"}</dd>
                  <dt className="col-5 text-muted">Owner dept.</dt><dd className="col-7">{app.department_name ?? "Unassigned"}</dd>
                  <dt className="col-5 text-muted">Module grant</dt><dd className="col-7"><code>{s.module_grant ?? "admin-gated"}</code></dd>
                  <dt className="col-5 text-muted">Address</dt><dd className="col-7"><code>{s.url}</code></dd>
                </dl>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
