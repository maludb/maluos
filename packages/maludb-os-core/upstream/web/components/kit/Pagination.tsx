import Link from "./Link";

/**
 * Server-rendered Bootstrap pagination (design-decisions: the "Traffic Reports" pattern). Every
 * page link carries the whole current query, so filters survive paging.
 */
export default function Pagination({
  id, pathname, query, page, totalPages, label, maxPages,
}: {
  /** Show at most this many page links (the activity trail stops at 20, as its PHP pager did). */
  maxPages?: number;
  id: string;
  pathname: string;
  query: Record<string, string>;
  page: number;
  totalPages: number;
  label: string;
}) {
  if (totalPages <= 1) return null;
  const href = (p: number) => {
    const qs = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== ""));
    if (p > 1) qs.set("page", String(p));
    const s = qs.toString();
    return s === "" ? pathname : `${pathname}?${s}`;
  };
  return (
    <nav className="d-flex justify-content-end p-3" id={id} aria-label={label}>
      <ul className="pagination mb-0">
        {Array.from({ length: maxPages ? Math.min(totalPages, maxPages) : totalPages }, (_, i) => i + 1).map((p) => (
          <li className={`page-item${p === page ? " active" : ""}`} key={p}>
            <Link className="page-link" href={href(p)} scroll={false}>{p}</Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
