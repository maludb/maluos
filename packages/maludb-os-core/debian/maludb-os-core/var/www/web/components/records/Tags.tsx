import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import type { Tagging } from "@/lib/schemas/records";

/**
 * Tag strip for any record (app/views/shared/tags.php). Reused verbatim by every slice — a tag
 * on an invoice is the same row as a tag on a contact. Writes: /tags/add.php, /tags/remove.php.
 */
export default function Tags({
  entityType, entityId, taggings, canEdit,
}: {
  entityType: string;
  entityId: number;
  taggings: Tagging[];
  canEdit: boolean;
}) {
  const region = `tags-${entityType}-${entityId}`;
  return (
    <div id={region} className="d-flex flex-wrap align-items-center gap-1">
      {taggings.map((t) => (
        <span className="badge bg-soft-primary text-primary d-inline-flex align-items-center gap-1"
              id={`tag-${entityType}-${entityId}-${t.tag_id}`} key={t.tag_id}>
          {t.name}
          {canEdit && (
            <ActionForm path="/tags/remove.php" className="d-inline">
              <input type="hidden" name="entity_type" value={entityType} />
              <input type="hidden" name="entity" value={entityId} />
              <input type="hidden" name="tag" value={t.tag_id} />
              <SubmitButton className="btn btn-link btn-sm p-0 text-primary lh-1" ariaLabel="Remove tag">&times;</SubmitButton>
            </ActionForm>
          )}
        </span>
      ))}
      {canEdit && (
        <ActionForm path="/tags/add.php" className="d-inline-flex align-items-center gap-1" resetOnSuccess>
          <input type="hidden" name="entity_type" value={entityType} />
          <input type="hidden" name="entity" value={entityId} />
          <input type="text" name="tag" className="form-control form-control-sm" style={{ maxWidth: "9rem" }} placeholder="Add tag"
                 maxLength={40} required id={`tag-add-field-${entityType}-${entityId}`} />
          <SubmitButton className="btn btn-sm btn-light-brand">Add</SubmitButton>
        </ActionForm>
      )}
    </div>
  );
}
