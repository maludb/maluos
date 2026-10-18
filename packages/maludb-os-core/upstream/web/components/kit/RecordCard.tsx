import Link from "@/components/kit/Link";

/**
 * The card every inventory-style list shows a record as (Applications set the look, 2026-09-21):
 * what is live is a solid card with a brand edge; what is not (retired, ended, suspended) is a
 * dashed, muted one. `facts` are the label/value lines; `footer` holds badges and the actions.
 */
export default function RecordCard({
  id, href, title, icon, avatar, badges, description, facts = [], note, footer, muted = false,
}: {
  id: string;
  href?: string | null;
  title: string;
  /** A feather class for the tile — or pass `avatar` to show a picture or initials instead. */
  icon?: string;
  avatar?: React.ReactNode;
  badges?: React.ReactNode;
  description?: React.ReactNode;
  facts?: [string, React.ReactNode][];
  /** A line in the danger tone under the facts (gaps, warnings). */
  note?: React.ReactNode;
  footer?: React.ReactNode;
  muted?: boolean;
}) {
  return (
    <div className="col-xl-4 col-md-6" id={id} data-state={muted ? "muted" : "live"}>
      <div className={`card h-100 mb-0 ${muted ? "border-dashed bg-transparent shadow-none" : "border-start border-3 border-primary"}`}>
        <div className="card-body d-flex flex-column gap-3">
          <div className="d-flex align-items-start gap-3">
            {avatar ?? (
              <div className={`avatar-text avatar-md rounded flex-shrink-0 ${muted ? "bg-gray-200 text-muted" : "bg-soft-primary text-primary"}`}>
                <i className={icon ?? "feather-grid"}></i>
              </div>
            )}
            <div className="flex-grow-1 overflow-hidden">
              <div className="d-flex flex-wrap align-items-center gap-2">
                {href ? <Link href={href} className="fw-bold text-dark">{title}</Link>
                      : <span className={`fw-bold ${muted ? "text-muted" : "text-dark"}`}>{title}</span>}
                {badges}
              </div>
              {description && <div className="fs-12 text-muted text-truncate-2-line">{description}</div>}
            </div>
          </div>

          {facts.length > 0 && (
            <div className="d-flex flex-column gap-1 fs-12">
              {facts.map(([label, value]) => (
                <div className="d-flex justify-content-between gap-2" key={label}>
                  <span className="text-muted flex-shrink-0">{label}</span>
                  <span className="text-truncate text-end">{value}</span>
                </div>
              ))}
            </div>
          )}

          {note && <div className="fs-11 text-danger">{note}</div>}

          <div className="d-flex flex-wrap align-items-center gap-2 mt-auto">
            {footer}
            {href && (
              <Link href={href} id={`${id}-open`} className="btn btn-sm btn-light-brand ms-auto">
                Open<i className="feather-arrow-right ms-1"></i>
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** A titled group of cards: the heading, what it holds, and the grid. */
export function CardSection({ id, title, href, note, children }: { id: string; title: string; href?: string | null; note?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="mb-4">
      <div className="d-flex align-items-baseline justify-content-between gap-2 mb-3">
        <h6 className="fw-bold mb-0">{href ? <Link href={href} className="text-dark">{title}</Link> : title}</h6>
        {note && <span className="fs-12 text-muted">{note}</span>}
      </div>
      <div className="row g-3">{children}</div>
    </section>
  );
}

/** Group rows under a heading, headings A–Z; rows with no group go last under `fallback`. */
export function groupBy<T>(rows: T[], key: (row: T) => string | null, fallback: string): [string, T[]][] {
  const groups = new Map<string, T[]>();
  const none: T[] = [];
  for (const row of rows) {
    const k = key(row);
    if (k === null || k === "") none.push(row);
    else groups.set(k, [...(groups.get(k) ?? []), row]);
  }
  const out = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  if (none.length > 0) out.push([fallback, none]);
  return out;
}

/** A filter bar in a card of its own, above the sections — the Applications page's header. */
export function CardFilters({ id, title, children }: { id: string; title: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="card" id={id}>
      <div className="card-header flex-wrap gap-2">
        <h5 className="card-title">{title}</h5>
        {children && <div className="d-flex flex-wrap align-items-center gap-2" id={`${id}-filters`}>{children}</div>}
      </div>
    </div>
  );
}

/** What a list says when it has nothing. */
export function CardsEmpty({ id, icon, children }: { id: string; icon: string; children: React.ReactNode }) {
  return (
    <div className="card" id={id}>
      <div className="card-body text-center text-muted py-5">
        <i className={`${icon} fs-1 d-block mb-2 opacity-50`}></i>
        {children}
      </div>
    </div>
  );
}
