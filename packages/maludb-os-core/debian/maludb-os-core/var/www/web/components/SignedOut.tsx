import { GitBranch, LogIn } from "lucide-react";

// Rendered when there is no session cookie, or the platform rejected it (401). Never a
// crash, and never an empty graph presented as though the organisation had no one in it.
export default function SignedOut({ loginUrl }: { loginUrl: string | null }) {
  return (
    <main className="signedout-stage">
      <div className="signedout-card">
        <div className="signedout-brand">
          <GitBranch size={18} strokeWidth={2.25} />
          <span>
            Malu<b>Db</b>
          </span>
        </div>
        <p className="signedout-eyebrow">WORKSPACE / ORGANIZATION</p>
        <h1>
          Agent View
          <br />
          <span>Every connection.</span>
        </h1>
        <p className="signedout-copy">
          You need to sign in to Business OS to see your organisation&rsquo;s agent view —
          the people, departments and AI agents around you.
        </p>
        {loginUrl ? (
          <a className="signedout-cta" href={loginUrl}>
            <LogIn size={16} strokeWidth={2.25} />
            Sign in to continue
          </a>
        ) : (
          // No LOGIN_URL configured. Saying so beats offering a link that goes nowhere useful.
          <p className="signedout-copy signedout-misconfig">
            Sign-in is not configured for this deployment: set <code>LOGIN_URL</code> in
            <code> agentview/.env.local</code> to the Business OS login page.
          </p>
        )}
        <p className="signedout-hint">
          Just exploring the interface?{" "}
          <a href="/?demo=1">View the sample workspace</a> instead — no sign-in required.
        </p>
      </div>
    </main>
  );
}
