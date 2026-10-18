import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import Nl2br from "@/components/kit/Nl2br";
import { formatTs } from "@/lib/format";
import type { RecordComment } from "@/lib/schemas/records";

/**
 * Stacked-card rule: these shared cards sit in a column WITH other cards, so they are plain
 * `.card`. The theme's `stretch stretch-full` means "be as tall as the whole row" — right for a
 * column's only card, wrong for stacked ones: each becomes row-height, the excess scrolls inside
 * .main-content, and the page cannot reach its own bottom (reported by the owner 2026-09-18).
 */
/** Comment thread for any record (app/views/shared/comments.php). Writes: /comments/save.php, /comments/delete.php. */
export default function Notes({
  entityType, entityId, comments, timeZone,
}: {
  entityType: string;
  entityId: number;
  comments: RecordComment[];
  timeZone: string;
}) {
  const region = `comments-${entityType}-${entityId}`;
  return (
    <div className="card" id={`${region}-card`}>
      <div className="card-header"><h5 className="card-title">Notes</h5></div>
      <div className="card-body p-0">
        <div id={region}>
          <ul className="list-group list-group-flush">
            {comments.length === 0 ? (
              <li className="list-group-item text-muted">No notes yet.</li>
            ) : (
              comments.map((c) => (
                <li className="list-group-item" id={`comment-${c.id}`} key={c.id}>
                  <div className="d-flex justify-content-between align-items-start">
                    <div>
                      <div className="fw-medium fs-13">{c.author_name ?? "Someone"}</div>
                      <div className="fs-13"><Nl2br text={c.body} /></div>
                    </div>
                    <div className="text-nowrap ms-2 d-flex align-items-center gap-2">
                      <span className="fs-11 text-muted">{formatTs(c.created_at, timeZone, false)}</span>
                      {c.mine && (
                        <ActionForm path="/comments/delete.php" confirm="Delete this note?">
                          <input type="hidden" name="comment" value={c.id} />
                          <SubmitButton className="btn btn-link btn-sm p-0 text-danger lh-1" ariaLabel="Delete note">&times;</SubmitButton>
                        </ActionForm>
                      )}
                    </div>
                  </div>
                </li>
              ))
            )}
          </ul>
        </div>
        <div className="p-3 border-top">
          <ActionForm path="/comments/save.php" id={`${region}-form`} resetOnSuccess>
            <input type="hidden" name="entity_type" value={entityType} />
            <input type="hidden" name="entity" value={entityId} />
            <div className="d-flex gap-2">
              <textarea name="body" rows={1} className="form-control" placeholder="Add a note" maxLength={5000} required
                        id={`comment-field-${entityType}-${entityId}`}></textarea>
              <SubmitButton className="btn btn-primary">Post</SubmitButton>
            </div>
          </ActionForm>
        </div>
      </div>
    </div>
  );
}
