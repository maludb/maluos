import type { FocusKind } from "@/lib/types";

/**
 * Opens this record's focused Agent View (/view/<kind>/<id>): the same record at the centre of
 * the picture, with what this screen shows around it. A full page, never a modal. A plain <a>,
 * not the kit Link: the Agent View lives under its own root layout (its stylesheet must never
 * meet Bootstrap's), so this is a document navigation whichever way it is written.
 */
export default function AgentViewButton({ kind, id, screen }: { kind: FocusKind; id: number; screen: string }) {
  return (
    <a href={`/view/${kind}/${id}`} id={`${screen}-agent-view-btn`} className="btn btn-light-brand" title="See this in the Agent View">
      <i className="feather-share-2 me-2"></i><span>Agent View</span>
    </a>
  );
}
