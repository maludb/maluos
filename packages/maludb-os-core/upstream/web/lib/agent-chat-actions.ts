"use server";

import { redirect } from "next/navigation";
import { ApiError, apiPost } from "./api";
import { markQuiet } from "./actions";

/**
 * The Chat tab's two writes that need an answer back (docs/build-specs/agent-chat.md): sending a message
 * (PHP answers at once with the run and the conversation) and stopping a turn. Rename and archive are plain
 * ActionForms. PHP stays the authority — gate, CSRF, the busy check, activity logging.
 */
export type ChatSendResult =
  | { ok: true; runId: number; conversationId: number }
  | { ok: false; error: string };

export async function sendChatMessage(agentId: number, conversationId: number | null, message: string): Promise<ChatSendResult> {
  try {
    const answer = await apiPost<{ run_id: number; conversation_id: number }>("/agents/chat-send.php", {
      agent: agentId, message, ...(conversationId !== null ? { conversation: conversationId } : {}),
    });
    await markQuiet();
    return { ok: true, runId: answer.run_id, conversationId: answer.conversation_id };
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    if (err.status === 401) redirect("/login");
    return { ok: false, error: err.message };
  }
}

export async function stopChatTurn(runId: number): Promise<{ ok: boolean; error?: string }> {
  try {
    await apiPost("/agents/run-cancel.php", { agent_run: runId });
    return { ok: true };
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    if (err.status === 401) redirect("/login");
    return { ok: false, error: err.message };
  }
}
