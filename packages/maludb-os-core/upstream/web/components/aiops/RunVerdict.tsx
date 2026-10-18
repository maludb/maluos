import ActionForm from "@/components/kit/ActionForm";
import Who from "@/components/kit/Who";
import { formatTs } from "@/lib/format";

export type Verdicts = {
  mine: { verdict: string; note: string | null; updated_at: string | null } | null;
  all: { verdict: string; note: string | null; member_name: string | null; member_id?: number | null; updated_at: string | null }[];
};

/**
 * "Was this any good?" — the cheapest label an evaluation can have, and the one thing the
 * platform recorded nowhere (docs/build-specs/eval-evidence.md, db/124). Two buttons and a note,
 * on an agent run or one assistant answer.
 *
 * It cannot be backfilled: nobody will remember in March whether Tuesday's brief was good, so the
 * card sits on the run itself where the person who just read it can say so in one click.
 */
export default function RunVerdict({
  runId, callId, verdicts, can, timeZone, here = null }: {
  runId?: number;
  callId?: number;
  verdicts: Verdicts;
  can: boolean;
  timeZone: string;
  /** The page this card sits on, so a verdict's author links back to it. */
  here?: string | null;
}) {
  const mine = verdicts.mine;
  const others = verdicts.all.filter((v) => !mine || v.updated_at !== mine.updated_at || v.note !== mine.note);
  const subject = runId !== undefined ? { name: "run", value: runId } : { name: "call", value: callId ?? 0 };

  return (
    <div className="card" id="run-verdict-card">
      <div className="card-header">
        <h5 className="card-title">Was this any good?</h5>
      </div>
      <div className="card-body">
        {!can && !mine && verdicts.all.length === 0 && (
          <p className="text-muted fs-12 mb-0">Nobody has said yet.</p>
        )}
        {can && (
          <ActionForm path="/ai/verdict.php" id="run-verdict-form" resetOnSuccess={false}>
            <input type="hidden" name={subject.name} value={subject.value} />
            <div className="d-flex flex-wrap gap-2 mb-3">
              <button type="submit" name="verdict" value="good" id="run-verdict-good"
                      className={`btn ${mine?.verdict === "good" ? "btn-success" : "btn-light-success"}`}>
                <i className="feather-thumbs-up me-2"></i><span>Good</span>
              </button>
              <button type="submit" name="verdict" value="bad" id="run-verdict-bad"
                      className={`btn ${mine?.verdict === "bad" ? "btn-danger" : "btn-light-danger"}`}>
                <i className="feather-thumbs-down me-2"></i><span>Not good</span>
              </button>
            </div>
            <label htmlFor="run-verdict-note" className="form-label fs-12 text-muted">
              What was good or wrong about it? (optional, and worth more later than the click)
            </label>
            <textarea className="form-control" id="run-verdict-note" name="note" rows={2}
                      defaultValue={mine?.note ?? ""} maxLength={2000} />
          </ActionForm>
        )}
        {mine && (
          <p className="text-muted fs-12 mt-3 mb-0" id="run-verdict-mine">
            You marked this <strong>{mine.verdict === "good" ? "good" : "not good"}</strong>
            {mine.updated_at ? ` on ${formatTs(mine.updated_at, timeZone)}` : ""}. Saying it again changes it.
          </p>
        )}
        {others.length > 0 && (
          <ul className="list-unstyled mt-3 mb-0" id="run-verdict-others">
            {others.map((v, i) => (
              <li key={i} className="fs-12 text-muted border-top pt-2 mt-2">
                <span className={v.verdict === "good" ? "text-success" : "text-danger"}>
                  {v.verdict === "good" ? "Good" : "Not good"}
                </span>
                {" — "}{v.member_id != null ? <Who who={{ id: v.member_id, name: v.member_name ?? "someone" }} here={here} className="text-muted" /> : v.member_name ?? "someone"}
                {v.updated_at ? `, ${formatTs(v.updated_at, timeZone)}` : ""}
                {v.note ? <div className="mt-1">{v.note}</div> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
