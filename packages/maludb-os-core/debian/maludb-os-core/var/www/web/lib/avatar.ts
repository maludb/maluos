import type { ViewMode } from "./types";

/** Resolves a node's avatar_url to something the browser can actually load. Demo avatars
 * are self-contained data: URIs. Live avatars are relative platform paths that require an
 * authenticated session, so they route through our own server-side proxy. */
export function resolveAvatarSrc(mode: ViewMode, avatarUrl: string | undefined): string | null {
  if (!avatarUrl) return null;
  if (avatarUrl.startsWith("data:") || /^https?:\/\//.test(avatarUrl)) return avatarUrl;
  if (mode === "demo") return avatarUrl;
  return `/api/avatar?src=${encodeURIComponent(avatarUrl)}`;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}
