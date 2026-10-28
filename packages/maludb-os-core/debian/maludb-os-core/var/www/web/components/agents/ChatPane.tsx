"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { markQuiet } from "@/lib/actions";
import { sendChatMessage, stopChatTurn } from "@/lib/agent-chat-actions";

type LiveEvent = { seq: number; event: string; tool: string; status: string | null; duration_ms: number | null };

/**
 * The Chat tab's live half (docs/build-specs/agent-chat.md): the thread (server-rendered, passed as children)
 * above the message box. A turn is a run, so a message is sent, answered at once with the run's id, and the
 * page polls /api/agent-chat while the agent works — its tool calls appear as they happen, Stop cancels the
 * run — and re-reads the page when it ends. State lives on the server: a reload mid-turn finds the running
 * turn in the page data and resumes polling.
 */
export default function ChatPane({
  agentId, agentName, conversationId, canSend, reason, running, messageMax, children,
}: {
  agentId: number;
  agentName: string;
  conversationId: number | null;
  canSend: boolean;
  reason: string | null;
  /** The turn still in flight, if any — from the server's own data. */
  running: { runId: number; startedAt: string | null } | null;
  messageMax: number;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, startSend] = useTransition();
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [pollFailed, setPollFailed] = useState(false);
  const [stopping, setStopping] = useState(false);
  const cursor = useRef(0);
  const scroller = useRef<HTMLDivElement>(null);
  const runId = running?.runId ?? null;
  const startedAt = running?.startedAt ?? null;
  const [now, setNow] = useState(() => Date.now());

  // A new turn starts a fresh trail of tool calls.
  useEffect(() => { cursor.current = 0; setEvents([]); setStopping(false); setPollFailed(false); }, [runId]);

  // Poll the turn in flight; when it has ended, re-read the page so the thread shows the answer.
  useEffect(() => {
    if (runId === null) return;
    let stopped = false;
    const tick = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const res = await fetch(`/api/agent-chat?run=${runId}&after=${cursor.current}`, { cache: "no-store" });
        if (res.status === 401) { window.location.href = "/login"; return; }
        if (!res.ok) { setPollFailed(true); return; }
        const turn = await res.json() as { finished: boolean; events: LiveEvent[] };
        setPollFailed(false);
        if (stopped) return;
        if (turn.events.length > 0) {
          cursor.current = turn.events[turn.events.length - 1].seq;
          setEvents((prev) => [...prev, ...turn.events]);
        }
        if (turn.finished) {
          stopped = true;
          clearInterval(timer);
          await markQuiet();
          router.refresh();
        }
      } catch { setPollFailed(true); }
    };
    const timer = setInterval(tick, 1500);
    void tick();
    // A tab in the background is not polled (it would only add load); the moment it is looked at again, catch up at once —
    // the turn may well have finished while it was hidden.
    const onVisible = () => { if (document.visibilityState === "visible") void tick(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => { stopped = true; clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); window.removeEventListener("focus", onVisible); };
  }, [runId, router]);

  // How long the turn has been going, so a slow start (a Hermes agent takes up to a minute to come up) does not look like a hang.
  useEffect(() => {
    if (runId === null) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [runId]);
  const elapsed = startedAt !== null ? Math.max(0, Math.round((now - new Date(startedAt).getTime()) / 1000)) : null;

  // Keep the newest turn in view.
  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight }); }, [children, events.length, runId]);

  const submit = () => {
    const message = text.trim();
    if (message === "" || sending || !canSend || runId !== null) return;
    setError(null);
    startSend(async () => {
      const result = await sendChatMessage(agentId, conversationId, message);
      if (!result.ok) { setError(result.error); return; }
      setText("");
      const next = new URLSearchParams(search.toString());
      next.set("tab", "chat");
      next.set("c", String(result.conversationId));
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
      router.refresh();
    });
  };

  const stop = async () => {
    if (runId === null) return;
    setStopping(true);
    const result = await stopChatTurn(runId);
    if (!result.ok) { setStopping(false); setError(result.error ?? "The turn could not be stopped."); }
  };

  const tools = events.filter((e) => e.event === "post_tool_call");
  const calling = events.length > 0 && events[events.length - 1].event === "pre_tool_call" ? events[events.length - 1].tool : null;
  const disabled = !canSend || runId !== null || sending;

  return (
    <div className="d-flex flex-column" id="agent-chat-pane">
      <div ref={scroller} className="border rounded p-3 mb-3 bg-white" id="agent-chat-thread" style={{ minHeight: "16rem", maxHeight: "60vh", overflowY: "auto" }}>
        {children}
        {runId !== null && (
          <div className="d-flex align-items-start gap-2 mb-2" id="agent-chat-working" role="status" aria-live="polite">
            <span className="spinner-border spinner-border-sm mt-1 text-primary" aria-hidden="true"></span>
            <div className="fs-13">
              <span className="fw-semibold">{agentName}</span> is working{calling ? <> — calling <code>{calling}</code></> : "…"}
              {elapsed !== null && <span className="text-muted fs-12"> ({elapsed < 90 ? `${elapsed}s` : `${Math.floor(elapsed / 60)} min ${elapsed % 60}s`}{elapsed > 20 && tools.length === 0 && !calling ? " — this agent can take a minute or two" : ""})</span>}
              {tools.length > 0 && <div className="fs-12 text-muted">{tools.length} tool call{tools.length === 1 ? "" : "s"} so far: {tools.slice(-4).map((t) => t.tool).join(", ")}</div>}
              {pollFailed && <div className="fs-12 text-warning">Lost touch for a moment — still trying. The turn keeps running.</div>}
              <button type="button" className="btn btn-sm btn-outline-danger mt-2" id="agent-chat-stop" onClick={stop} disabled={stopping}>
                <i className="feather-square me-1"></i>{stopping ? "Stopping…" : "Stop"}
              </button>
            </div>
          </div>
        )}
      </div>

      {!canSend && reason && <div className="alert alert-secondary py-2 fs-13" id="agent-chat-reason" role="status">{reason}</div>}
      {error && <div className="alert alert-danger py-2 fs-13" id="agent-chat-error" role="alert">{error}</div>}

      <form onSubmit={(e) => { e.preventDefault(); submit(); }} id="agent-chat-form">
        <label htmlFor="agent-chat-input" className="visually-hidden">Message {agentName}</label>
        <textarea id="agent-chat-input" className="form-control mb-2" rows={3} value={text} maxLength={messageMax}
                  placeholder={canSend ? `Message ${agentName} — ask a question or give a task` : "Chat is not available for this agent right now"}
                  disabled={disabled} aria-busy={sending} autoFocus={canSend && runId === null}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }} />
        <div className="d-flex align-items-center gap-3">
          <button type="submit" className="btn btn-primary" id="agent-chat-send" disabled={disabled || text.trim() === ""}>
            <i className="feather-send me-2"></i>{sending ? "Sending…" : "Send"}
          </button>
          <span className="fs-12 text-muted">Enter sends · Shift+Enter for a new line{text.length > messageMax * 0.8 ? ` · ${text.length}/${messageMax}` : ""}</span>
        </div>
      </form>
    </div>
  );
}
