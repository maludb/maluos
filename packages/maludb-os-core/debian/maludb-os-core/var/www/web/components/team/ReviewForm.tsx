"use client";

import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";
import type { ReviewFormData } from "@/lib/schemas/agents";

/** Performance review form (screen `review-add`) — app/views/team/review-form.php. */
export default function ReviewForm({ data, back: carried = null }: { data: ReviewFormData; back?: string | null }) {
  const { member } = data;
  const { state, pending, onSubmit } = useRecordForm("/team/reviews/save.php", carried);
  // Where the member is: an agent's Performance tab, a person's page (click-around, R5) — unless the form was opened from elsewhere.
  const parent = member.kind === "agent" ? `/agents/${member.id}?tab=performance` : `/team/${member.id}`;
  const back = carried ?? parent;

  return (
    <>
      <PageHeader title={`Write a review · ${member.name}`} id="review-form"
                  crumbs={[member.kind === "agent" ? { label: "HR", href: "/agents" } : { label: "People", href: "/team" }, { label: member.name, href: parent }, { label: "Review" }]}
                  back={{ href: parent, label: member.kind === "agent" ? "the agent" : "the person" }}>
        <Link href={back} id="review-form-cancel" className="btn btn-light-brand">Cancel</Link>
        <button type="submit" form="review-form" id="review-form-save" className="btn btn-primary" disabled={pending}>
          <i className="feather-check me-2"></i><span>{pending ? "Saving…" : "Save review"}</span>
        </button>
      </PageHeader>

      <div className="main-content" data-screen="review-add">
        <ActionOutcome state={state} id="review-form-errors" />
        <div className="row">
          <div className="col-lg-7">
            <div className="card stretch stretch-full">
              <div className="card-body">
                <form id="review-form" onSubmit={onSubmit}>
                  <input type="hidden" name="member" value={member.id} />
                  <FieldRow label="Period start" htmlFor="review-form-field-period_start">
                    <input type="date" className="form-control" id="review-form-field-period_start" name="period_start" required />
                  </FieldRow>
                  <FieldRow label="Period end" htmlFor="review-form-field-period_end">
                    <input type="date" className="form-control" id="review-form-field-period_end" name="period_end" required />
                  </FieldRow>
                  <FieldRow label="Rating" htmlFor="review-form-field-rating">
                    <select className="form-select" id="review-form-field-rating" name="rating" defaultValue="">
                      <option value="">— none —</option>
                      {[1, 2, 3, 4, 5].map((r) => <option value={r} key={r}>{r} / 5</option>)}
                    </select>
                  </FieldRow>
                  <FieldRow label="Summary" htmlFor="review-form-field-summary">
                    <textarea className="form-control" id="review-form-field-summary" name="summary" rows={5}></textarea>
                    <div className="form-text">Metrics from the period (activity, and escalations for an agent) are filled automatically.</div>
                  </FieldRow>
                </form>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
