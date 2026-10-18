/** Display helpers that mirror PHP's, so a converted screen reads the same as the one it replaces. */

/** "2026-09-18" from an ISO timestamp — the list screens' date column. */
export function dateOnly(iso: string | null): string {
  return iso === null ? "" : iso.slice(0, 10);
}

/** ucfirst() */
export function ucfirst(s: string): string {
  return s === "" ? s : s[0].toUpperCase() + s.slice(1);
}

/**
 * A timestamp in the viewer's timezone — PHP's format_ts(): "Sep 18, 2026 2:30 PM", or without
 * the year ("Sep 18, 2:30 PM") where the legacy screen dropped it.
 */
export function formatTs(iso: string | null, timeZone: string, withYear = true): string {
  if (iso === null) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timeZone || "UTC", month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  }).formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const day = `${get("month")} ${get("day")}`;
  const time = `${get("hour")}:${get("minute")} ${get("dayPeriod")}`;
  return withYear ? `${day}, ${get("year")} ${time}` : `${day}, ${time}`;
}

/** A date in the viewer's timezone — PHP's format_ts($x, $tz, 'M j, Y'): "Sep 18, 2026". */
export function formatDate(iso: string | null, timeZone: string): string {
  if (iso === null) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", { timeZone: timeZone || "UTC", month: "short", day: "numeric", year: "numeric" }).format(date);
}
