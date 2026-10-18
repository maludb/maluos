"use client";

import { useSearchParams } from "next/navigation";
import Link from "./Link";
import { backLabel, isSafeBack } from "@/lib/routes";

export type BackTarget = { href: string; label: string | null };

/**
 * "← Back to …" on a record's page (click-around, R4): the `back` the link that opened this page
 * carried — returning to exactly that URL — else the page's structural parent (`fallback`), so a
 * shared or bookmarked URL still has a way up. Anything but a relative path of ours is ignored.
 */
export default function BackLink({ id, fallback }: { id: string; fallback?: BackTarget }) {
  const raw = useSearchParams().get("back");
  const target: BackTarget | null = isSafeBack(raw) ? { href: raw, label: backLabel(raw) } : fallback ?? null;
  if (target === null) return null;
  return (
    <Link href={target.href} id={`${id}-back`} className="fs-12 text-muted d-inline-flex align-items-center mb-1" data-back={isSafeBack(raw) ? "carried" : "parent"}>
      <i className="feather-arrow-left me-1"></i>Back{target.label ? ` to ${target.label}` : ""}
    </Link>
  );
}
