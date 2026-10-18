"use client";

import { useState } from "react";
import { useQueryState } from "@/components/kit/useQueryState";

/** The prompt library's "Filter by role key" box with its Filter button — state is the URL (?role=). */
export default function PromptRoleFilter({ role }: { role: string }) {
  const { setParam } = useQueryState();
  const [text, setText] = useState(role);
  return (
    <form className="row g-2 mb-3" onSubmit={(e) => { e.preventDefault(); setParam("role", text.trim()); }}>
      <div className="col-auto">
        <input type="text" className="form-control form-control-sm" name="role" id="system-prompts-filter-role"
               value={text} onChange={(e) => setText(e.target.value)} placeholder="Filter by role key" />
      </div>
      <div className="col-auto">
        <button type="submit" className="btn btn-sm btn-light-brand" id="system-prompts-filter-btn">Filter</button>
      </div>
    </form>
  );
}
