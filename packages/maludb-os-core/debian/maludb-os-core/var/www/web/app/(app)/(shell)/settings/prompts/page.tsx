import type { Metadata } from "next";
import PromptRoleFilter from "@/components/settings/PromptRoleFilter";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { promptLibrary } from "@/lib/schemas/settings";

export const metadata: Metadata = { title: "Prompt library" };

/** Screen `system-prompts`. Data: GET /settings/prompts?role= (any insider; writing needs mod:hr). */
export default async function PromptLibraryPage({ searchParams }: { searchParams: Promise<{ role?: string }> }) {
  const { role } = await searchParams;
  const query = role ? `?role=${encodeURIComponent(role)}` : "";
  const here = await herePath();

  return renderScreen(`/settings/prompts${query}`, promptLibrary, (data) => (
    <>
      <PageHeader title="Prompt library" crumbs={[{ label: "Prompt library" }]} id="system-prompts">
        {data.can.write && (
          <Link href={withBack("/settings/prompts/new", here)} id="system-prompts-add-btn" className="btn btn-primary">
            <i className="feather-plus me-2"></i><span>New prompt</span>
          </Link>
        )}
      </PageHeader>

      <div className="main-content" data-screen="system-prompts">
        <PromptRoleFilter role={data.filters.role} key={data.filters.role} />

        <div className="card stretch stretch-full" id="system-prompts-card">
          <div className="card-header">
            <h5 className="card-title">Reusable system prompts</h5>
            <span className="fs-11 text-muted">a version&rsquo;s text and model settings are immutable once written — a change is always a new version</span>
          </div>
          <div className="card-body p-0">
            <div className="table-responsive">
              <table className="table table-hover mb-0" id="system-prompts-table">
                <thead className="thead-light">
                  <tr><th>Name</th><th>Key</th><th>Role</th><th>Current version</th><th>Used by</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {data.prompts.length === 0 ? (
                    <tr><td colSpan={6} className="text-center text-muted py-5">
                      <i className="feather-file-text fs-1 d-block mb-2 opacity-50"></i>
                      No prompts yet.{data.can.write && <> <Link href={withBack("/settings/prompts/new", here)}>Write one</Link>.</>}
                    </td></tr>
                  ) : data.prompts.map((p) => (
                    <tr id={`system-prompt-row-${p.id}`} key={p.id}>
                      <td>
                        <Link href={`/settings/prompts/${p.id}`} className="fw-medium">{p.name}</Link>
                        {p.description && <div className="fs-11 text-muted">{p.description}</div>}
                      </td>
                      <td className="text-muted fs-12">{p.prompt_key}</td>
                      <td className="text-muted fs-12">{p.role_key ?? "—"}</td>
                      <td className="text-muted fs-12">v{p.current_version} ({p.version_count} total)</td>
                      <td className="text-muted fs-12">{p.used_by_configs}</td>
                      <td>
                        {p.archived
                          ? <span className="badge bg-soft-secondary text-secondary">Archived</span>
                          : <span className="badge bg-soft-success text-success">Active</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </>
  ));
}
