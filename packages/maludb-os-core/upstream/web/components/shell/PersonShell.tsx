import Link from "@/components/kit/Link";
import type { SessionMember } from "@/lib/api";

/**
 * The person face's chrome (app.<domain>, A2 2026-09-22): a top bar and the page. No sidebar — the
 * operating system's navigation belongs to os.<domain>. What a person can do here is sign in,
 * pick an application from the launcher, and keep their own settings.
 */
export default function PersonShell({ member, businessName, logoutAction, children }: {
  member: SessionMember; businessName: string; logoutAction: () => Promise<void>; children: React.ReactNode;
}) {
  return (
    <div className="d-flex flex-column min-vh-100" id="person-shell">
      <header className="border-bottom bg-white">
        <div className="container-xl d-flex align-items-center justify-content-between py-2 px-3" id="person-shell-bar">
          <Link href="/launcher" className="fw-bold text-dark text-decoration-none fs-16" id="person-shell-brand">{businessName}</Link>
          <div className="d-flex align-items-center gap-3 fs-12">
            <span className="text-muted d-none d-sm-inline" id="person-shell-member">{member.display_name}</span>
            <Link href="/settings" className="fw-semibold text-uppercase" id="person-shell-settings">Settings</Link>
            <form action={logoutAction}>
              <button type="submit" className="btn btn-link btn-sm fw-semibold text-uppercase p-0 fs-12" id="person-shell-logout">Sign out</button>
            </form>
          </div>
        </div>
      </header>
      <main className="container-xl flex-grow-1 py-4 px-3" id="page-content">{children}</main>
      <footer className="container-xl px-3 py-3 fs-11 text-muted text-uppercase fw-medium">© {new Date().getFullYear()} {businessName}</footer>
    </div>
  );
}
