import type { Metadata } from "next";
import ModuleStub from "@/components/kit/ModuleStub";
import PageHeader from "@/components/kit/PageHeader";
import { renderScreen } from "@/lib/screen";
import { moduleStub, STUB_PATHS } from "@/lib/schemas/modules";
import { getSession } from "@/lib/api";
import { activeNavKey } from "@/lib/nav";

export const metadata: Metadata = { title: "Not converted yet" };

/**
 * Stand-in for every screen the migration has not reached (docs/react-migration-plan.md, R4).
 * It says so plainly rather than 404ing: the module exists and still works in the legacy UI —
 * a "not found" here would be a lie. Each converted module's own routes take precedence over
 * this catch-all, so it shrinks to nothing by cut-over and is deleted with it.
 */
export default async function NotConvertedYet({ params }: { params: Promise<{ slug: string[] }> }) {
  const path = "/" + (await params).slug.join("/");

  // A module that is designed but not built is a real screen of the product: PHP describes it.
  if (path in STUB_PATHS) {
    return renderScreen(STUB_PATHS[path], moduleStub, (data) => <ModuleStub data={data} />);
  }
  const session = await getSession();
  const items = session.nav.flatMap((g) => g.items);
  const key = activeNavKey(path === "/dashboard" ? "/dashboard" : path, items);
  const label = items.find((i) => i.key === key)?.label ?? "This screen";

  return (
    <>
      <PageHeader title={label} crumbs={[{ label }]} id="not-converted" />
      <div className="main-content">
        <div className="row">
          <div className="col-12">
            <div className="card stretch stretch-full">
              <div className="card-body text-center py-5" id="not-converted-card">
                <div className="avatar-text avatar-xl rounded mx-auto mb-4"><i className="feather-tool"></i></div>
                <h5 className="fw-bold mb-2">{label} has not moved to the new front end yet</h5>
                <p className="text-muted mb-0">
                  It is unchanged and fully working in the current application. Screens move over
                  module by module; this one is still to come.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
