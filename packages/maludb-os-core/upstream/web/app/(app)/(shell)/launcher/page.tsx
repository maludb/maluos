import type { Metadata } from "next";
import { redirect } from "next/navigation";
import PageHeader from "@/components/kit/PageHeader";
import Link from "@/components/kit/Link";
import RecordCard from "@/components/kit/RecordCard";
import { renderScreen } from "@/lib/screen";
import { launcherScreen } from "@/lib/schemas/launcher";

export const metadata: Metadata = { title: "Applications" };

/**
 * Screen `launcher` — the person face's home (A2, 2026-09-22): the applications this person may
 * open, one card each, and for a super-admin the operating system itself. Data: GET /launcher.php
 * (mcp_my_applications: a live access grant, or being the super-admin, is what puts a card here).
 * A card with a sign-on path opens through /launch/<id> (A3: the hand-off token carries the person
 * in already signed in); one without opens the application's recorded address as it is. A scoped
 * application the person holds at several sites or departments shows one button per scope (db/141).
 */
export default async function LauncherPage({ searchParams }: { searchParams: Promise<{ refused?: string; app?: string }> }) {
  const { refused, app } = await searchParams;
  // /launcher?app=<key> — an application (Projects builds its link this way) sent a person with no session there:
  // /home takes them straight back, or returns here WITH ?refused=, which never redirects again — no loop.
  if (!refused && typeof app === "string" && /^[a-z][a-z0-9_]{0,31}$/.test(app)) redirect(`/home?app=${app}`);
  return renderScreen("/launcher.php", launcherScreen, (data) => (
    <>
      <PageHeader title={`Welcome, ${data.member.display_name}`} id="launcher" home="/launcher" />
      <div className="main-content" data-screen="launcher">
        {refused && <div className="alert alert-danger py-2" id="launcher-refused" role="alert">{refused}</div>}
        <div className="row g-3" id="launcher-cards">
          {data.os_url && (
            <RecordCard id="launcher-card-os" title="Operating system" icon="feather-cpu"
                        description="The estate, the departments, the people and the agents — where the business is run."
                        badges={<span className="badge bg-soft-dark text-dark">Administrators</span>}
                        footer={<a href={data.os_url} className="btn btn-sm btn-primary" id="launcher-open-os">Open</a>} />
          )}
          {data.applications.map((a) => (
            <RecordCard id={`launcher-card-${a.id}`} key={a.id} title={a.name} icon={a.icon} description={a.description}
                        muted={a.url === null || a.status !== "active"}
                        badges={<>
                          {a.id === data.default_application_id && <span className="badge bg-soft-brand text-brand" id={`launcher-default-${a.id}`}>Default</span>}
                          {a.business_area && <span className="badge bg-soft-secondary text-secondary">{a.business_area}</span>}
                        </>}
                        facts={a.capability ? [["Your access", a.capability]] : []}
                        note={a.url === null ? "No address is recorded for this application yet." : a.status !== "active" ? `This application is ${a.status}.` : undefined}
                        footer={a.url !== null && a.status === "active"
                          ? a.sso && a.scopes.length > 1
                            ? <div className="d-flex flex-wrap gap-1" id={`launcher-scopes-${a.id}`}>
                                {a.scopes.map((sc) => (
                                  <Link href={`/launch/${a.id}?scope=${sc.id}`} className="btn btn-sm btn-primary" key={sc.id}
                                        id={`launcher-open-${a.id}-${sc.id}`} title={sc.role ?? undefined}>{sc.name}</Link>
                                ))}
                              </div>
                          : a.sso
                            ? <Link href={`/launch/${a.id}`} className="btn btn-sm btn-primary" id={`launcher-open-${a.id}`}>
                                {a.scopes.length === 1 ? `Open · ${a.scopes[0].name}` : "Open"}
                              </Link>
                            : <a href={a.url} className="btn btn-sm btn-light-brand" id={`launcher-open-${a.id}`} target="_blank" rel="noopener noreferrer">Open</a>
                          : undefined} />
          ))}
          {data.applications.length === 0 && !data.os_url && (
            <div className="col-12">
              <div className="card mb-0"><div className="card-body text-center text-muted py-5" id="launcher-empty">
                <i className="feather-grid fs-1 d-block mb-2 opacity-50"></i>
                You do not have access to any applications, please contact support.
              </div></div>
            </div>
          )}
        </div>
      </div>
    </>
  ));
}
