"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import type { MemberDetail, OrgGraph, OrgNode, ViewMode } from "@/lib/types";
import { computeManagerRef, computeReports } from "@/lib/detail";
import AgentAvatar from "./AgentAvatar";

// What a node of the focused view is called (lib/focus-graph.ts sets node.focus).
const FOCUS_TYPE_LABEL: Record<string, string> = {
  group: "Group", project: "Project", task: "Task", milestone: "Milestone", location: "Location",
  application: "Application", organization: "Company", contact: "Contact", deal: "Deal",
  tool: "Tool grant", duty: "Duty", department: "Department",
};

const AGENT_KIND_LABEL: Record<string, string> = {
  orchestrator: "Orchestrator",
  subagent: "Subagent",
  voice: "Voice agent",
};

function fmtDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

export default function ProfilePanel({
  graph,
  mode,
  node,
  color,
  onClose,
  onNavigate,
}: {
  graph: OrgGraph;
  mode: ViewMode;
  node: OrgNode;
  color: string;
  onClose: () => void;
  onNavigate: (id: string) => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const [detail, setDetail] = useState<MemberDetail | null>(null);

  useEffect(() => {
    closeRef.current?.focus();
  }, [node.id]);

  useEffect(() => {
    setDetail(null);
    // In the focused view a drawn member_id is a position, not a member: the real id rides in
    // node.focus, and a record that is not a person or an agent has no member detail to fetch.
    const memberId = node.focus ? (node.focus.type === "member" ? node.focus.member_id : undefined) : node.member_id;
    if (mode !== "live" || node.type !== "member" || memberId == null) return;
    const controller = new AbortController();
    fetch(`/api/member?id=${memberId}`, { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: MemberDetail | null) => {
        if (data && !("error" in data)) setDetail(data);
      })
      .catch(() => {
        /* Extra detail is progressive enhancement — the base panel already rendered. */
      });
    return () => controller.abort();
  }, [mode, node.id, node.member_id, node.focus]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const manager = computeManagerRef(graph, node);
  const reports = computeReports(graph, node);
  const isDepartment = node.type === "department";
  const focusRef = node.focus;
  const workspaceHref = focusRef
    ? focusRef.href // PHP computed it — the one place that knows the canonical URLs
    : isDepartment
      ? node.department_id != null ? `/team/departments/${node.department_id}` : null
      : node.member_id != null ? `${node.member_kind === "agent" ? "/agents" : "/team"}/${node.member_id}` : null;
  const kindLabel = focusRef && focusRef.type !== "member"
    ? FOCUS_TYPE_LABEL[focusRef.type] ?? "Record"
    : isDepartment ? "Department" : node.member_kind === "agent" ? "AI agent" : "Person";
  const agentKind = node.agent?.agent_kind ?? detail?.agent?.agent_kind;

  return (
    <aside className="profile-panel" role="complementary" aria-label={`Profile: ${node.name}`}>
      <button ref={closeRef} type="button" className="profile-close" onClick={onClose} aria-label="Close profile">
        <X size={18} strokeWidth={2.25} />
      </button>

      <div className="profile-head">
        {isDepartment ? (
          <div className="profile-dept-badge" style={{ borderColor: color, color }} aria-hidden="true">
            {node.name.slice(0, 2).toUpperCase()}
          </div>
        ) : (
          <AgentAvatar mode={mode} avatarUrl={node.avatar_url} name={node.name} size={72} ring={color} />
        )}
        <div>
          <p className="profile-kind" style={{ color }}>
            {kindLabel}
            {agentKind ? ` · ${AGENT_KIND_LABEL[agentKind] ?? agentKind}` : ""}
          </p>
          <h2>{node.name}</h2>
          {!isDepartment && node.title ? <p className="profile-title">{node.title}</p> : null}
          {isDepartment && node.manager ? <p className="profile-title">Led by {node.manager.name}</p> : null}
        </div>
      </div>

      {isDepartment && focusRef ? (
        <div className="profile-stats">
          <div>
            <span>{node.member_count ?? 0}</span>
            <label>Records</label>
          </div>
          {focusRef.truncated && (
            <div>
              <span>{focusRef.shown ?? 0}</span>
              <label>Shown</label>
            </div>
          )}
        </div>
      ) : isDepartment ? (
        <div className="profile-stats">
          <div>
            <span>{node.member_count ?? 0}</span>
            <label>People</label>
          </div>
          <div>
            <span>{node.agent_count ?? 0}</span>
            <label>Agents</label>
          </div>
        </div>
      ) : (
        <dl className="profile-facts">
          {(detail?.agent?.status ?? node.agent?.status) && (
            <div>
              <dt>Status</dt>
              <dd>{detail?.agent?.status ?? node.agent?.status}</dd>
            </div>
          )}
          {detail?.agent?.model_key && (
            <div>
              <dt>Model</dt>
              <dd>{detail.agent.model_key}</dd>
            </div>
          )}
          {detail?.agent?.harness && (
            <div>
              <dt>Harness</dt>
              <dd>{detail.agent.harness}</dd>
            </div>
          )}
          {fmtDate(detail?.agent?.hired_at) && (
            <div>
              <dt>Hired</dt>
              <dd>{fmtDate(detail?.agent?.hired_at)}</dd>
            </div>
          )}
          {fmtDate(detail?.agent?.suspended_at) && (
            <div>
              <dt>Suspended</dt>
              <dd>{fmtDate(detail?.agent?.suspended_at)}</dd>
            </div>
          )}
          {fmtDate(detail?.agent?.offboarded_at) && (
            <div>
              <dt>Offboarded</dt>
              <dd>{fmtDate(detail?.agent?.offboarded_at)}</dd>
            </div>
          )}
          {detail?.departments && detail.departments.length > 0 && (
            <div>
              <dt>Departments</dt>
              <dd className="profile-chip-row">
                {detail.departments.map((d) => (
                  mode === "live"
                    ? <a key={d.department_id} className="profile-chip" href={`/team/departments/${d.department_id}`} id={`profile-department-${d.department_id}`}>
                        {d.name}
                        {d.is_primary ? " ★" : ""}
                      </a>
                    : <span key={d.department_id} className="profile-chip">
                        {d.name}
                        {d.is_primary ? " ★" : ""}
                      </span>
                ))}
              </dd>
            </div>
          )}
        </dl>
      )}

      {manager && (
        <div className="profile-relation">
          <h3>Manager</h3>
          <button type="button" className="profile-link" onClick={() => onNavigate(manager.id)}>
            {manager.name}
          </button>
        </div>
      )}

      {(reports.length > 0 || (!focusRef && (detail?.agent?.roster?.length ?? 0) > 0)) && (
        <div className="profile-relation">
          <h3>{focusRef ? "In this group" : isDepartment ? "Team" : "Direct reports"}</h3>
          <ul className="profile-relation-list">
            {reports.map((r) => (
              <li key={r.id}>
                <button type="button" className="profile-link" onClick={() => onNavigate(r.id)}>
                  {r.name}
                  {r.title ? <span> — {r.title}</span> : null}
                </button>
              </li>
            ))}
            {(focusRef ? undefined : detail?.agent?.roster)
              ?.filter((r) => !reports.some((rep) => rep.id === r.id))
              .map((r) => (
                <li key={r.id}>
                  <button type="button" className="profile-link" onClick={() => onNavigate(r.id)}>
                    {r.name}
                    {r.role_key ? <span> — {r.role_key}</span> : null}
                  </button>
                </li>
              ))}
          </ul>
        </div>
      )}

      {/* Every node links back to its day-to-day screen (R5). Agents live in Agent HR, people in
          People & access, departments under Team — the same ids the graph already carries. */}
      {mode === "live" && workspaceHref && (
        <div className="profile-relation">
          <h3>In the workspace</h3>
          <a className="profile-link" href={workspaceHref} id="profile-workspace-link">
            {focusRef && focusRef.type !== "member"
              ? `Open this ${(FOCUS_TYPE_LABEL[focusRef.type] ?? "record").toLowerCase()}`
              : isDepartment ? "Open this department" : node.member_kind === "agent" ? "Open in Agent HR" : "Open in People & access"}
          </a>
        </div>
      )}

      {mode === "demo" && <p className="profile-fictional">Fictional data, for demonstration only.</p>}
    </aside>
  );
}
