import type { NavItem } from "./api";

/**
 * Where a sidebar entry goes. The menu is data (nav_items, db/127): an entry of ours keeps its
 * path minus the trailing slash (Next.js canonicalises those away); an external application's
 * address is used exactly as recorded.
 */
export function navHref(item: NavItem): string {
  if (item.opens === "new_tab") return item.url;
  return item.url.length > 1 ? item.url.replace(/\/+$/, "") : item.url;
}

const covers = (prefix: string, pathname: string) => pathname === prefix || pathname.startsWith(prefix + "/");

/**
 * The nav item a path belongs to: the longest prefix that is the path or a parent of it, taken
 * over each entry's own href AND its active_patterns — the screens that live under another path
 * but belong to this entry (People & access under /team is part of Agent Workforce, while
 * /team/departments, being longer, stays with Departments). An external entry is never active.
 */
export function activeNavKey(pathname: string, items: NavItem[]): string | null {
  let best: { key: string; length: number } | null = null;
  for (const item of items) {
    if (item.opens === "new_tab") continue;
    for (const raw of [navHref(item), ...item.active_patterns]) {
      const prefix = raw.length > 1 ? raw.replace(/\/+$/, "") : raw;
      if (covers(prefix, pathname) && (best === null || prefix.length > best.length)) {
        best = { key: item.key, length: prefix.length };
      }
    }
  }
  return best?.key ?? null;
}
