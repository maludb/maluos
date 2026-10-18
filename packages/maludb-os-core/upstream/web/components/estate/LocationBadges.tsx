import { ucfirst } from "@/lib/format";

const KIND: Record<string, string> = { building: "dark", office: "brand", desk: "info", site: "success" };
const PRESENCE: Record<string, string> = { online: "success", offline: "secondary", unknown: "warning" };

export function KindBadge({ kind }: { kind: string }) {
  const c = KIND[kind] ?? "info";
  return <span className={`badge bg-soft-${c} text-${c}`}>{ucfirst(kind)}</span>;
}

/** Presence, or "Retired" when the location is — a retired machine has no presence worth stating. */
export function PresenceBadge({ presence, retired = false }: { presence: string; retired?: boolean }) {
  const c = retired ? "dark" : PRESENCE[presence] ?? "secondary";
  return <span className={`badge bg-soft-${c} text-${c}`}>{retired ? "Retired" : ucfirst(presence)}</span>;
}
