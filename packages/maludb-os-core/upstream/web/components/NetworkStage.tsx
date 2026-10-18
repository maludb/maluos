"use client";

import dynamic from "next/dynamic";
import type { KeyboardEvent } from "react";
import type { GraphLayout } from "@/lib/layout";
import { GUIDE_RADII, CENTRE_X, CENTRE_Y, curvedPath } from "@/lib/layout";
import type { OrgGraph, ViewMode } from "@/lib/types";
import AgentAvatar from "./AgentAvatar";

const ApexHeroOrb = dynamic(() => import("@/components/ApexHeroOrb"), { ssr: false });

const CYAN = "#35dff5";
const GOLD = "#f2ca71";

function colorHex(c: "cyan" | "gold"): string {
  return c === "cyan" ? CYAN : GOLD;
}

function activate(e: KeyboardEvent, fn: () => void) {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fn();
  }
}

export default function NetworkStage({
  graph,
  mode,
  layout,
  selectedId,
  onSelect,
  matched,
  motionOn,
  reducedMotion,
}: {
  graph: OrgGraph;
  mode: ViewMode;
  layout: GraphLayout;
  selectedId: string | null;
  onSelect: (id: string) => void;
  matched: Set<string> | null; // null = no filter active, everything is "matched"
  motionOn: boolean;
  reducedMotion: boolean;
}) {
  const centre = graph.centre;
  const animate = motionOn && !reducedMotion;
  const isDim = (id: string) => matched !== null && !matched.has(id);

  return (
    <div className="network-stage">
      <svg
        className="network-svg"
        viewBox="0 0 1000 680"
        role="img"
        aria-label={`${centre?.name ?? "you"} at the centre, ${layout.departments.length} ${layout.departments.some((d) => d.node.focus) ? "groups" : "departments"}`}
      >
        <defs>
          <filter id="nodeGlow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="4" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Guide rings */}
        <g className="guide-rings" aria-hidden="true">
          {GUIDE_RADII.map((r, i) => (
            <circle
              key={r}
              cx={CENTRE_X}
              cy={CENTRE_Y}
              r={r}
              fill="none"
              stroke={i % 2 === 0 ? CYAN : GOLD}
              strokeOpacity={0.08}
              strokeWidth={i === GUIDE_RADII.length - 1 ? 0.75 : 0.5}
              strokeDasharray={i === GUIDE_RADII.length - 1 ? "2 6" : undefined}
            />
          ))}
        </g>

        {/* Edges: centre -> department */}
        <g className="edges-centre" aria-hidden="true">
          {layout.departments.map((d) => {
            const dim = isDim(d.node.id);
            const path = curvedPath(CENTRE_X, CENTRE_Y, d.x, d.y);
            const pid = `edge-c-${d.deptId}`;
            return (
              <g key={pid} className={dim ? "edge dimmed" : "edge"}>
                <path id={pid} d={path} fill="none" stroke={colorHex(d.color)} strokeOpacity={dim ? 0.08 : 0.32} strokeWidth={1.25} />
                {animate && !dim && (
                  <circle r={2.2} fill={colorHex(d.color)} opacity={0.85}>
                    <animateMotion dur={`${4 + (d.deptId % 5)}s`} repeatCount="indefinite">
                      <mpath href={`#${pid}`} />
                    </animateMotion>
                  </circle>
                )}
              </g>
            );
          })}
        </g>

        {/* Edges: department -> member (primary) */}
        <g className="edges-member" aria-hidden="true">
          {layout.members.map((m) => {
            const dept = layout.departments.find((d) => d.deptId === m.primaryDeptId)!;
            const dim = isDim(m.node.id);
            const path = curvedPath(dept.x, dept.y, m.x, m.y, 0.12);
            const pid = `edge-m-${m.memberId}`;
            return (
              <g key={pid} className={dim ? "edge dimmed" : "edge"}>
                <path id={pid} d={path} fill="none" stroke={colorHex(m.color)} strokeOpacity={dim ? 0.06 : 0.26} strokeWidth={1} />
                {animate && !dim && (
                  <circle r={1.6} fill={colorHex(m.color)} opacity={0.8}>
                    <animateMotion dur={`${3 + (m.memberId % 4)}s`} repeatCount="indefinite">
                      <mpath href={`#${pid}`} />
                    </animateMotion>
                  </circle>
                )}
              </g>
            );
          })}
          {/* Extra affiliations: a member who belongs to more than one department */}
          {layout.extra.map((x) => {
            const dept = layout.departments.find((d) => d.deptId === x.deptId);
            const mem = layout.members.find((m) => m.memberId === x.memberId);
            if (!dept || !mem) return null;
            const dim = isDim(mem.node.id) || isDim(dept.node.id);
            const path = curvedPath(dept.x, dept.y, mem.x, mem.y, 0.3);
            return (
              <path
                key={`extra-${x.deptId}-${x.memberId}`}
                d={path}
                fill="none"
                stroke={colorHex(dept.color)}
                strokeOpacity={dim ? 0.04 : 0.16}
                strokeWidth={0.75}
                strokeDasharray="3 5"
              />
            );
          })}
        </g>

        {/* Department nodes */}
        {layout.departments.map((d) => {
          const dim = isDim(d.node.id);
          const selected = selectedId === d.node.id;
          const color = colorHex(d.color);
          // A ring of the focused view (lib/focus-graph.ts) is a group of records, not a department;
          // one that was cut says how many of its records are drawn.
          const ringNote = d.node.focus
            ? d.node.focus.truncated ? `${d.node.focus.shown ?? 0} of ${d.node.member_count ?? 0}` : String(d.node.member_count ?? 0)
            : null;
          const label = d.node.focus
            ? `${d.node.name}, ${d.node.member_count ?? 0} records${d.node.focus.truncated ? `, ${d.node.focus.shown ?? 0} shown` : ""}`
            : `${d.node.name} department, ${d.node.member_count ?? 0} people, ${d.node.agent_count ?? 0} agents${d.node.manager ? `, led by ${d.node.manager.name}` : ""}`;
          const labelLeft = Math.cos((d.angleDeg * Math.PI) / 180) < 0;
          return (
            <g
              key={d.node.id}
              className={`node dept-node${dim ? " dimmed" : ""}${selected ? " selected" : ""}`}
              transform={`translate(${d.x} ${d.y})`}
              role="button"
              tabIndex={0}
              aria-label={label}
              onClick={() => onSelect(d.node.id)}
              onKeyDown={(e) => activate(e, () => onSelect(d.node.id))}
            >
              <circle r={16} fill="#0a1420" stroke={color} strokeWidth={selected ? 2.5 : 1.5} filter="url(#nodeGlow)" />
              <circle r={4} fill={color} />
              {d.node.focus ? (
                // A ring of the focused view: its label is centred on the inward side of the node
                // (below it in the upper half, above it in the lower), because every record of the
                // ring lies outward — beside the node is exactly where one would land on it.
                <>
                  <text x={0} y={d.y < CENTRE_Y ? 34 : -36} textAnchor="middle" className="node-label dept-label" fill={color}>
                    {d.node.name}
                  </text>
                  <text x={0} y={d.y < CENTRE_Y ? 47 : -23} textAnchor="middle" className="node-label dept-sub">
                    {ringNote}
                  </text>
                </>
              ) : (
                <>
                  <text
                    x={labelLeft ? -22 : 22}
                    y={-2}
                    textAnchor={labelLeft ? "end" : "start"}
                    className="node-label dept-label"
                    fill={color}
                  >
                    {d.node.name}
                  </text>
                  {d.node.manager && (
                    <text x={labelLeft ? -22 : 22} y={13} textAnchor={labelLeft ? "end" : "start"} className="node-label dept-sub">
                      {d.node.manager.name}
                    </text>
                  )}
                </>
              )}
            </g>
          );
        })}

        {/* Member nodes */}
        {layout.members.map((m) => {
          const dim = isDim(m.node.id);
          const selected = selectedId === m.node.id;
          const color = colorHex(m.color);
          const isAgent = m.node.member_kind === "agent";
          const label = `${m.node.name}${m.node.title ? `, ${m.node.title}` : ""}${isAgent ? ", AI agent" : ""}`;
          const labelLeft = Math.cos((m.angleDeg * Math.PI) / 180) < 0;
          const r = 13;
          return (
            <g
              key={m.node.id}
              className={`node member-node${dim ? " dimmed" : ""}${selected ? " selected" : ""}${isAgent ? " is-agent" : ""}`}
              transform={`translate(${m.x} ${m.y})`}
              role="button"
              tabIndex={0}
              aria-label={label}
              onClick={() => onSelect(m.node.id)}
              onKeyDown={(e) => activate(e, () => onSelect(m.node.id))}
            >
              <circle r={r + 2} fill="none" stroke={color} strokeOpacity={selected ? 0.9 : 0.5} strokeWidth={selected ? 2 : 1} />
              <foreignObject x={-r} y={-r} width={r * 2} height={r * 2}>
                <AgentAvatar mode={mode} avatarUrl={m.node.avatar_url} name={m.node.name} size={r * 2} ring={color} />
              </foreignObject>
              {isAgent && <circle cx={r - 2} cy={r - 2} r={2.5} fill={color} className="agent-dot" />}
              <text
                x={labelLeft ? -(r + 8) : r + 8}
                y={m.crowded ? 4 : -3}
                textAnchor={labelLeft ? "end" : "start"}
                className="node-label member-label"
              >
                {m.crowded && m.node.name.length > 18 ? `${m.node.name.slice(0, 17)}…` : m.node.name}
              </text>
              {m.node.title && !m.crowded && (
                <text x={labelLeft ? -(r + 8) : r + 8} y={10} textAnchor={labelLeft ? "end" : "start"} className="node-label member-sub">
                  {m.node.title}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* Orb overlay — exactly at SVG centre (500,340) i.e. (50%, 50%) of the stage box.
          Wrapper is 48% of stage width and 70.59% of stage height (identical square once
          the 1000x680 aspect ratio is factored in: 0.7059 * 0.68 = 0.48). */}
      <div className="orb-overlay" aria-hidden="true">
        {animate ? (
          <ApexHeroOrb state="thinking" interactive={false} />
        ) : (
          <div className="orb-static-fallback">
            <div className="orb-static-ring" />
            <div className="orb-static-core" />
          </div>
        )}
      </div>

      {centre && (
        <button
          type="button"
          className={`centre-hit${selectedId === centre.id ? " selected" : ""}`}
          onClick={() => onSelect(centre.id)}
          aria-label={`${centre.name}${centre.title ? `, ${centre.title}` : ""} — open profile`}
        >
          <span className="visually-hidden">{centre.name}</span>
        </button>
      )}
    </div>
  );
}
