import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { getSession } from "@/lib/api";
import { appUrl, type Face } from "@/lib/face";
import { logoutAction } from "@/app/(app)/(auth)/login/actions";
import Shell from "@/components/shell/Shell";
import PersonShell from "@/components/shell/PersonShell";

/**
 * Every day-to-day screen renders inside a shell. The middleware has already turned away a
 * visitor with no cookie and chosen the face (x-face — lib/face.ts); this turns away one whose
 * cookie PHP no longer honours, sends a non-administrator who reached the operating system to
 * the person face, and picks the chrome: the nxl shell with the kernel's navigation on
 * os.<domain>, a bare top bar on app.<domain>.
 */
export default async function ShellLayout({ children }: { children: React.ReactNode }) {
  const incoming = await headers();
  const face: Face = incoming.get("x-face") === "app" ? "app" : "os";
  const session = await getSession();
  if (!session.authenticated || session.member === null) {
    const path = incoming.get("x-pathname") ?? (face === "app" ? "/launcher" : "/dashboard");
    redirect(`/login?next=${encodeURIComponent(path)}`);
  }

  // The operating system is for super-admins (the owner's decision, 2026-09-22). PHP refuses everyone
  // else on every read and write under the os name; this is the courtesy that sends them where they belong.
  if (face === "os" && !session.member.is_super_admin) {
    const to = appUrl();
    if (to) redirect(`${to}/launcher`);
  }

  if (face === "app") {
    return (
      <PersonShell member={session.member} businessName={session.business.name} logoutAction={logoutAction}>
        {children}
      </PersonShell>
    );
  }
  return (
    <Shell member={session.member} nav={session.nav} businessName={session.business.name}
           logoUrl={session.business.logo_url ?? null} logoutAction={logoutAction}>
      {children}
    </Shell>
  );
}
