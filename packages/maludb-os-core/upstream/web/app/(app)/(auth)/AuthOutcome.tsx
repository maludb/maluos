import type { AuthFlowState } from "./login/actions";

/** The error / error-list alerts the three auth templates share; `prefix` keeps each screen's ids. */
export default function AuthOutcome({ state, prefix }: { state: AuthFlowState; prefix: string }) {
  return (
    <>
      {state.error !== "" && <div className="alert alert-danger py-2" id={`${prefix}-error`} role="alert">{state.error}</div>}
      {state.errors.length > 0 && (
        <div className="alert alert-danger py-2" id={`${prefix}-errors`} role="alert">
          <ul className="mb-0 ps-3">{state.errors.map((e) => <li key={e}>{e}</li>)}</ul>
        </div>
      )}
    </>
  );
}
