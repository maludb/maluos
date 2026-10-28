"use client";

import { Suspense, useState } from "react";
import BackLink, { type BackTarget } from "./BackLink";
import Link from "./Link";

/**
 * The design system's page header (components.md, "Page header / breadcrumb / title with
 * action buttons") — first child of .nxl-content, before .main-content. Action buttons are the
 * children; on mobile they collapse behind the open/close toggles, which the theme's jQuery
 * used to drive by flipping page-header-right-open / -close. `back` is the page's structural
 * parent: the "Back to …" line above the title shows the `back` the opening link carried, else
 * this (click-around, R4 — docs/build-specs/click-around.md).
 */
export type Crumb = { label: string; href?: string };

export default function PageHeader({
  title,
  icon,
  crumbs = [],
  id,
  back,
  home = "/dashboard",
  children,
}: {
  title: string;
  /** An icon class shown before the title, where the PHP header had one (e.g. a location's kind). */
  icon?: string;
  crumbs?: Crumb[];
  /** Screen id prefix, per the id scheme (e.g. "contacts-list"). */
  id: string;
  /** Where "Back" goes when the link that opened this page carried no `back` of its own. */
  back?: BackTarget;
  /** The first crumb's target — the OS dashboard, or `/launcher` on the app face (the launcher passes it). */
  home?: string;
  children?: React.ReactNode;
}) {
  const [open, setOpen] = useState<boolean | null>(null);
  const state = open === null ? "" : open ? " page-header-right-open" : " page-header-right-close";

  return (
    <div className="page-header" id={`${id}-header`}>
      <div className="page-header-left d-flex align-items-center">
        <div className="page-header-title">
          {back && <Suspense fallback={null}><BackLink id={id} fallback={back} /></Suspense>}
          <h5 className="m-b-10">{icon && <i className={`${icon} me-2`}></i>}{title}</h5>
        </div>
        <ul className="breadcrumb">
          <li className="breadcrumb-item"><Link href={home}>Home</Link></li>
          {crumbs.map((c) => (
            <li className="breadcrumb-item" key={c.label}>
              {c.href ? <Link href={c.href}>{c.label}</Link> : c.label}
            </li>
          ))}
        </ul>
      </div>
      {children && (
        <div className="page-header-right ms-auto">
          <div className={`page-header-right-items${state}`}>
            <div className="d-flex d-md-none">
              <a href="#" className="page-header-right-close-toggle"
                 onClick={(e) => { e.preventDefault(); setOpen(false); }}>
                <i className="feather-arrow-left me-2"></i>
                <span>Back</span>
              </a>
            </div>
            <div className="d-flex align-items-center gap-2 page-header-right-items-wrapper">{children}</div>
          </div>
          <div className="d-md-none d-flex align-items-center">
            <a href="#" className="page-header-right-open-toggle" aria-label="Show actions"
               onClick={(e) => { e.preventDefault(); setOpen(true); }}>
              <i className="feather-align-right fs-20"></i>
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
