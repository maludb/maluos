"use client";

import { useQueryState } from "./useQueryState";

/** A card-header checkbox filter: ticked sets ?name=1, unticked removes it; returns to page 1. `switch` draws it as a toggle. */
export default function FilterCheckbox({
  id, name, checked, label, valueOn = "1", variant = "checkbox",
}: {
  id: string;
  name: string;
  checked: boolean;
  label: string;
  /** What the parameter is set to when ticked (e.g. status=retired); "1" by default. */
  valueOn?: string;
  variant?: "checkbox" | "switch";
}) {
  const { setParam } = useQueryState();
  return (
    <div className={`form-check ${variant === "switch" ? "form-switch mb-0" : ""} d-flex align-items-center gap-1`}>
      <input className="form-check-input" type="checkbox" name={name} value={valueOn} id={id} checked={checked}
             onChange={(e) => setParam(name, e.target.checked ? valueOn : "")} />
      <label className={`form-check-label ${variant === "switch" ? "fw-semibold" : "fs-12"}`} htmlFor={id}>{label}</label>
    </div>
  );
}
