"use client";

import { useActionState, useCallback, useTransition, type FormEvent } from "react";
import { submitToPlatform, type ActionState } from "@/lib/actions";

/**
 * The engine under every full-page create/edit form. Posts the form to its PHP save handler
 * and follows PHP to the saved record — with the trail the form page was opened with (`back`,
 * click-around R5: an edit returns to the record's page as it was, a create lands on the new
 * record with the list as its back). Submitted by hand rather than through <form action>,
 * because React resets a form after its action runs — and a form refused by validation must
 * keep what the person typed.
 */
export function useRecordForm(path: string, back: string | null = null) {
  const [state, dispatch] = useActionState<ActionState, FormData>(
    submitToPlatform.bind(null, { path, follow: true, back }),
    { status: "idle" },
  );
  const [pending, startTransition] = useTransition();

  const onSubmit = useCallback(
    (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const data = new FormData(e.currentTarget);
      startTransition(() => dispatch(data));
    },
    [dispatch],
  );

  return { state, pending, onSubmit };
}
