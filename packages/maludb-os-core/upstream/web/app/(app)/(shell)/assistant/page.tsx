import type { Metadata } from "next";
import ActionForm from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import SubmitButton from "@/components/kit/SubmitButton";
import { getSession } from "@/lib/api";
import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { myAssistant } from "@/lib/schemas/assistants";

export const metadata: Metadata = { title: "My assistant" };

const STATUS_TONE: Record<string, string> = { succeeded: "success", running: "primary", failed: "danger", awaiting_approval: "warning", cancelled: "secondary" };

/**
 * Screen `my-assistant` (db/154–156) — you and your personal assistant: the conversation across every
 * channel (Telegram, SMS, email, here), a box to write to it, and what it handed on — to whom, in which
 * department, why, and what came back. On app.<domain> and os.<domain>. Data: GET /assistant/.
 */
export default async function MyAssistantPage() {
  const session = await getSession();
  const timeZone = session?.member?.timezone || "UTC";
  return renderScreen("/assistant/", myAssistant, (data) => {
    if (data.assistant === null) {
      return (
        <>
          <PageHeader title="My assistant" id="my-assistant" crumbs={[{ label: "My assistant" }]} />
          <div className="main-content" data-screen="my-assistant">
            <p className="text-muted">You have no personal assistant yet. A super-admin assigns one; it then takes your directions here and on your own channels.</p>
          </div>
        </>
      );
    }
    const a = data.assistant;
    const lastThread = data.messages.length > 0 ? data.messages[data.messages.length - 1].thread_id : null;
    return (
      <>
        <PageHeader title={a.name} id="my-assistant" crumbs={[{ label: "My assistant" }]}>
          <Link href="/settings/channels" className="btn btn-light-brand" id="my-assistant-channels-btn">
            <i className="feather-smartphone me-2"></i><span>My channels</span>
          </Link>
        </PageHeader>
        <div className="main-content" data-screen="my-assistant">
          <p className="text-muted fs-13">
            {a.name} takes your directions, hands each one to the department that owns it, and tells you what came back.
            {data.channels.length > 0
              ? <> You also reach it by {data.channels.map((c) => `${c.channel} (${c.label})`).join(", ")}.</>
              : <> Link <Link href="/settings/channels">Telegram, your phone or your email</Link> to reach it from anywhere.</>}
          </p>
          <div className="row">
            <div className="col-xl-7">
              <div className="card" id="my-assistant-conversation">
                <div className="card-header"><h5 className="card-title">Conversation</h5></div>
                <div className="card-body" style={{ maxHeight: 640, overflowY: "auto" }}>
                  {data.messages.length === 0 && <p className="text-muted mb-0">Nothing yet — write below.</p>}
                  {data.messages.map((m) => (
                    <div key={m.id} className={`d-flex mb-3 ${m.mine ? "justify-content-end" : ""}`} id={`my-assistant-message-${m.id}`}>
                      <div className={`p-2 rounded ${m.mine ? "bg-soft-primary" : "bg-gray-100"}`} style={{ maxWidth: "85%" }}>
                        <div className="fs-11 text-muted mb-1">
                          {m.mine ? "You" : a.name} · {formatTs(m.created_at, timeZone)}
                          {m.channel !== "web" && m.channel !== "internal" && <> · via {m.channel}</>}
                          {!m.mine && m.delivery_channel && m.delivery_channel !== "web" && (
                            m.delivered ? <> · sent by {m.delivery_channel}</> : <span className="text-danger"> · not yet sent by {m.delivery_channel}{m.delivery_error ? `: ${m.delivery_error}` : ""}</span>
                          )}
                          {m.kind === "decision_needed" && <span className="badge bg-soft-danger text-danger ms-1">decision needed</span>}
                        </div>
                        <div className="fs-13" style={{ whiteSpace: "pre-wrap" }}>{m.body}</div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="card-footer">
                  <ActionForm path="/agents/messages/send.php" id="my-assistant-send-form" resetOnSuccess>
                    <input type="hidden" name="to" value={a.id} />
                    <input type="hidden" name="kind" value="request" />
                    {lastThread !== null && <input type="hidden" name="thread" value={lastThread} />}
                    <input type="hidden" name="subject" value="From the OS" />
                    <textarea name="body" className="form-control mb-2" rows={3} required maxLength={20000}
                              placeholder={`Tell ${a.name} what you need…`} id="my-assistant-body" aria-label="Message"></textarea>
                    <SubmitButton className="btn btn-primary" id="my-assistant-send">Send</SubmitButton>
                    <span className="fs-11 text-muted ms-2">It wakes {a.name} at once; its answer appears here.</span>
                  </ActionForm>
                </div>
              </div>
            </div>
            <div className="col-xl-5">
              <div className="card" id="my-assistant-handoffs">
                <div className="card-header"><h5 className="card-title">Handed on</h5></div>
                <ul className="list-group list-group-flush">
                  {data.handoffs.length === 0 && <li className="list-group-item text-muted">Nothing handed on yet.</li>}
                  {data.handoffs.map((h) => (
                    <li className="list-group-item" key={h.run_id} id={`my-assistant-handoff-${h.run_id}`}>
                      <div className="d-flex flex-wrap align-items-center gap-2 fs-12">
                        <span>→ <Link href={`/agents/${h.agent_id}`}>{h.agent_name}</Link>{h.department && <span className="text-muted"> ({h.department})</span>}</span>
                        <span className={`badge bg-soft-${STATUS_TONE[h.status] ?? "secondary"} text-${STATUS_TONE[h.status] ?? "secondary"}`}>{h.status.replace("_", " ")}</span>
                        <span className="text-muted ms-auto">{formatTs(h.started_at, timeZone)}</span>
                      </div>
                      {h.reason && <div className="fs-12 fst-italic mt-1">{h.reason}</div>}
                      {h.result && <details className="mt-1"><summary className="fs-12">What came back</summary>
                        <div className="fs-12 text-muted" style={{ whiteSpace: "pre-wrap" }}>{h.result}</div></details>}
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
