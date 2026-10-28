import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";

/**
 * The super-admin's Delete, on the department page and on its form — never shown for a standing
 * department. While anything still works in the department (people, agents, a manager, departments
 * reporting to it, applications it owns, open invitations, ledger lines, eval sets) the button is
 * shown disabled and its title names what — a refusal must name what is in the way rather than
 * saying "cannot".
 */
export default function DeleteDepartment({ departmentId, blockers, buttonId }: { departmentId: number; blockers: string[]; buttonId: string }) {
  if (blockers.length > 0) {
    return (
      <button type="button" className="btn btn-light-brand text-muted" id={buttonId} disabled
              title={`Still has ${blockers.join(", ")} — move or remove those first`}>
        <i className="feather-trash-2 me-2"></i><span>Delete</span>
      </button>
    );
  }
  return (
    <ActionForm path="/team/departments/delete.php" follow
                confirm="Delete this department for good? Nobody works in it, so nothing else is lost — its past memberships, policies, skill assignments and access grants go with it. This cannot be undone.">
      <input type="hidden" name="department" value={departmentId} />
      <SubmitButton className="btn btn-danger" id={buttonId}>
        <i className="feather-trash-2 me-2"></i><span>Delete</span>
      </SubmitButton>
    </ActionForm>
  );
}
