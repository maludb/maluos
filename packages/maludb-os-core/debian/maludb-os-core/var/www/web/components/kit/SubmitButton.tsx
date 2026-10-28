"use client";

import { useFormStatus } from "react-dom";

/** A submit button that disables itself while its own form is in flight. */
export default function SubmitButton({
  children, className, id, ariaLabel, disabled = false,
}: {
  children: React.ReactNode;
  className: string;
  id?: string;
  ariaLabel?: string;
  /** Nothing to do here (the first row cannot move up). */
  disabled?: boolean;
}) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className={className} id={id} aria-label={ariaLabel} disabled={pending || disabled}>
      {children}
    </button>
  );
}
