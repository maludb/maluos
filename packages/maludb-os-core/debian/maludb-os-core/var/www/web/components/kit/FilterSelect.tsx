"use client";

import { useQueryState } from "./useQueryState";

/** A card-header filter: picking an option sets its query parameter and returns to page 1. */
export default function FilterSelect({
  id, name, value, options,
}: {
  id: string;
  name: string;
  value: string;
  options: { value: string; label: string }[];
}) {
  const { setParam } = useQueryState();
  return (
    <select name={name} id={id} className="form-select form-select-sm w-auto" value={value}
            onChange={(e) => setParam(name, e.target.value)}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}
