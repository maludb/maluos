"use client";

import { useActionState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { submitToPlatform, type ActionState, type ActionTarget } from "@/lib/actions";

/**
 * A form that posts to a PHP write handler — the React counterpart of `hx-post`. Used for the
 * small in-place writes (archive, merge, delete, add a tag, post a note) and as the engine
 * under RecordForm. `confirm` is the design system's standard guard on destructive actions
 * (the browser confirm dialog, as hx-confirm was — confirmations are exempt from the no-modal
 * rule). After a success that does not navigate, the page's server data is re-read.
 */
export default function ActionForm({
  path,
  follow = false,
  confirm,
  resetOnSuccess = false,
  id,
  className,
  children,
  renderState,
}: {
  path: string;
  follow?: boolean;
  confirm?: string;
  resetOnSuccess?: boolean;
  id?: string;
  className?: string;
  children: React.ReactNode;
  /** Where to show the outcome; defaults to a compact alert under the form. */
  renderState?: (state: ActionState) => React.ReactNode;
}) {
  const target: ActionTarget = { path, follow };
  const [state, action, pending] = useActionState<ActionState, FormData>(submitToPlatform.bind(null, target), { status: "idle" });
  const router = useRouter();
  const form = useRef<HTMLFormElement>(null);
  const typed = useRef<[string, string][]>([]);

  useEffect(() => {
    if (state.status === "ok") {
      if (resetOnSuccess) form.current?.reset();
      router.refresh();
      return;
    }
    // React clears an uncontrolled form once its action has run — also when PHP refused it, so a
    // mistyped address had to be typed again. After anything but success, what the person typed
    // goes back. (Hidden inputs never change; ticks, radios and files are left as React left them.)
    if (state.status !== "idle" && form.current) {
      for (const [name, value] of typed.current) {
        const field = form.current.elements.namedItem(name);
        if (field instanceof HTMLInputElement && ["hidden", "checkbox", "radio", "file", "password"].includes(field.type)) continue;
        if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement) {
          field.value = value;
        }
      }
    }
  }, [state, resetOnSuccess, router]);

  return (
    <>
      <form ref={form} id={id} className={className} action={action} aria-busy={pending}
            onSubmit={(e) => {
              if (confirm && !window.confirm(confirm)) { e.preventDefault(); return; }
              typed.current = [...new FormData(e.currentTarget)].filter((pair): pair is [string, string] => typeof pair[1] === "string");
            }}>
        {children}
      </form>
      {renderState ? renderState(state) : <ActionOutcome state={state} />}
    </>
  );
}

/** The outcome of a write, in the theme's alerts. Success is silent — the refreshed page shows it. */
export function ActionOutcome({ state, id }: { state: ActionState; id?: string }) {
  if (state.status === "idle" || state.status === "ok") return null;
  if (state.status === "pending_approval") {
    return <div className="alert alert-warning mt-2 mb-0" role="alert" id={id}>{state.message}</div>;
  }
  if (state.status === "invalid") {
    return (
      <div className="alert alert-danger mt-2 mb-0" role="alert" id={id}>
        <ul className="mb-0">{state.errors.map((e) => <li key={e}>{e}</li>)}</ul>
      </div>
    );
  }
  return <div className="alert alert-danger mt-2 mb-0" role="alert" id={id}>{state.message}</div>;
}
