"use client";
/* eslint-disable @next/next/no-img-element */

import { useEffect, useRef, useState } from "react";

/**
 * An agent's picture with its initials as the fallback — agent_avatar_html() in
 * app/features/agents/render.php: the same picture, and the same initials when the image is
 * missing or fails to load, on every screen that shows an agent.
 *
 * Agent photos are served by PHP behind the session (/agents/photo.php), and the browser never
 * talks to PHP — so they come through this app's own /api/avatar relay.
 */
export default function AgentAvatarBadge({
  initials, pictureUrl, sizeClass = "avatar-sm",
}: {
  initials: string;
  pictureUrl: string | null;
  sizeClass?: string;
}) {
  const [failed, setFailed] = useState(false);
  const img = useRef<HTMLImageElement>(null);

  // A server-rendered <img> can fail before React attaches onError; catch that on mount.
  useEffect(() => {
    if (img.current && img.current.complete && img.current.naturalWidth === 0) setFailed(true);
  }, []);

  const src = pictureUrl === null ? null
    : /^(https?:)?\/\//.test(pictureUrl) || pictureUrl.startsWith("data:") ? pictureUrl
    : `/api/avatar?src=${encodeURIComponent(pictureUrl)}`;

  if (src && !failed) {
    return <img ref={img} src={src} alt="" className={`avatar-image ${sizeClass} rounded-circle`} onError={() => setFailed(true)} />;
  }
  return <span className={`avatar-text ${sizeClass} rounded-circle bg-soft-primary text-primary fw-semibold`}>{initials}</span>;
}
