"use client";

import { useState } from "react";
import { resolveAvatarSrc, initials } from "@/lib/avatar";
import type { ViewMode } from "@/lib/types";

export default function AgentAvatar({
  mode,
  avatarUrl,
  name,
  size,
  ring,
}: {
  mode: ViewMode;
  avatarUrl: string | undefined;
  name: string;
  size: number;
  ring: string;
}) {
  const src = resolveAvatarSrc(mode, avatarUrl);
  const [failed, setFailed] = useState(false);

  if (!src || failed) {
    return (
      <div
        className="agent-avatar agent-avatar-fallback"
        style={{ width: size, height: size, borderColor: ring, color: ring }}
        aria-hidden="true"
      >
        {initials(name)}
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element -- avatar host is dynamic/authenticated, not a static-optimizable asset
    <img
      className="agent-avatar"
      src={src}
      alt=""
      width={size}
      height={size}
      style={{ width: size, height: size, borderColor: ring }}
      onError={() => setFailed(true)}
    />
  );
}
