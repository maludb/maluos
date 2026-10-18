"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { GitBranch, LogIn, Search, X, ZoomIn, ZoomOut, RotateCcw, Play, Pause } from "lucide-react";
import type { FocusContext, OrgGraph, OrgNode, ViewMode } from "@/lib/types";
import { computeLayout } from "@/lib/layout";
import { nodeById } from "@/lib/detail";
import NetworkStage from "./NetworkStage";
import ProfilePanel from "./ProfilePanel";

const ZOOM_MIN = 60;
const ZOOM_MAX = 140;
const ZOOM_STEP = 10;

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduced(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  return reduced;
}

const FOCUS_KIND_LABEL: Record<FocusContext["kind"], string> = {
  department: "department", agent: "agent", project: "project", location: "location", organization: "company",
};

/**
 * `focus` is set by /view/<kind>/<id> only: the same picture, centred on a record instead of the
 * person looking (lib/focus-graph.ts adapts that payload to this component's shape). Without it
 * this is the home view, exactly as before.
 *
 * `loginUrl` is set only on the landing page: the sample workspace shown to a visitor who is not
 * signed in, where the way forward is to log in.
 */
export default function AgentView({ graph, mode, focus, loginUrl }: {
  graph: OrgGraph; mode: ViewMode; focus?: FocusContext; loginUrl?: string;
}) {
  const kindLabel = focus ? FOCUS_KIND_LABEL[focus.kind] : null;
  const layout = useMemo(() => computeLayout(graph, mode, { weighted: focus !== undefined }), [graph, mode, focus]);
  const memberPrimaryDept = useMemo(() => new Map(layout.members.map((m) => [m.memberId, m.primaryDeptId])), [layout]);

  const [search, setSearch] = useState("");
  const [activeTeam, setActiveTeam] = useState<number | null>(null);
  const [zoom, setZoom] = useState(100);
  const [motionOn, setMotionOn] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const reducedMotion = useReducedMotion();
  const lastFocusRef = useRef<HTMLElement | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const selectedNode: OrgNode | null = selectedId ? nodeById(graph, selectedId) ?? null : null;
  const selectedColor = selectedNode
    ? selectedNode.type === "department"
      ? layout.departments.find((d) => d.deptId === selectedNode.department_id)?.color
      : layout.members.find((m) => m.memberId === selectedNode.member_id)?.color
    : undefined;

  function select(id: string, opener?: HTMLElement) {
    lastFocusRef.current = opener ?? (document.activeElement as HTMLElement) ?? null;
    setSelectedId(id);
  }
  function closeProfile() {
    setSelectedId(null);
    lastFocusRef.current?.focus?.();
  }
  function navigate(id: string) {
    setSelectedId(id);
  }

  // Center the horizontally-scrolling mobile stage on mount and on resize.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const center = () => {
      el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2;
    };
    center();
    const ro = new ResizeObserver(center);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const matched = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (q === "" && activeTeam === null) return null;
    const set = new Set<string>();
    for (const node of graph.nodes) {
      if (node.is_centre) continue;
      const deptId = node.type === "department" ? node.department_id! : memberPrimaryDept.get(node.member_id!) ?? -1;
      const teamNode = graph.nodes.find((n) => n.type === "department" && n.department_id === deptId);
      const teamOk = activeTeam === null || deptId === activeTeam;
      const haystack = `${node.name} ${node.title ?? ""} ${teamNode?.name ?? ""}`.toLowerCase();
      const searchOk = q === "" || haystack.includes(q);
      if (teamOk && searchOk) set.add(node.id);
    }
    return set;
  }, [search, activeTeam, graph, memberPrimaryDept]);

  const searchResults = useMemo(() => {
    if (search.trim() === "") return null;
    return graph.nodes.filter((n) => !n.is_centre && matched?.has(n.id));
  }, [search, matched, graph]);

  return (
    <main className="agentview-root" data-focus={focus ? focus.kind : undefined}>
      <header className="av-header">
        <div className="av-brand">
          <GitBranch size={18} strokeWidth={2.25} />
          <span className="av-wordmark">
            Malu<b>Db</b>
          </span>
          <span className="av-tagline">AI AGENT VIEW</span>
        </div>
        <div className="av-header-right">
          <span className={`mode-badge mode-${mode}`}>{mode === "demo" ? "SAMPLE WORKSPACE" : "LIVE WORKSPACE"}</span>
          <button
            type="button"
            className="motion-toggle"
            onClick={() => setMotionOn((v) => !v)}
            aria-pressed={motionOn}
            title={motionOn ? "Pause motion" : "Resume motion"}
          >
            {motionOn ? <Pause size={14} strokeWidth={2.25} /> : <Play size={14} strokeWidth={2.25} />}
            {motionOn ? "Pause" : "Motion"}
          </button>
          {/* The plan's rule: a plain dashboard is always one click away. The sample workspace has
              no signed-in person, so there is nowhere to go from it. */}
          {focus ? (
            <>
              <a className="motion-toggle" href="/" id="agentview-organisation-link">Organisation</a>
              <a className="human-view-btn" href={focus.href ?? "/dashboard"} id="agentview-record-link">Goto Human View</a>
            </>
          ) : mode === "live" ? (
            <a className="human-view-btn" href="/dashboard" id="agentview-dashboard-link">Goto Human View</a>
          ) : loginUrl ? (
            <a className="human-view-btn av-login-btn" href={loginUrl} id="landing-login-link">
              <LogIn size={14} strokeWidth={2.25} />
              Log in
            </a>
          ) : (
            <button type="button" className="human-view-btn" disabled title="Sign in to open the workspace">
              Goto Human View
            </button>
          )}
        </div>
      </header>

      <div className="av-body">
        <div className="av-left">
          <p className="av-eyebrow">{focus ? `WORKSPACE / ${kindLabel!.toUpperCase()}` : "WORKSPACE / ORGANIZATION"}</p>
          {focus ? (
            <h1 className="av-heading av-heading-focus" id="agentview-focus-name">
              {focus.name}
              {focus.title ? (
                <>
                  <br />
                  <span>{focus.title}</span>
                </>
              ) : null}
            </h1>
          ) : (
            <h1 className="av-heading">
              Agent View
              <br />
              <span>Every connection.</span>
            </h1>
          )}
          <p className="av-subcopy">
            {focus
              ? `What this ${kindLabel}’s own screen shows you, in orbit.`
              : loginUrl ? "Your organisation’s people and AI agents, in orbit. This is a sample workspace — log in to see yours."
              : mode === "demo" ? "Studio Acme’s people, in orbit." : "Your organisation’s people, in orbit."}
          </p>
          {loginUrl && (
            <a className="av-login-cta" href={loginUrl} id="landing-login-cta">
              <LogIn size={16} strokeWidth={2.25} />
              Log in to your workspace
            </a>
          )}

          {focus ? (
            <div className="av-stats">
              <div>
                <span>{String(focus.records).padStart(2, "0")}</span>
                <label>Records</label>
              </div>
              <div>
                <span>{String(focus.groups).padStart(2, "0")}</span>
                <label>Groups</label>
              </div>
            </div>
          ) : (
          <div className="av-stats">
            <div>
              <span>{String(graph.summary.people + graph.summary.agents).padStart(2, "0")}</span>
              <label>People</label>
            </div>
            <div>
              <span>{String(graph.summary.agents).padStart(2, "0")}</span>
              <label>Agents</label>
            </div>
            <div>
              <span>{String(graph.summary.teams).padStart(2, "0")}</span>
              <label>Teams</label>
            </div>
            <div>
              <span>{String(graph.summary.levels).padStart(2, "0")}</span>
              <label>Levels</label>
            </div>
          </div>
          )}

          <div className="av-search">
            <Search size={14} strokeWidth={2.25} aria-hidden="true" />
            <input
              type="text"
              placeholder={focus ? "Search this view…" : "Search people, roles, teams…"}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label={focus ? "Search this view" : "Search the organisation"}
            />
            {search !== "" && (
              <button type="button" onClick={() => setSearch("")} aria-label="Clear search">
                <X size={14} strokeWidth={2.25} />
              </button>
            )}
          </div>

          {searchResults && (
            <div className="av-search-results" role="status">
              {searchResults.length === 0 ? (
                <p className="av-no-results">
                  No matches for &ldquo;{search}&rdquo;.{" "}
                  <button type="button" className="profile-link" onClick={() => setSearch("")}>
                    Clear search
                  </button>
                </p>
              ) : (
                <>
                  <p className="av-match-count">
                    {searchResults.length} match{searchResults.length === 1 ? "" : "es"}
                  </p>
                  <ul>
                    {searchResults.map((n) => (
                      <li key={n.id}>
                        <button type="button" className="profile-link" onClick={(e) => select(n.id, e.currentTarget)}>
                          {n.name}
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}

          <div className="av-teams" role="group" aria-label={focus ? "Filter by group" : "Filter by team"}>
            <button
              type="button"
              className={`team-chip${activeTeam === null ? " active" : ""}`}
              onClick={() => setActiveTeam(null)}
            >
              {focus ? "All groups" : "All teams"}
            </button>
            {graph.teams.map((t) => {
              const color = layout.departments.find((d) => d.deptId === t.department_id)?.color ?? "cyan";
              const active = activeTeam === t.department_id;
              return (
                <button
                  key={t.department_id}
                  type="button"
                  className={`team-chip team-${color}${active ? " active" : ""}`}
                  onClick={() => setActiveTeam(active ? null : t.department_id)}
                  aria-pressed={active}
                >
                  {t.name}
                </button>
              );
            })}
          </div>

          <div className="av-legend">
            {!focus && (
              <>
                <p>
                  <span className="legend-dot legend-cyan" /> Business departments
                </p>
                <p>
                  <span className="legend-dot legend-gold" /> Front &amp; delivery departments
                </p>
              </>
            )}
            <p>
              <span className="legend-dot legend-agent" /> AI agent
            </p>
          </div>

          <div className="av-zoom" role="group" aria-label="Zoom">
            <button type="button" onClick={() => setZoom((z) => Math.max(ZOOM_MIN, z - ZOOM_STEP))} disabled={zoom <= ZOOM_MIN} aria-label="Zoom out">
              <ZoomOut size={14} strokeWidth={2.25} />
            </button>
            <span>{zoom}%</span>
            <button type="button" onClick={() => setZoom((z) => Math.min(ZOOM_MAX, z + ZOOM_STEP))} disabled={zoom >= ZOOM_MAX} aria-label="Zoom in">
              <ZoomIn size={14} strokeWidth={2.25} />
            </button>
            <button type="button" onClick={() => setZoom(100)} aria-label="Reset zoom" title="Reset view">
              <RotateCcw size={13} strokeWidth={2.25} />
            </button>
          </div>

          <p className="av-footer-note">
            {mode === "demo" ? "Fictional sample data — nothing here is a real person." : `Live · updated ${new Date(graph.generated_at).toLocaleTimeString()}`}
          </p>
        </div>

        <div className="av-stage-scroll" ref={scrollRef}>
          <div className="av-stage-zoom" style={{ transform: `scale(${zoom / 100})` }}>
            <NetworkStage
              graph={graph}
              mode={mode}
              layout={layout}
              selectedId={selectedId}
              onSelect={(id) => select(id)}
              matched={matched}
              motionOn={motionOn}
              reducedMotion={reducedMotion}
            />
          </div>
          <div className="av-status-line">
            <svg width="120" height="20" aria-hidden="true" className="status-wave">
              {Array.from({ length: 16 }, (_, i) => (
                <rect
                  key={i}
                  x={i * 7.4}
                  y={10 - (2 + Math.abs(Math.sin(i * 0.7)) * 8) / 2}
                  width={3}
                  height={2 + Math.abs(Math.sin(i * 0.7)) * 8}
                  rx={1}
                  fill="#f2ca71"
                  opacity={selectedId ? 0.85 : 0.4}
                />
              ))}
            </svg>
            <span className="status-text">{selectedId ? "CONNECTION IN FOCUS" : "CONNECTED"}</span>
          </div>
        </div>
      </div>

      {selectedNode && (
        <ProfilePanel
          graph={graph}
          mode={mode}
          node={selectedNode}
          color={selectedColor === "gold" ? "#f2ca71" : "#35dff5"}
          onClose={closeProfile}
          onNavigate={(id) => navigate(id)}
        />
      )}
    </main>
  );
}
