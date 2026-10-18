"use client";

/** "New" on a conversation that is already blank: there is nothing to open, so take the person to the message box. */
export default function ChatFocusButton({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <button type="button" className="btn btn-sm btn-primary" id={id}
            onClick={() => {
              const box = document.getElementById("agent-chat-input") as HTMLTextAreaElement | null;
              box?.scrollIntoView({ block: "center", behavior: "smooth" });
              box?.focus();
            }}>
      {children}
    </button>
  );
}
