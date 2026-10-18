import ActionForm from "@/components/kit/ActionForm";

/**
 * The empty sibling forms behind an inline-row settings table. HTMX posted a row with
 * hx-include="closest tr" (a form cannot live in a <tr>); here the row's inputs and buttons
 * point at these with `form=`. One save form and, where the row can be archived, one archive
 * form per row — plus the "new" row's save form, which clears itself after a success.
 */
export function rowFormId(table: string, action: "save" | "archive", key: number | "new"): string {
  return `${table}-form-${action}-${key}`;
}

export default function RowForms({
  table, idField, savePath, archivePath, rows,
}: {
  table: string;
  /** The name PHP reads the row's id from, e.g. "catalog_item". */
  idField: string;
  savePath: string;
  archivePath?: string;
  rows: { id: number; archived: boolean }[];
}) {
  return (
    <div className="px-3">
      {rows.map((r) => (
        <div key={r.id}>
          <ActionForm path={savePath} id={rowFormId(table, "save", r.id)}>
            <input type="hidden" name={idField} value={r.id} />
          </ActionForm>
          {archivePath && (
            <ActionForm path={archivePath} id={rowFormId(table, "archive", r.id)}>
              <input type="hidden" name={idField} value={r.id} />
              <input type="hidden" name="archived" value={r.archived ? "0" : "1"} />
            </ActionForm>
          )}
        </div>
      ))}
      <ActionForm path={savePath} id={rowFormId(table, "save", "new")} resetOnSuccess><></></ActionForm>
    </div>
  );
}
