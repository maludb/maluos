import Link from "./Link";
import { memberHref, withBack, type MemberRef } from "@/lib/routes";

/**
 * A member's name as the right link (click-around, R1): an agent to its page, a person to theirs,
 * carrying `here` so that page can come back. No id → plain text. `kind` overrides what the row
 * says (a field that is always an agent passes kind="agent").
 */
export default function Who({ who, name, kind, here, className }: {
  who: MemberRef & { name?: string | null };
  name?: string | null;
  kind?: string | null;
  here?: string | null;
  className?: string;
}) {
  const label = name ?? who.name ?? (who.id !== null && who.id !== undefined ? `#${who.id}` : "—");
  const href = memberHref({ id: who.id, kind: kind ?? who.kind });
  return href ? <Link href={withBack(href, here)} className={className}>{label}</Link> : <span className={className}>{label}</span>;
}
