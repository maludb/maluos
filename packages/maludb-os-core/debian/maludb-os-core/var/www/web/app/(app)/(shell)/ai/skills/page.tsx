import type { Metadata } from "next";
import AiOpsNav from "@/components/aiops/AiOpsNav";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import KindBadge from "@/components/skills/KindBadge";
import RecordCard from "@/components/kit/RecordCard";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { skillLibrary } from "@/lib/schemas/skillLibrary";

export const metadata: Metadata = { title: "Skills" };

/**
 * Screen `skills-library` — AI Ops → Skills: every skill in the library (MaluDB) as a card — what it is
 * for, the version agents get (the newest enabled), how many versions and assignments. Who holds which
 * skill, and what agents have proposed, stay on /skills. Data: GET /ai/skills/ (super-admin).
 */
export default async function SkillLibraryPage() {
  const here = await herePath();
  return renderScreen("/ai/skills/", skillLibrary, (data) => (
    <>
      <PageHeader title="Skills" id="skills-library" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Skills" }]}>
        <Link href="/skills" className="btn btn-light-brand" id="skills-library-assignments-btn">
          <i className="feather-users me-2"></i><span>Who has which</span>
        </Link>
        {data.can.edit && (
          <Link href={withBack("/ai/skills/new", here)} className="btn btn-primary" id="skills-library-new-btn">
            <i className="feather-plus me-2"></i><span>New skill</span>
          </Link>
        )}
      </PageHeader>
      <div className="main-content" data-screen="skills-library">
        <AiOpsNav active="skills" />
        <p className="text-muted fs-13">
          Instructions agents work from, in the business&rsquo;s own words. Saving a change makes a new version and keeps the old ones;
          an agent gets the newest enabled version of each skill it holds. Agents granted <code>skill_library</code> and{" "}
          <code>skill_read</code> can read any enabled skill in full, reference files included.
        </p>
        <div className="row g-3" id="skills-library-cards">
          {data.skills.length === 0 && <p className="text-muted">No skills yet.</p>}
          {[...data.skills].sort((a, b) => (a.kind === "runbook" ? 0 : 1) - (b.kind === "runbook" ? 0 : 1) || a.name.localeCompare(b.name)).map((s) => (
            <RecordCard key={s.name} id={`skill-card-${s.name}`} href={`/ai/skills/${encodeURIComponent(s.name)}`} title={s.name}
                        icon="feather-book-open" muted={!s.enabled}
                        badges={<>{s.kind === "runbook" && <KindBadge kind={s.kind} />}{!s.enabled && <span className="badge bg-soft-secondary text-secondary">disabled</span>}</>}
                        description={<span className="fs-12">{s.description}</span>}
                        facts={[["Version", <code key="v">{s.current.version}</code>],
                                ["Versions", String(s.version_count)],
                                ["Held by", s.assignment_count === 0 ? "nobody yet" : `${s.assignment_count} assignment${s.assignment_count === 1 ? "" : "s"}`]]} />
          ))}
        </div>
      </div>
    </>
  ));
}
