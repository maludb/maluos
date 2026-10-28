"use client";

import { useLayoutEffect } from "react";

/**
 * Puts the theme's dark skin on <html> for the pages that render this — the sign-in screens
 * (owner, 2026-09-19: they follow the dark landing page, and a white card after it is a flash).
 *
 * Two halves, because <html> belongs to the root layout: the inline script runs while the
 * document is still being parsed, so a first load never paints light; the layout effect covers
 * arriving by client-side navigation (after logging out), where an inline script does not run.
 * There is no cleanup on purpose — the workspace shell sets the skin from the person's own
 * stored preference as soon as it mounts, and it is the one that should decide.
 */
export default function DarkSkin() {
  useLayoutEffect(() => {
    document.documentElement.classList.add("app-skin-dark");
  }, []);
  return <script dangerouslySetInnerHTML={{ __html: 'document.documentElement.classList.add("app-skin-dark")' }} />;
}
