import type { Metadata } from "next";
import { notFound } from "next/navigation";
import AiOpsNav from "@/components/aiops/AiOpsNav";
import ActionForm from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import KindBadge from "@/components/skills/KindBadge";
import SubmitButton from "@/components/kit/SubmitButton";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { skillLibraryView } from "@/lib/schemas/skillLibrary";

export const metadata: Metadata = { title: "Skill" };

const fmt = (iso: string) => new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });

/**
 * Screen `skills-library-view` — one skill: its versions (enable or disable each; agents get the newest
 * enabled one), the chosen version's instructions and reference files, and who holds it. `?version=`
 * shows an older version. Data: GET /ai/skills/view.php?name=&version= (super-admin).
 */
export default async function SkillPage({ params, searchParams }: {
  params: Promise<{ name: string }>; searchParams: Promise<{ version?: string }>;
}) {
  const { name } = await params;
  const { version } = await searchParams;
  const skillName = decodeURIComponent(name);
  if (!/^[a-z0-9][a-z0-9-]{1,63}$/.test(skillName)) notFound();
  const v = version && /^\d+$/.test(version) ? `&version=${version}` : "";
  const here = await herePath();
  return renderScreen(`/ai/skills/view.php?name=${encodeURIComponent(skillName)}${v}`, skillLibraryView, (data) => {
    const s = data.skill;
    const base = `/ai/skills/${encodeURIComponent(s.name)}`;
    const isCurrent = s.chosen.id === s.current_id;
    return (
      <>
        <PageHeader title={s.name} id="skills-library-view" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Skills", href: "/ai/skills" }, { label: s.name }]}>
          {data.can.edit && (
            <Link href={withBack(`${base}/edit`, here)} className="btn btn-primary" id="skills-library-view-edit-btn">
              <i className="feather-edit-2 me-2"></i><span>New version</span>
            </Link>
          )}
        </PageHeader>
        <div className="main-content" data-screen="skills-library-view">
          {s.kind === "runbook" && <p className="mb-3"><KindBadge kind={s.kind} /> <span className="fs-12 text-muted">An application&rsquo;s generic skill: shipped with it, assigned to it, and given to agents from its page.</span></p>}
          <AiOpsNav active="skills" />
          {!isCurrent && (
            <div className="alert alert-soft-warning-message py-2" id="skills-library-view-older">
              You are reading version <code>{s.chosen.version}</code>, not the one agents get. <Link href={base}>Show the current one</Link>.
            </div>
          )}
          <div className="row">
            <div className="col-xl-8">
              <div className="card" id="skills-library-view-instructions">
                <div className="card-header"><h5 className="card-title">Instructions</h5>
                  <span className="fs-11 text-muted">version <code>{s.chosen.version}</code> · {s.markdown.length.toLocaleString()} characters</span></div>
                <div className="card-body">
                  <p className="fs-13"><strong>Description.</strong> {s.chosen.description}</p>
                  <pre className="fs-12 mb-0" style={{ whiteSpace: "pre-wrap", maxHeight: 640, overflow: "auto" }}>{s.body}</pre>
                </div>
              </div>
              <div className="card" id="skills-library-view-files">
                <div className="card-header"><h5 className="card-title">Reference files</h5></div>
                <div className="card-body">
                  {s.files.length === 0 ? <p className="text-muted mb-0">None.</p> : s.files.map((f) => (
                    <details key={f.path} className="mb-2" id={`skills-library-file-${f.path.replace(/[^a-z0-9]+/gi, "-")}`}>
                      <summary className="fs-13"><code>{f.path}</code> <span className="text-muted fs-11">{f.size.toLocaleString()} bytes</span></summary>
                      <pre className="fs-12 mt-2 mb-0" style={{ whiteSpace: "pre-wrap", maxHeight: 480, overflow: "auto" }}>{f.content ?? "(could not be read)"}</pre>
                    </details>
                  ))}
                </div>
              </div>
            </div>
            <div className="col-xl-4">
              <div className="card" id="skills-library-view-versions">
                <div className="card-header"><h5 className="card-title">Versions</h5></div>
                <ul className="list-group list-group-flush">
                  {s.versions.map((ver) => (
                    <li className="list-group-item" key={ver.id} id={`skills-library-version-${ver.id}`}>
                      <div className="d-flex justify-content-between align-items-center gap-2">
                        <span>
                          <Link href={ver.id === s.current_id ? base : `${base}?version=${ver.id}`}><code>{ver.version}</code></Link>
                          {ver.id === s.current_id && <span className="badge bg-soft-success text-success ms-1">agents get this</span>}
                          {!ver.enabled && <span className="badge bg-soft-secondary text-secondary ms-1">disabled</span>}
                          <div className="fs-11 text-muted">{fmt(ver.created_at)}</div>
                        </span>
                        {data.can.edit && (
                          <ActionForm path="/ai/skills/enabled.php"
                                      confirm={ver.enabled ? `Disable version ${ver.version}? Agents holding the skill fall back to the newest version still enabled.` : undefined}>
                            <input type="hidden" name="name" value={s.name} />
                            <input type="hidden" name="skill" value={ver.id} />
                            <input type="hidden" name="enabled" value={ver.enabled ? "0" : "1"} />
                            <SubmitButton className="btn btn-sm btn-light-brand">{ver.enabled ? "Disable" : "Enable"}</SubmitButton>
                          </ActionForm>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="card" id="skills-library-view-holders">
                <div className="card-header"><h5 className="card-title">Held by</h5>
                  <Link href="/skills" className="fs-12">Assign</Link></div>
                <ul className="list-group list-group-flush">
                  {s.assignments.length === 0 ? <li className="list-group-item text-muted">Nobody yet.</li> : s.assignments.map((a) => (
                    <li className="list-group-item fs-13" key={a.skill_assignment_id}>
                      {a.agent ? <Link href={`/agents/${a.agent.member_id}`}>{a.agent.name}</Link>
                        : a.department ? <>everyone in {a.department.name}</>
                        : a.application ? <>{a.application.name}&rsquo;s agents</>
                        : a.role_key ? <>role <code>{a.role_key}</code></> : <>the whole business</>}
                      {a.pinned_bundle_hash && <span className="badge bg-soft-warning text-warning ms-1">pinned {a.pinned_bundle_hash.slice(0, 10)}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      </>
    );
  });
}
