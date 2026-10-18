"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryState } from "./useQueryState";

/** Page-header search box: updates ?q= 400 ms after typing stops (the HTMX delay it replaces). */
export default function SearchInput({ id, value, placeholder }: { id: string; value: string; placeholder: string }) {
  const { setParam } = useQueryState();
  const [text, setText] = useState(value);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  function onChange(next: string) {
    setText(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setParam("q", next.trim(), "replace"), 400);
  }

  return (
    <div className="input-group">
      <span className="input-group-text"><i className="feather-search"></i></span>
      <input type="search" id={id} name="q" className="form-control" placeholder={placeholder}
             value={text} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}
