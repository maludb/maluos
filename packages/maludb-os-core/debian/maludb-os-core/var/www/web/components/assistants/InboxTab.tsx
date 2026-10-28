import Link from "@/components/kit/Link";
import { formatTs } from "@/lib/format";
import type { AgentInbox } from "@/lib/schemas/assistants";

const KIND_TONE: Record<string, string> = {
  request: "primary", result: "success", question: "warning", decision_needed: "danger", fyi: "secondary", reply: "info",
};

/**
 * The agent page's Inbox tab (db/155–156): what the agent was sent and what it sent, newest first — to
 * its orchestrator, its roster, the leads beside it, or (an assistant) its person — and the channels it
 * answers on. What a message says is the sender's; the agent treats it as information, never an order.
 */
export default function InboxTab({ inbox, timeZone }: { inbox: AgentInbox; timeZone: string }) {
  return (
    <div id="agent-inbox">
      {inbox.endpoints.length > 0 && (
        <p className="fs-12 text-muted mb-3" id="agent-inbox-endpoints">
          Reached on: {inbox.endpoints.map((e, i) => <span key={e.channel}>{i > 0 && " · "}{e.channel} <code>{e.address}</code></span>)}
        </p>
      )}
      {inbox.messages.length === 0 ? (
        <p className="text-muted mb-0">No messages yet. Agents message along the tree: their orchestrator, their roster, the leads beside them.</p>
      ) : (
        <ul className="list-unstyled mb-0">
          {inbox.messages.map((m) => (
            <li key={m.id} className="border-bottom py-2" id={`agent-inbox-message-${m.id}`}>
              <div className="d-flex flex-wrap align-items-center gap-2 fs-12">
                <span className={`badge bg-soft-${KIND_TONE[m.kind] ?? "secondary"} text-${KIND_TONE[m.kind] ?? "secondary"}`}>{m.kind.replace("_", " ")}</span>
                {m.priority === "urgent" && <span className="badge bg-soft-danger text-danger">urgent</span>}
                <span>{m.outgoing ? "to" : "from"}{" "}
                  {m.other_kind === "agent" ? <Link href={`/agents/${m.other_id}`}>{m.other_name}</Link> : m.other_name}</span>
                {m.channel !== "internal" && <span className="text-muted">via {m.channel}</span>}
                <span className="text-muted ms-auto">{formatTs(m.created_at, timeZone)}</span>
              </div>
              <div className="fw-semibold fs-13 mt-1">{m.subject} <span className="text-muted fw-normal fs-11">thread {m.thread_id}</span></div>
              <div className="fs-12 text-muted" style={{ whiteSpace: "pre-wrap" }}>{m.body.length > 600 ? m.body.slice(0, 600) + "…" : m.body}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
