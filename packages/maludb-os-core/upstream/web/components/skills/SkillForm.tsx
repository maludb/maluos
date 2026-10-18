"use client";

import { useState } from "react";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";

type FileRow = { key: number; path: string; content: string };

/**
 * Screens `skills-library-form` (new / new version) — a skill is its name, its description (how an
 * agent knows when to use it), its instructions (SKILL.md after the frontmatter, written here) and
 * any text reference files. Saving never edits a version: a change becomes a new one. Posts
 * /ai/skills/save.php, which follows to the skill's page.
 */
export default function SkillForm({ initial, back = null }: {
  initial: { name: string; kind?: string; description: string; body: string; files: { path: string; content: string }[] } | null;
  back?: string | null;
}) {
  const isEdit = initial !== null;
  const record = isEdit ? `/ai/skills/${encodeURIComponent(initial.name)}` : "/ai/skills";   // Cancel and a save without a trail (R5)
  const { state, pending, onSubmit } = useRecordForm("/ai/skills/save.php", back);
  const [files, setFiles] = useState<FileRow[]>(
    (initial?.files ?? []).map((f, i) => ({ key: i, path: f.path, content: f.content })));
  const [next, setNext] = useState(files.length);
  const add = () => { setFiles([...files, { key: next, path: "", content: "" }]); setNext(next + 1); };
  const remove = (key: number) => setFiles(files.filter((f) => f.key !== key));

  return (
    <>
      <PageHeader title={isEdit ? `New version of ${initial.name}` : "New skill"} id="skills-library-form"
                  crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Skills", href: "/ai/skills" }, ...(isEdit ? [{ label: initial.name, href: record }, { label: "New version" }] : [{ label: "New" }])]}
                  back={{ href: record, label: isEdit ? "the skill" : "Skills" }}>
        <Link href={back ?? record} className="btn btn-light-brand" id="skills-library-form-cancel">Cancel</Link>
        <button type="submit" form="skills-library-form" className="btn btn-primary" id="skills-library-form-save" disabled={pending}>
          <i className="feather-check me-2"></i><span>{pending ? "Saving…" : isEdit ? "Save new version" : "Save"}</span>
        </button>
      </PageHeader>
      <div className="main-content" data-screen="skills-library-form">
        <ActionOutcome state={state} id="skills-library-form-errors" />
        <div className="card">
          <div className="card-body">
            <form id="skills-library-form" onSubmit={onSubmit}>
              <FieldRow label="Name" htmlFor="skill-form-field-name">
                {isEdit ? (
                  <>
                    <input type="hidden" name="name" value={initial.name} />
                    <input type="text" className="form-control" id="skill-form-field-name" value={initial.name} disabled />
                  </>
                ) : (
                  <input type="text" className="form-control" id="skill-form-field-name" name="name" required maxLength={64}
                         pattern="[a-z0-9][a-z0-9\-]{1,63}" placeholder="file-a-vendor-bill" />
                )}
                <div className="form-text">Lower-case letters, digits and hyphens. It is how the skill is assigned and read; it never changes.</div>
              </FieldRow>
              <FieldRow label="Kind" htmlFor="skill-form-field-kind">
                <select className="form-select" id="skill-form-field-kind" name="kind" defaultValue={initial?.kind ?? "skill"}>
                  <option value="skill">Skill — one job, done this business&rsquo;s way</option>
                  <option value="runbook">Runbook — an application&rsquo;s generic skill (close of day, month-end, onboarding)</option>
                </select>
                <div className="form-text">Written into the frontmatter as <code>kind: runbook</code>; a shipped runbook says it there too.</div>
              </FieldRow>
              <FieldRow label="Description" htmlFor="skill-form-field-description">
                <textarea className="form-control" id="skill-form-field-description" name="description" rows={3} maxLength={1024} required
                          defaultValue={initial?.description ?? ""}></textarea>
                <div className="form-text">What it is for and when to use it — an agent decides from this line whether the skill applies.</div>
              </FieldRow>
              <FieldRow label="Instructions" htmlFor="skill-form-field-body">
                <textarea className="form-control font-monospace fs-12" id="skill-form-field-body" name="body" rows={18} required
                          defaultValue={initial?.body ?? ""}></textarea>
                <div className="form-text">
                  Markdown. An agent on the Claude harness carries only the first 6,000 characters in its instructions — put what matters first;
                  it reads the rest, and the files below, with <code>skill_read</code> when granted.
                </div>
              </FieldRow>
              <FieldRow label="Reference files" htmlFor="skill-form-add-file">
                {files.length === 0 && <p className="text-muted fs-12 mb-2">None. Text files only (md, txt, json, yaml, csv) — up to 20.</p>}
                {files.map((f, i) => (
                  <div className="border rounded p-2 mb-2" key={f.key} id={`skill-form-file-${f.key}`}>
                    <div className="d-flex gap-2 mb-2">
                      <input type="text" className="form-control form-control-sm" name={`files[${i}][path]`} defaultValue={f.path}
                             placeholder="references/notes.md" aria-label="File path" required />
                      <button type="button" className="btn btn-sm btn-light-brand text-danger" onClick={() => remove(f.key)}>Remove</button>
                    </div>
                    <textarea className="form-control form-control-sm font-monospace fs-12" name={`files[${i}][content]`} rows={6}
                              defaultValue={f.content} aria-label="File text"></textarea>
                  </div>
                ))}
                <button type="button" className="btn btn-sm btn-light-brand" id="skill-form-add-file" onClick={add}>
                  <i className="feather-plus me-1"></i>Add a file
                </button>
              </FieldRow>
            </form>
          </div>
        </div>
      </div>
    </>
  );
}
