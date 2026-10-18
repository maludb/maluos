"use client";

import { useState, useTransition } from "react";
import type { JevCheck } from "@/lib/schemas/aiops";
import { draftJevChecks } from "./evalActions";

/**
 * The JEV checks of an eval case (db/144): one card per check — a typed question JEV answers about the
 * agent's work, and the rule that makes it pass. Serialised into the form's `checks` field. A check JEV
 * is unsure of sends the case to a person; the injection guard is added by the runner, never here.
 */
type Draft = {
  id: string; type: "noul" | "choice" | "score"; instructions: string;
  criteriaText: string;          // noul: "true: …\nfalse: …"; choice: "option: description" lines; score: one level per line, lowest first
  passAt: string; accept: string; minLevel: string; minConfidence: string; required: boolean; weight: string;
};

const blank = (n: number): Draft => ({ id: `check_${n}`, type: "noul", instructions: "", criteriaText: "", passAt: "0.8",
  accept: "", minLevel: "1", minConfidence: "0.6", required: true, weight: "1" });

function toDraft(c: JevCheck): Draft {
  let criteriaText = "";
  if (c.type === "score" && Array.isArray(c.criteria)) criteriaText = c.criteria.join("\n");
  else if (c.criteria && typeof c.criteria === "object" && !Array.isArray(c.criteria)) {
    criteriaText = Object.entries(c.criteria).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v ?? "")}`).join("\n");
  }
  return { id: c.id, type: c.type, instructions: c.instructions, criteriaText, passAt: String(c.pass_at ?? 0.8),
    accept: (c.accept ?? []).join(", "), minLevel: String(c.min_level ?? 1), minConfidence: String(c.min_confidence ?? 0.6),
    required: c.required ?? true, weight: String(c.weight ?? 1) };
}

function pairs(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const at = line.indexOf(":");
    if (at > 0) out[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  return out;
}

function toCheck(d: Draft): Record<string, unknown> {
  const base = { id: d.id.trim(), type: d.type, instructions: d.instructions.trim(), required: d.required, weight: Number(d.weight) || 1 };
  if (d.type === "noul") {
    const crit = pairs(d.criteriaText);
    return { ...base, ...(crit.true || crit.false ? { criteria: { true: crit.true ?? "", false: crit.false ?? "" } } : {}),
      pass_at: Number(d.passAt), uncertain: [0.3, 0.7] };
  }
  if (d.type === "choice") {
    return { ...base, criteria: pairs(d.criteriaText), accept: d.accept.split(",").map((a) => a.trim()).filter(Boolean),
      min_confidence: Number(d.minConfidence) };
  }
  return { ...base, criteria: d.criteriaText.split("\n").map((l) => l.trim()).filter(Boolean),
    min_level: parseInt(d.minLevel, 10), min_confidence: Number(d.minConfidence) };
}

export default function JevChecksEditor({ initial, caseId, rubricFieldId, fieldName = "checks", allowEmpty = false }: {
  initial: JevCheck[] | null; caseId: number | null; rubricFieldId: string | null; fieldName?: string; allowEmpty?: boolean;
}) {
  const [checks, setChecks] = useState<Draft[]>(() => (initial ?? []).map(toDraft));
  const [note, setNote] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const set = (i: number, patch: Partial<Draft>) => setChecks((cs) => cs.map((c, j) => (j === i ? { ...c, ...patch } : c)));

  const draft = () => start(async () => {
    const rubric = rubricFieldId ? (document.getElementById(rubricFieldId) as HTMLTextAreaElement | null)?.value ?? "" : "";
    const answer = await draftJevChecks(rubric, caseId);
    if (answer.error) { setNote(answer.error); return; }
    setChecks((answer.checks ?? []).map(toDraft));
    setNote(`Drafted ${answer.checks?.length ?? 0} checks from the rubric — review them before saving.`);
  });

  return (
    <div id="eval-case-jev-checks">
      <input type="hidden" name={fieldName} value={allowEmpty && checks.length === 0 ? "" : JSON.stringify(checks.map(toCheck))} />
      <div className="d-flex flex-wrap gap-2 mb-2">
        <button type="button" className="btn btn-sm btn-light-brand" id="eval-case-jev-add" onClick={() => setChecks((cs) => [...cs, blank(cs.length + 1)])}>
          <i className="feather-plus me-1"></i>Add a check
        </button>
        {rubricFieldId && (
          <button type="button" className="btn btn-sm btn-light-brand" id="eval-case-jev-draft" onClick={draft} disabled={pending}>
            <i className="feather-edit-3 me-1"></i>{pending ? "Drafting…" : "Draft checks from the rubric"}
          </button>
        )}
      </div>
      {note && <div className="fs-12 text-muted mb-2" id="eval-case-jev-note">{note}</div>}
      {checks.length === 0 && <div className="fs-12 text-muted mb-2">No checks yet. One check asks JEV one thing — split a rubric into one property per check.</div>}
      {checks.map((c, i) => (
        <div className="card mb-2" id={`eval-case-jev-check-${i}`} key={i}>
          <div className="card-body p-3">
            <div className="row g-2">
              <div className="col-sm-4">
                <label className="form-label fs-12" htmlFor={`jev-id-${i}`}>Id</label>
                <input id={`jev-id-${i}`} className="form-control form-control-sm font-monospace" value={c.id} onChange={(e) => set(i, { id: e.target.value })} />
              </div>
              <div className="col-sm-4">
                <label className="form-label fs-12" htmlFor={`jev-type-${i}`}>Kind of question</label>
                <select id={`jev-type-${i}`} className="form-select form-select-sm" value={c.type} onChange={(e) => set(i, { type: e.target.value as Draft["type"] })}>
                  <option value="noul">Yes or no (how likely true)</option>
                  <option value="choice">Pick one option</option>
                  <option value="score">Place on levels</option>
                </select>
              </div>
              <div className="col-sm-4 d-flex align-items-end gap-2">
                <div className="form-check mb-1">
                  <input className="form-check-input" type="checkbox" id={`jev-req-${i}`} checked={c.required} onChange={(e) => set(i, { required: e.target.checked })} />
                  <label className="form-check-label fs-12" htmlFor={`jev-req-${i}`}>Required</label>
                </div>
                <button type="button" className="btn btn-sm btn-light-brand text-danger ms-auto" id={`jev-remove-${i}`}
                        onClick={() => setChecks((cs) => cs.filter((_, j) => j !== i))}>Remove</button>
              </div>
              <div className="col-12">
                <label className="form-label fs-12" htmlFor={`jev-ins-${i}`}>What JEV is asked</label>
                <textarea id={`jev-ins-${i}`} className="form-control form-control-sm" rows={2} value={c.instructions}
                          placeholder={c.type === "noul" ? "The agent's final answer names the leave policy that applies." : "How does the agent's answer respond to the question?"}
                          onChange={(e) => set(i, { instructions: e.target.value })} />
              </div>
              <div className="col-md-7">
                <label className="form-label fs-12" htmlFor={`jev-crit-${i}`}>
                  {c.type === "noul" ? "What true and false mean (optional)" : c.type === "choice" ? "Options — one per line, option: description" : "Levels — one per line, lowest first, each a situation"}
                </label>
                <textarea id={`jev-crit-${i}`} className="form-control form-control-sm" rows={3} value={c.criteriaText}
                          placeholder={c.type === "noul" ? "true: a named, real policy\nfalse: no policy, or an invented one" : c.type === "choice" ? "supported: every claim is backed by a tool result\nunsupported: some claim is not backed" : "misses the key fact\nhas the fact but not its source\nhas the fact and names its source"}
                          onChange={(e) => set(i, { criteriaText: e.target.value })} />
              </div>
              <div className="col-md-5">
                <label className="form-label fs-12">Passes when</label>
                {c.type === "noul" && (
                  <div className="input-group input-group-sm"><span className="input-group-text">likely true ≥</span>
                    <input className="form-control" value={c.passAt} onChange={(e) => set(i, { passAt: e.target.value })} aria-label="pass at" /></div>
                )}
                {c.type === "choice" && (
                  <input className="form-control form-control-sm" value={c.accept} placeholder="options that pass, comma-separated"
                         onChange={(e) => set(i, { accept: e.target.value })} aria-label="accepted options" />
                )}
                {c.type === "score" && (
                  <div className="input-group input-group-sm"><span className="input-group-text">level ≥</span>
                    <input className="form-control" value={c.minLevel} onChange={(e) => set(i, { minLevel: e.target.value })} aria-label="minimum level" /></div>
                )}
                <div className="form-text">
                  {c.type === "noul" ? "Between 0.3 and the pass mark JEV is unsure — a person decides." : `Below ${c.minConfidence} confidence JEV is unsure — a person decides.`}
                </div>
              </div>
            </div>
          </div>
        </div>
      ))}
      <div className="form-text">
        JEV answers each check about the agent&apos;s work — no reasons, just calibrated decisions. Every case also gets a guard that sends it to a
        person if the transcript tries to talk to the grader.
      </div>
    </div>
  );
}
