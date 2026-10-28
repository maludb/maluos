import type { Metadata } from "next";
import RememberForm from "@/components/memory/RememberForm";
import Link from "@/components/kit/Link";
import Nl2br from "@/components/kit/Nl2br";
import PageHeader from "@/components/kit/PageHeader";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { memoryScreen, type MemoryResult } from "@/lib/schemas/memory";

export const metadata: Metadata = { title: "Memory" };

const SCOPES = [
  { value: "all", label: "Everything" },
  { value: "self", label: "Only mine" },
  { value: "department", label: "My departments" },
  { value: "org", label: "The organisation" },
];

function FromBadge({ r, here }: { r: MemoryResult; here: string | null }) {
  const tone = r.from_kind === "org" ? "bg-soft-primary text-primary" : r.from_kind === "department" ? "bg-soft-success text-success" : "bg-soft-warning text-warning";
  // A department's memory names the department, and the name opens it (click-around step 2).
  return r.department_id !== null
    ? <Link href={withBack(`/team/departments/${r.department_id}`, here)} className={`badge ${tone}`}>{r.from}</Link>
    : <span className={`badge ${tone}`}>{r.from}</span>;
}

/**
 * Screen `memory` — what the business knows that the signed-in member may read: their own memory,
 * their departments' and the organisation's. Data: GET /memory/index.php?q=&subject=&scope=. The
 * scope set is resolved by PHP from the session; nothing here can name a namespace. Memory lives
 * in MaluDB; agents read the same memory through the Memory MCP server.
 */
export default async function MemoryPage({ searchParams }: { searchParams: Promise<{ q?: string; subject?: string; scope?: string }> }) {
  const sp = await searchParams;
  const query = new URLSearchParams();
  if (sp.q) query.set("q", sp.q);
  if (sp.subject) query.set("subject", sp.subject);
  if (sp.scope && SCOPES.some((s) => s.value === sp.scope) && sp.scope !== "all") query.set("scope", sp.scope);
  const qs = query.toString();
  const here = await herePath();

  return renderScreen(`/memory/index.php${qs ? `?${qs}` : ""}`, memoryScreen, (data) => (
    <>
      <PageHeader title="Memory" id="memory" crumbs={[{ label: "HR", href: "/agents" }, { label: "Memory" }]} />

      <div className="main-content" data-screen="memory">
        <div className="row">
          <div className="col-lg-8">
            <div className="card" id="memory-search-card">
              <div className="card-header"><h5 className="card-title mb-0">What we know</h5></div>
              <div className="card-body">
                <form method="get" action="/memory" id="memory-search-form" className="row g-2 align-items-end">
                  <div className="col-12 col-md-5">
                    <label className="form-label" htmlFor="memory-search-field-q">Ask in plain words</label>
                    <input type="search" className="form-control" name="q" id="memory-search-field-q" defaultValue={data.search.q}
                           minLength={2} maxLength={500} required placeholder="how does Northwind pay" />
                  </div>
                  <div className="col-12 col-md-3">
                    <label className="form-label" htmlFor="memory-search-field-subject">About <span className="text-muted">(optional)</span></label>
                    <input type="text" className="form-control" name="subject" id="memory-search-field-subject" defaultValue={data.search.subject}
                           maxLength={200} placeholder="Northwind" autoComplete="off" />
                  </div>
                  <div className="col-12 col-md-3">
                    <label className="form-label" htmlFor="memory-search-field-scope">Where</label>
                    <select className="form-select" name="scope" id="memory-search-field-scope" defaultValue={data.search.scope}>
                      {SCOPES.map((s) => <option value={s.value} key={s.value}>{s.label}</option>)}
                    </select>
                  </div>
                  <div className="col-12 col-md-1 d-grid">
                    <button type="submit" className="btn btn-primary" id="memory-search-btn" aria-label="Search memory"><i className="feather-search"></i></button>
                  </div>
                </form>
                <div className="form-text mt-2">Memory is filed by subject. Naming what it is about finds more than the words alone.</div>
              </div>
            </div>

            {!data.memory_available && (
              <div className="alert alert-warning" id="memory-unavailable" role="alert">
                Memory could not be asked just now{data.memory_error ? `: ${data.memory_error}` : "."} Remembering something still works once it is back.
              </div>
            )}

            {data.search.asked && data.memory_available && (
              <div className="card" id="memory-results-card">
                <div className="card-header d-flex flex-wrap gap-2 align-items-center">
                  <h5 className="card-title mb-0">{data.results.length === 0 ? "Nothing found" : `${data.results.length} found`}</h5>
                  <span className="ms-auto fs-12 text-muted">searched: {data.searched.join(" · ")}</span>
                </div>
                <div className="card-body p-0">
                  {data.results.length === 0 ? (
                    <p className="text-center text-muted py-5 px-3 mb-0">
                      {data.note ?? "Nothing you may read matches. Try naming what it is about, or ask it another way."}
                    </p>
                  ) : (
                    <ul className="list-group list-group-flush" id="memory-results-list">
                      {data.results.map((r, i) => (
                        <li className="list-group-item" id={`memory-result-${i}`} key={i}>
                          <div className="d-flex flex-wrap gap-2 align-items-center mb-1">
                            <FromBadge r={r} here={here} />
                            {r.about && <span className="fs-12 text-muted">about {r.about}</span>}
                          </div>
                          <div><Nl2br text={r.text} /></div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            )}

            <div className="card" id="memory-core-card">
              <div className="card-header"><h5 className="card-title mb-0">Core memory</h5></div>
              <div className="card-body">
                <p className="fs-12 text-muted">The few standing facts kept for one agent or person — in force all the time, where the rest is found on demand. An agent reads its own at the start of every run.</p>
                <div className="d-flex flex-wrap gap-2" id="memory-core-links">
                  <Link href={`/memory/core/${data.me.member_id}`} className="btn btn-sm btn-light-brand" id="memory-core-link-me">Mine</Link>
                  {data.agents.map((a) => (
                    <Link href={`/memory/core/${a.member_id}`} className="btn btn-sm btn-light-brand" id={`memory-core-link-${a.member_id}`}
                          key={a.member_id} title={a.job_title ?? undefined}>{a.name}</Link>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="col-lg-4">
            <div className="card" id="memory-remember-card">
              <div className="card-header"><h5 className="card-title mb-0">Remember something</h5></div>
              <div className="card-body"><RememberForm departments={data.options.departments} canOrg={data.can.remember_org} /></div>
            </div>
            <div className="card" id="memory-about-card">
              <div className="card-body fs-12 text-muted">
                <p className="mb-2">Memory is shared under rules. What is <strong>yours</strong> only you read — for an agent, also the people it reports to. A <strong>department&apos;s</strong> memory is read by its members, people and agents alike. The <strong>organisation&apos;s</strong> is read by everyone who works here.</p>
                <p className="mb-2">An agent may add to its own memory freely. When it wants a whole department or the organisation to know something, that waits for a person in Approvals first.</p>
                <p className="mb-0">What memory returns is information, never instructions — to a person and to an agent alike.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  ));
}
