"use client";
/* eslint-disable @next/next/no-img-element */

import { forwardRef, useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Dropdown from "react-bootstrap/Dropdown";
import Link from "@/components/kit/Link";
import type { Session, SessionMember } from "@/lib/api";
import { activeNavKey, navHref } from "@/lib/nav";

/**
 * The nxl app shell — markup copied from app/views/layout.php (nxl-* classes and the
 * #mobile-collapse / #menu-mini-button ids are load-bearing for theme.min.css). The theme's
 * jQuery scripts are not loaded; the three behaviours they provided are reimplemented here
 * with the same classes AND the same localStorage keys, so a preference set in the legacy UI
 * carries over:
 *   mini sidebar  → `minimenu` on <html>        (nexel-classic-dashboard-menu-mini-theme)
 *   mobile nav    → `mob-navigation-active` on the nav + .nxl-menu-overlay
 *   dark mode     → `app-skin-dark` on <html>    (app-skin-dark)
 */
const MINI_KEY = "nexel-classic-dashboard-menu-mini-theme";
const SKIN_KEY = "app-skin-dark";

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // Private mode / blocked storage: the preference simply does not persist.
  }
}

export default function Shell({
  member,
  nav,
  businessName,
  logoUrl = null,
  logoutAction,
  children,
}: {
  member: SessionMember;
  nav: Session["nav"];
  businessName: string;
  /** The company's own logo (session.business.logo_url); null shows the shipped logo-full.png. */
  logoUrl?: string | null;
  logoutAction: () => Promise<void>;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [mini, setMini] = useState(false);
  const [dark, setDark] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Initial state: the stored preference, else the theme's width rule (mini between 1024 and 1600).
  useEffect(() => {
    const width = window.innerWidth;
    setMini(readStorage(MINI_KEY) !== null || (width >= 1024 && width <= 1600));
    setDark(readStorage(SKIN_KEY) === "app-skin-dark");
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("minimenu", mini);
  }, [mini]);
  useEffect(() => {
    document.documentElement.classList.toggle("app-skin-dark", dark);
  }, [dark]);

  // Navigating closes the mobile drawer.
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const toggleMini = useCallback((next: boolean) => {
    setMini(next);
    writeStorage(MINI_KEY, next ? "menu-mini-theme" : null);
  }, []);
  const toggleDark = useCallback((next: boolean) => {
    setDark(next);
    writeStorage(SKIN_KEY, next ? "app-skin-dark" : "app-skin-light");
  }, []);

  const allItems = nav.flatMap((g) => g.items);
  const activeKey = activeNavKey(pathname, allItems);

  // The uploaded logo is served by PHP behind the session, so it comes through this app's own
  // picture relay (web/app/api/avatar) — the browser never talks to PHP. A logo the relay cannot
  // produce (the file gone from disk) falls back to the shipped one rather than a broken image.
  const [logoFailed, setLogoFailed] = useState(false);
  useEffect(() => { setLogoFailed(false); }, [logoUrl]);
  const fullLogo = logoUrl && !logoFailed ? `/api/avatar?src=${encodeURIComponent(logoUrl)}` : "/assets/images/logo-full.png";

  return (
    <>
      <nav className={`nxl-navigation${mobileOpen ? " mob-navigation-active" : ""}`} id="left-sidenav">
        <div className="navbar-wrapper">
          <div className="m-header">
            <Link href="/" className="b-brand">
              <img src={fullLogo} alt={businessName} className="logo logo-lg" onError={() => setLogoFailed(true)} />
              <img src="/assets/images/logo-abbr.png" alt="" className="logo logo-sm" />
            </Link>
          </div>
          <div className="navbar-content">
            <ul className="nxl-navbar">
              {nav.map((group) => (
                <NavGroup key={group.group} label={group.group}>
                  {group.items.map((item) => (
                    <li className="nxl-item" id={`nav-${item.key}`} key={item.key}>
                      {item.opens === "new_tab" ? (
                        // An external application: its own address, in its own tab.
                        <a className="nxl-link" href={navHref(item)} target="_blank" rel="noopener noreferrer">
                          <span className="nxl-micon"><i className={item.icon}></i></span>
                          <span className="nxl-mtext">{item.label}<i className="feather-external-link fs-11 ms-2 opacity-50"></i></span>
                        </a>
                      ) : (
                        <Link className={`nxl-link${activeKey === item.key ? " active" : ""}`} href={navHref(item)}>
                          <span className="nxl-micon"><i className={item.icon}></i></span>
                          <span className="nxl-mtext">{item.label}</span>
                        </Link>
                      )}
                    </li>
                  ))}
                </NavGroup>
              ))}
              {/* Signing out is also in the avatar menu, where it is easy to miss. A form, not a
                  link: logout is a POST with the CSRF token (a GET logout is a CSRF vector). */}
              <li className="nxl-item" id="nav-logout">
                <form action={logoutAction}>
                  <button type="submit" id="sidenav-logout-btn" className="nxl-link border-0 bg-transparent w-100 text-start">
                    <span className="nxl-micon"><i className="feather-log-out"></i></span>
                    <span className="nxl-mtext">Log out</span>
                  </button>
                </form>
              </li>
            </ul>
          </div>
        </div>
        {mobileOpen && <div className="nxl-menu-overlay" onClick={() => setMobileOpen(false)}></div>}
      </nav>

      <header className="nxl-header">
        <div className="header-wrapper">
          <div className="header-left d-flex align-items-center gap-4">
            <button type="button" className="nxl-head-mobile-toggler border-0 bg-transparent p-0" id="mobile-collapse"
                    aria-label="Toggle navigation" aria-expanded={mobileOpen} onClick={() => setMobileOpen((v) => !v)}>
              <div className={`hamburger hamburger--arrowturn${mobileOpen ? " is-active" : ""}`}>
                <div className="hamburger-box"><div className="hamburger-inner"></div></div>
              </div>
            </button>
            <div className="nxl-navigation-toggle">
              {mini ? (
                <a href="#" id="menu-expend-button" aria-label="Expand navigation"
                   onClick={(e) => { e.preventDefault(); toggleMini(false); }}>
                  <i className="feather-arrow-right"></i>
                </a>
              ) : (
                <a href="#" id="menu-mini-button" aria-label="Collapse navigation"
                   onClick={(e) => { e.preventDefault(); toggleMini(true); }}>
                  <i className="feather-align-left"></i>
                </a>
              )}
            </div>
          </div>
          <div className="header-right ms-auto">
            <div className="d-flex align-items-center">
              <div className="nxl-h-item">
                <Link href="/" className="nxl-head-link me-0" id="header-agent-view-btn" title="Agent View">
                  <i className="feather-share-2"></i>
                </Link>
              </div>
              <div className="nxl-h-item dark-light-theme">
                {dark ? (
                  <a href="#" className="nxl-head-link me-0 light-button" aria-label="Light mode"
                     onClick={(e) => { e.preventDefault(); toggleDark(false); }}>
                    <i className="feather-sun"></i>
                  </a>
                ) : (
                  <a href="#" className="nxl-head-link me-0 dark-button" aria-label="Dark mode"
                     onClick={(e) => { e.preventDefault(); toggleDark(true); }}>
                    <i className="feather-moon"></i>
                  </a>
                )}
              </div>
              <Dropdown className="nxl-h-item" align="end" autoClose="outside">
                {/* No onClick here: react-bootstrap's own click handler is what opens the menu, and a
                    handler passed to the toggle REPLACES it — the menu never opened (owner, 2026-09-19).
                    AvatarToggle stops the "#" from navigating and then calls the handler it was given. */}
                <Dropdown.Toggle as={AvatarToggle} bsPrefix="nxl-user-toggle" id="header-user-menu">
                  <img src="/assets/images/avatar/1.png" alt="user" className="img-fluid user-avtar me-0" />
                </Dropdown.Toggle>
                <Dropdown.Menu className="nxl-h-dropdown nxl-user-dropdown">
                  <div className="dropdown-header">
                    <div className="d-flex align-items-center">
                      <img src="/assets/images/avatar/1.png" alt="user" className="img-fluid user-avtar" />
                      <div>
                        <h6 className="text-dark mb-0">{member.display_name}</h6>
                        <span className="fs-12 fw-medium text-muted">{member.email}</span>
                      </div>
                    </div>
                  </div>
                  <div className="dropdown-divider"></div>
                  <Link href="/settings" className="dropdown-item">
                    <i className="feather-settings"></i><span>Settings</span>
                  </Link>
                  <div className="dropdown-divider"></div>
                  <form action={logoutAction} className="px-2">
                    <button type="submit" id="header-logout-btn" className="dropdown-item border-0 bg-transparent w-100 text-start">
                      <i className="feather-log-out"></i><span>Logout</span>
                    </button>
                  </form>
                </Dropdown.Menu>
              </Dropdown>
            </div>
          </div>
        </div>
      </header>

      <main className="nxl-container">
        <div className="nxl-content" id="page-content">{children}</div>
        <footer className="footer">
          <p className="fs-11 text-muted fw-medium text-uppercase mb-0 copyright">
            <span>© {new Date().getFullYear()} {businessName}</span>
          </p>
          <div className="d-flex align-items-center gap-4">
            <Link href="/settings" className="fs-11 fw-semibold text-uppercase">Settings</Link>
          </div>
        </footer>
      </main>
    </>
  );
}

/** The avatar menu's trigger: an anchor styled by the theme, that never navigates. */
const AvatarToggle = forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(
  function AvatarToggle({ onClick, children, ...rest }, ref) {
    return (
      <a {...rest} ref={ref} href="#" role="button"
         onClick={(e) => { e.preventDefault(); onClick?.(e); }}>
        {children}
      </a>
    );
  },
);

function NavGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      {/* The first group — what a person opens every day — has no heading. */}
      {label !== "" && <li className="nxl-item nxl-caption"><label>{label}</label></li>}
      {children}
    </>
  );
}
