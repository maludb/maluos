import ReactMarkdown from "react-markdown";
import ActionForm from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import SubmitButton from "@/components/kit/SubmitButton";
import { StateBadge, money } from "@/components/aiops/AiOpsNav";
import { formatTs } from "@/lib/format";
import { withBack } from "@/lib/routes";
import type { AgentChat, ChatConversation, ChatTurn } from "@/lib/schemas/agents";
import ChatFocusButton from "./ChatFocusButton";
import ChatPane from "./ChatPane";

const seconds = (t: ChatTurn): string | null => {
  if (t.started_at === null || t.finished_at === null) return null;
  const s = Math.round((new Date(t.finished_at).getTime() - new Date(t.started_at).getTime()) / 1000);
  return Number.isFinite(s) && s >= 0 ? (s < 90 ? `${s}s` : `${Math.round(s / 60)} min`) : null;
};

/**
 * The agent page's Chat tab (docs/build-specs/agent-chat.md, db/163): this person's conversations with this
 * agent on the left, the open thread and the message box on the right (stacked at phone width). A turn is one
 * run; each carries a link to it. Conversations are private to their person — the runs behind them stay
 * visible wherever runs are. The live half (send, poll, Stop) is ChatPane.
 */
export default function ChatTab({
  agentId, agentName, chat, timeZone, here, back,
}: {
  agentId: number; agentName: string; chat: AgentChat; timeZone: string; here: string | null; back: string | null;
}) {
  const open = chat.conversation;
  const base = `/agents/${agentId}?tab=chat`;
  const link = (extra: string) => withBack(`${base}${extra}`, back);
  const runningTurn = chat.turns.find((t) => t.status === "running") ?? null;

  const list = (
    <ConversationList conversations={chat.conversations} openId={open?.id ?? null} archivedView={chat.archived_view}
                      blank={open === null && !chat.archived_view} link={link} timeZone={timeZone} />
  );

  return (
    <div className="row g-4" id="agent-chat">
      <div className="col-lg-4 order-2 order-lg-1">
        <div className="d-none d-lg-block">{list}</div>
        <details className="d-lg-none"><summary className="fw-semibold mb-2">Conversations ({chat.conversations.length})</summary>{list}</details>
        <p className="fs-12 text-muted mt-3 mb-0">
          Your conversations are private to you. Every turn is a run of {agentName}, so it shows in the run log, the ledger and the trail like any other work.
        </p>
      </div>

      <div className="col-lg-8 order-1 order-lg-2">
        {open === null && (
          <div className="mb-2" id="agent-chat-header">
            <h6 className="fw-bold mb-0">New conversation <span className="badge bg-soft-primary text-primary ms-1">not started</span></h6>
          </div>
        )}
        {open !== null && (
          <div className="d-flex flex-wrap align-items-center gap-2 mb-2" id="agent-chat-header">
            <h6 className="fw-bold mb-0 me-auto">{open.title || "Untitled"}{open.archived && <span className="badge bg-soft-secondary text-secondary ms-2">archived</span>}</h6>
            <ActionForm path="/agents/chat-rename.php" id="agent-chat-rename-form" className="d-flex gap-2" resetOnSuccess>
              <input type="hidden" name="conversation" value={open.id} />
              <input type="text" name="title" className="form-control form-control-sm" aria-label="Rename this conversation" placeholder="Rename" maxLength={120} required />
              <SubmitButton className="btn btn-sm btn-outline-secondary" id="agent-chat-rename-btn">Rename</SubmitButton>
            </ActionForm>
            <ActionForm path="/agents/chat-archive.php" id="agent-chat-archive-form">
              <input type="hidden" name="conversation" value={open.id} />
              <input type="hidden" name="archive" value={open.archived ? "0" : "1"} />
              <SubmitButton className="btn btn-sm btn-outline-secondary" id="agent-chat-archive-btn">{open.archived ? "Restore" : "Archive"}</SubmitButton>
            </ActionForm>
          </div>
        )}

        {/* Keyed by conversation: opening another, or a new one, starts the message box and the poll afresh. */}
        <ChatPane key={open?.id ?? "new"} agentId={agentId} agentName={agentName} conversationId={open?.id ?? null}
                  canSend={chat.can_send} reason={chat.reason} messageMax={chat.message_max}
                  running={runningTurn ? { runId: runningTurn.run_id, startedAt: runningTurn.started_at } : null}>
          {chat.turns.length === 0 ? (
            <p className="text-muted mb-0" id="agent-chat-empty">
              {open === null ? <>Start a conversation with {agentName}: ask a question, or give it a task — it works with its own tools and says what it did. <strong>Type your message in the box below.</strong> <i className="feather-arrow-down ms-1"></i></> : "No turns yet."}
            </p>
          ) : chat.turns.map((t) => <Turn key={t.run_id} turn={t} agentName={agentName} timeZone={timeZone} here={here} />)}
        </ChatPane>
      </div>
    </div>
  );
}

function ConversationList({ conversations, openId, archivedView, blank, link, timeZone }: {
  conversations: ChatConversation[]; openId: number | null; archivedView: boolean; blank: boolean; link: (extra: string) => string; timeZone: string;
}) {
  return (
    <div id="agent-chat-conversations">
      <div className="d-flex align-items-center mb-2">
        <h6 className="fw-bold mb-0 me-auto">{archivedView ? "Archived" : "Conversations"}</h6>
        {blank
          ? <ChatFocusButton id="agent-chat-new"><i className="feather-plus me-1"></i>New</ChatFocusButton>
          : <Link href={link("&c=new")} className="btn btn-sm btn-primary" id="agent-chat-new"><i className="feather-plus me-1"></i>New</Link>}
      </div>
      {conversations.length === 0 && !blank ? (
        <p className="text-muted fs-13 mb-2">{archivedView ? "Nothing archived." : "No conversations yet."}</p>
      ) : (
        <ul className="list-group mb-2">
          {blank && (
            <li className="list-group-item active px-3 py-2" id="agent-chat-conversation-new" aria-current="true">
              <div className="fw-semibold fs-13">New conversation</div>
              <div className="fs-11">Send a message to begin</div>
            </li>
          )}
          {conversations.map((c) => (
            <li key={c.id} className={`list-group-item p-0${c.id === openId ? " active" : ""}`}>
              <Link href={link(`&c=${c.id}${archivedView ? "&archived=1" : ""}`)} className={`d-block px-3 py-2 text-decoration-none${c.id === openId ? " text-white" : ""}`} id={`agent-chat-conversation-${c.id}`}>
                <div className="fw-semibold fs-13 text-truncate">{c.title || "Untitled"}</div>
                <div className={`fs-11 ${c.id === openId ? "" : "text-muted"}`}>{c.turns} turn{c.turns === 1 ? "" : "s"}{c.last_at ? ` · ${formatTs(c.last_at, timeZone, false)}` : ""}</div>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Link href={archivedView ? link("") : link("&archived=1")} className="fs-12" id="agent-chat-archived-toggle">{archivedView ? "← Back to conversations" : "Archived conversations"}</Link>
    </div>
  );
}

function Turn({ turn: t, agentName, timeZone, here }: { turn: ChatTurn; agentName: string; timeZone: string; here: string | null }) {
  const took = seconds(t);
  return (
    <div className="mb-3" id={`agent-chat-turn-${t.run_id}`}>
      <div className="d-flex justify-content-end mb-2">
        <div className="rounded px-3 py-2 bg-primary text-white" style={{ maxWidth: "85%", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{t.said}</div>
      </div>
      {t.status !== "running" && (
        <div className="d-flex justify-content-start">
          <div className="rounded px-3 py-2 bg-light border" style={{ maxWidth: "92%", overflowWrap: "anywhere" }}>
            <div className="fs-12 fw-semibold text-muted mb-1">{agentName}{t.started_at ? ` · ${formatTs(t.started_at, timeZone, false)}` : ""}</div>
            {t.reply !== null && t.reply !== "" && <div className="agent-chat-reply"><ReactMarkdown skipHtml>{t.reply}</ReactMarkdown></div>}
            {t.status === "failed" && <div className="text-danger fs-13">{t.error ?? "The run failed."}</div>}
            {t.status === "cancelled" && <div className="text-muted fs-13">Stopped before {agentName} finished.</div>}
            {t.status === "awaiting_approval" && (
              <div className="alert alert-warning py-2 fs-13 mt-2 mb-0">
                <i className="feather-pause-circle me-1"></i>Paused for an approval
                {t.approval_request_id !== null && <> — <Link href={withBack(`/approvals/${t.approval_request_id}`, here)}>open request #{t.approval_request_id}</Link></>}.
                <div className="fs-12 text-muted">An approver can ask {agentName} to carry on; that follow-up is a separate run, not part of this thread.</div>
              </div>
            )}
            <div className="fs-11 text-muted mt-2 d-flex flex-wrap gap-2 align-items-center">
              <StateBadge state={t.status} />
              {took && <span>{took}</span>}
              {t.cost !== null && t.currency !== null && Number(t.cost) > 0 && <span>{money(t.cost, t.currency)}</span>}
              <Link href={withBack(`/ai/runs/${t.run_id}`, here)} id={`agent-chat-run-${t.run_id}`}>Run #{t.run_id}</Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
