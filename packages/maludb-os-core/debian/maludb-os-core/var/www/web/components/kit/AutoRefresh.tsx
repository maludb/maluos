"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { markQuiet } from "@/lib/actions";

/**
 * Re-read this screen's server data every `seconds` while it sits open — the counterpart of
 * `hx-trigger="every 60s"`. The re-read is marked quiet first, so it is never a screen view.
 * Pauses while the tab is hidden.
 */
export default function AutoRefresh({ seconds }: { seconds: number }) {
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(async () => {
      if (document.visibilityState !== "visible") return;
      await markQuiet();
      router.refresh();
    }, seconds * 1000);
    return () => clearInterval(timer);
  }, [router, seconds]);
  return null;
}
