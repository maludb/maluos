"use client";

import { useQueryState } from "./useQueryState";

/** A date filter: picking a day sets its query parameter — the date counterpart of FilterSelect. */
export default function FilterDate({ id, name, value }: { id: string; name: string; value: string }) {
  const { setParam } = useQueryState();
  return (
    <input type="date" id={id} name={name} className="form-control form-control-sm w-auto" value={value}
           onChange={(e) => setParam(name, e.target.value)} />
  );
}
