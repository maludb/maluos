import type { Metadata } from "next";

// Root layout of the day-to-day application: the Bootstrap 5.3 nxl theme, in the order the
// design system fixes (theme.min.css, then app-overrides.css last). A separate root layout
// from (agentview) on purpose — the two stylesheets must never meet on one page.
// The files are html/assets, served at /assets here exactly as Apache serves them.
export const metadata: Metadata = {
  title: { default: "MaluDb OS", template: "%s · MaluDb OS" },
  icons: { shortcut: "/assets/images/favicon.png" },
};

export default function AppRootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* eslint-disable @next/next/no-css-tags */}
        <link rel="stylesheet" type="text/css" href="/assets/css/bootstrap.min.css" />
        <link rel="stylesheet" type="text/css" href="/assets/vendors/css/vendors.min.css" />
        <link rel="stylesheet" type="text/css" href="/assets/css/theme.min.css" />
        <link rel="stylesheet" type="text/css" href="/assets/css/app-overrides.css" />
        {/* eslint-enable @next/next/no-css-tags */}
      </head>
      <body>{children}</body>
    </html>
  );
}
