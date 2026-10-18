import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";

/**
 * The super-admin's Delete, on the location page and on its form. When something still points
 * at the location the button is shown disabled and says what — a refusal must name what is in
 * the way rather than saying "cannot".
 */
export default function DeleteLocation({ locationId, blockers, buttonId }: { locationId: number; blockers: string[]; buttonId: string }) {
  if (blockers.length > 0) {
    return (
      <button type="button" className="btn btn-light-brand text-muted" id={buttonId} disabled
              title={`Still has ${blockers.join(", ")} — retire it instead, or clear those first`}>
        <i className="feather-trash-2 me-2"></i><span>Delete</span>
      </button>
    );
  }
  return (
    <ActionForm path="/locations/delete.php" follow
                confirm="Delete this location for good? Retiring keeps the record; deleting removes it. Nothing points at it, so nothing else is lost — but this cannot be undone.">
      <input type="hidden" name="location" value={locationId} />
      <SubmitButton className="btn btn-danger" id={buttonId}>
        <i className="feather-trash-2 me-2"></i><span>Delete</span>
      </SubmitButton>
    </ActionForm>
  );
}
