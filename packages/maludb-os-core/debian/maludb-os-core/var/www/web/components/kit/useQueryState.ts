"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useTransition } from "react";

/**
 * List state lives in the URL (?q=&kind=&page=) — the React counterpart of hx-get +
 * hx-push-url: shareable, back-button friendly, and the server page is the only reader.
 * Changing any filter returns to page 1. `replace` for keystrokes, `push` for deliberate picks.
 */
export function useQueryState() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [pending, startTransition] = useTransition();

  const setParam = useCallback(
    (name: string, value: string, mode: "push" | "replace" = "push") => {
      const next = new URLSearchParams(params.toString());
      if (value === "") next.delete(name);
      else next.set(name, value);
      if (name !== "page") next.delete("page");
      const qs = next.toString();
      const url = qs === "" ? pathname : `${pathname}?${qs}`;
      startTransition(() => (mode === "replace" ? router.replace(url, { scroll: false }) : router.push(url, { scroll: false })));
    },
    [params, pathname, router],
  );

  return { setParam, pending };
}
