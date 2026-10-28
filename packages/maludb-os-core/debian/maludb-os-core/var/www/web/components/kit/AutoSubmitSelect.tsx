"use client";

/** A select that submits its own form on change — the counterpart of `hx-trigger="change"` on a select inside a form. */
export default function AutoSubmitSelect({
  id, name, value, options, className = "form-select form-select-sm",
}: {
  id: string;
  name: string;
  value: string | number;
  options: { value: string | number; label: string }[];
  className?: string;
}) {
  return (
    <select name={name} id={id} className={className} defaultValue={value}
            onChange={(e) => e.currentTarget.form?.requestSubmit()}>
      {options.map((o) => <option value={o.value} key={o.value}>{o.label}</option>)}
    </select>
  );
}
