import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";

/**
 * Set one core-memory entry (action `core_memory_set`). Setting a key that exists supersedes it —
 * MaluDB keeps what it said before. Shown only when PHP said this person may (can.set).
 */
export default function CoreSetForm({ memberId }: { memberId: number }) {
  return (
    <ActionForm path="/memory/core-set.php" resetOnSuccess>
      <input type="hidden" name="member" value={memberId} />
      <div className="mb-3">
        <label className="form-label" htmlFor="memory-core-field-key">Key</label>
        <input type="text" className="form-control" name="key" id="memory-core-field-key" required maxLength={80}
               pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,79}" placeholder="vendor_naming" autoComplete="off" />
        <div className="form-text">A short name: letters, digits, dot, dash, underscore. An existing key is superseded, never erased.</div>
      </div>
      <div className="mb-3">
        <label className="form-label" htmlFor="memory-core-field-value">What holds, all the time</label>
        <textarea className="form-control" name="value" id="memory-core-field-value" rows={3} required maxLength={2000}></textarea>
      </div>
      <div className="mb-3">
        <label className="form-label" htmlFor="memory-core-field-note">Note <span className="text-muted">(optional)</span></label>
        <input type="text" className="form-control" name="note" id="memory-core-field-note" maxLength={300} placeholder="Why, or who decided" />
      </div>
      <SubmitButton className="btn btn-primary" id="memory-core-set-btn"><i className="feather-save me-2"></i>Set</SubmitButton>
    </ActionForm>
  );
}
