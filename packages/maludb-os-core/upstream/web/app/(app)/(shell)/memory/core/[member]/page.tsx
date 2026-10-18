import type { Metadata } from "next";
import { notFound } from "next/navigation";
import CoreSetForm from "@/components/memory/CoreSetForm";
import Link from "@/components/kit/Link";
import Nl2br from "@/components/kit/Nl2br";
import PageHeader from "@/components/kit/PageHeader";
import { getSession } from "@/lib/api";
import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { coreMemoryScreen } from "@/lib/schemas/memory";

export const metadata: Metadata = { title: "Core memory" };

/**
 * Screen `memory-core` — the standing facts kept for one member. Data: GET
 * /memory/core.php?member= (oneself; HR; an agent one may see in full — anyone else is refused by
 * PHP). The set form appears only when PHP said core-set.php would accept this person (can.set).
 */
export default async function CoreMemoryPage({ params }: { params: Promise<{ member: string }> }) {
  const { member } = await params;
  if (!/^\d+$/.test(member)) notFound();
  const timeZone = (await getSession()).member?.timezone ?? "UTC";

  const here = await herePath();
  return renderScreen(`/memory/core.php?member=${member}`, coreMemoryScreen, (data) => {
    const who = data.member.is_me ? "My core memory" : `${data.member.name} — core memory`;
    return (
      <>
        <PageHeader title={who} id="memory-core"
                    crumbs={[{ label: "HR", href: "/agents" }, { label: "Memory", href: "/memory" }, { label: data.member.name }]}
                    back={{ href: "/memory", label: "Memory" }}>
          {data.member.is_agent ? (
            <Link href={withBack(`/agents/${data.member.member_id}`, here)} className="btn btn-light-brand" id="memory-core-agent-btn">
              <i className="feather-cpu me-2"></i><span>{data.member.name}</span>
            </Link>
          ) : (
            <Link href={withBack(`/team/${data.member.member_id}`, here)} className="btn btn-light-brand" id="memory-core-member-btn">
              <i className="feather-user me-2"></i><span>{data.member.name}</span>
            </Link>
          )}
        </PageHeader>

        <div className="main-content" data-screen="memory-core" data-entity="member" data-record-id={data.member.member_id}>
          {!data.memory_available && (
            <div className="alert alert-warning" id="memory-core-unavailable" role="alert">
              Memory could not be asked just now{data.memory_error ? `: ${data.memory_error}` : "."}
            </div>
          )}
          <div className="row">
            <div className="col-lg-8">
              <div className="card" id="memory-core-entries-card">
                <div className="card-header"><h5 className="card-title mb-0">What holds, all the time</h5></div>
                <div className="card-body p-0">
                  {data.entries.length === 0 ? (
                    <p className="text-center text-muted py-5 px-3 mb-0" id="memory-core-empty">
                      {data.memory_available ? "Nothing is kept in core memory yet." : "—"}
                    </p>
                  ) : (
                    <ul className="list-group list-group-flush" id="memory-core-entries-list">
                      {data.entries.map((e) => (
                        <li className="list-group-item" id={`memory-core-row-${e.key}`} key={e.key}>
                          <div className="d-flex flex-wrap gap-2 align-items-baseline mb-1">
                            <span className="fw-semibold text-break">{e.key}</span>
                            <span className="ms-auto fs-12 text-muted">{formatTs(e.updated_at, timeZone, false)}</span>
                          </div>
                          <div><Nl2br text={e.value} /></div>
                          {e.note && <div className="fs-12 text-muted mt-1">{e.note}</div>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>

            <div className="col-lg-4">
              {data.can.set && (
                <div className="card" id="memory-core-set-card">
                  <div className="card-header"><h5 className="card-title mb-0">Set an entry</h5></div>
                  <div className="card-body"><CoreSetForm memberId={data.member.member_id} /></div>
                </div>
              )}
              <div className="card" id="memory-core-about-card">
                <div className="card-body fs-12 text-muted">
                  <p className="mb-2">Core memory is for short standing facts and preferences: how this business names its vendors, who signs off what, what never to do.</p>
                  <p className="mb-0">{data.member.is_agent
                    ? "It is written into this agent's persona at the start of every run. When the agent itself asks to change it, that waits for a person in Approvals."
                    : "It is kept for you, and read by nobody else but HR."}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </>
    );
  });
}
