# MaluDb AI Agent View — build handoff

Updated: September 18, 2026.

## Objective

Reproduce or continue the existing **MaluDb** frontend: a dark, animated, radial organization network based on APEX-UI. This is a working local frontend with fictional organization data. Preserve the current appearance and interactions unless the user requests changes.

The user explicitly rejected a conventional light-colored org chart with employee cards. The intended visualization is a glowing cyan particle orb inside a gold ring, surrounded by connected department and employee nodes on a dark navy canvas.

## Source of truth and recovery

- Local working repository: `/Users/user/os-frontend`.
- Upstream: https://github.com/RubenM1990/APEX-UI
- Base commit: `a8732fad1078a809cadfa810cb0d89cf4445dbed`.
- **The MaluDb implementation is currently uncommitted.** Cloning upstream alone will retrieve the original APEX interface, not this implementation. Preserve the working files and inspect `git diff` before modifying them.
- User-provided visual reference: `/Users/user/Downloads/IMG_7345.jpg`. It depicts an APEX-style radial interface on a monitor. Reproduce the application aesthetic, not the physical monitor, keyboard, room, or social-media overlay. The image may not exist on another machine.
- Local preview: http://127.0.0.1:3000/ (availability depends on whether its server is still running).
- `README.md` describes normal setup, usage, and attribution; refer to it instead of treating old conversation summaries as current specifications.

For an exact copy on another machine, transfer the working repository, excluding `node_modules` and `.next`, then install dependencies. If starting with a clean upstream clone, copy the modified files listed below and retain the original orb components.

## Latest explicit user requirements

These supersede previous names and headings:

| Element | Exact current text / behavior |
| --- | --- |
| Brand | `MaluDb` (rendered as `Malu` plus a differently colored `Db`) |
| Header tagline | `AI AGENT VIEW` |
| Browser title | `MaluDb — Your team, connected` |
| Main heading, first line | `Agent View` |
| Main heading, second line | `Every connection.` |
| Header button | `Goto Human View` |
| Human View behavior | Placeholder only; currently a native disabled button with title `Human View is coming soon`. No navigation is required. |

The eyebrow remains `WORKSPACE / ORGANIZATION`; the supporting sentence remains `Studio Acme’s people, in orbit.` The user requested branding and heading changes, not a conversion of all fictional people into real AI agents.

## Implementation map

Paths below are relative to the repository root.

| File | Responsibility |
| --- | --- |
| `app/page.tsx` | Client-side page, fictional roster, SVG network, search, team filters, zoom, profile panel, animation controls, current branding. |
| `app/globals.css` | Complete dark interface, radial layout, responsive rules, SVG node styling, static orb fallback, reduced-motion rules. |
| `app/layout.tsx` | Metadata, global stylesheet import, root HTML/body. |
| `components/ApexHeroOrb.tsx` | Original upstream orb composition, responsive sizing, dynamic particle-core loading. Reused directly. |
| `components/ApexOrb.jsx` | Original gold SVG ring and associated decorative visuals. |
| `components/ApexCore3D.jsx` | Original React Three Fiber particle cloud and bloom, including upstream error boundary. |
| `components/apex-orb.css` | Original orb animations. Imported by `ApexHeroOrb`. |
| `next.config.mjs` | Explicit `outputFileTracingRoot` resolves to this repository, avoiding accidental parent-workspace inference. |
| `package.json`, `package-lock.json` | Runtime versions, scripts, patched dependency resolution. |
| `README.md` | Setup and current feature overview. |
| `LICENSE`, `CREDITS.md` | Preserve upstream attribution and licensing. |

`ApexWorld`, `ReasoningWeb`, the weather API, and the original overview/status components remain in the repository but are not used by the current page. The current network is a custom declarative SVG, not the original imperative `ReasoningWeb` roster.

## Stack and dependency decisions

Next.js 15 App Router, React 19, TypeScript, plain CSS, Lucide icons, Three.js, React Three Fiber, and React Three Postprocessing. No Tailwind or external graph layout library is required.

The original Next.js pin had audit findings. The working package uses `next` and `eslint-config-next` at `^15.5.25`, with a `postcss` override of `^8.5.28`. Preserve the lockfile for reproducibility. At the time of implementation, the updated install reported zero vulnerabilities; rerun audit if current status matters.

The npm package is still named `apex-ui`; that internal identifier was not part of the user’s requested visible branding change. The upstream `lint` script remains `next lint`; standalone lint has not been verified. Do not claim it passes. Production build/type checking is the established verification command.

## Visual construction

1. Fill the viewport with a dark navy radial gradient, subtly brighter behind the network. Add a very faint grid, sparse cyan stars, and small decorative circuit traces. Set `color-scheme: dark` so native scrollbars match.
2. Place a slim header across the top: GitBranch icon, MaluDb wordmark, tagline, disabled Human View button, sample-workspace indicator, and motion toggle.
3. Place the heading and three summary counts at upper left: 13 people, 06 teams, 03 levels. Below them, show search and the six team filters.
4. Give the radial network the majority of the center/right space. Use an SVG `viewBox="0 0 1000 680"` with the CEO at `(500, 340)`.
5. Overlay the real upstream `ApexHeroOrb` at exactly that SVG center. It runs with `state="thinking"` and `interactive={false}`. Its wrapper is 48% of stage width and 70.59% of stage height. Its decorative pointer events are disabled; a separate circular button (26% stage width) opens the CEO profile.
6. Draw thin orbital guide rings with radii 146, 156, 194, 205, and 254. The outermost uses a dotted stroke. Use curved reporting links, glow filters, and small animated particles traveling along links.
7. Put department heads closer to the center and contributors farther out. Department nodes have larger glowing circles and team labels, followed by the head’s name. Contributor nodes show person name and role in smaller text. Place labels to the left or right based on their position relative to the center.
8. Render a small gold waveform and `CONNECTED` status below the network. Selection changes the status to `CONNECTION IN FOCUS`. Finish with a quiet legend, zoom controls, and sample-data footer.

Palette: cyan `#35dff5`, gold `#f2ca71`, muted blue-gray text, near-black navy background. Typography uses Space Grotesk for headings/node titles, DM Sans for body text, and system monospace for small interface labels. Google Fonts has system fallbacks.

Consult `app/globals.css` for exact spacing, gradients, glow values, and breakpoints rather than approximating an already available implementation.

## Sample organization and graph semantics

The authoritative roster is the `people` array in `app/page.tsx`. Each item has `id`, `name`, `role`, `team`, `x`, `y`, and optional `manager` (another person’s ID). Coordinates are deterministic, not calculated by a force-directed simulation.

The hierarchy is:

- Olivia Rhye, CEO, is the central node.
- Alex Morgan leads Strategy; Sam Rivera reports to Alex.
- Jordan Lee leads Finance; Taylor Kim reports to Jordan.
- Avery Chen leads Operations; Natali Craig reports to Avery.
- Phoenix Baker leads Engineering; Drew Cano reports to Phoenix.
- Lana Steiner leads Design; Orlando Diggs reports to Lana.
- Demi Wilkinson leads Marketing; Kate Morrison reports to Demi.

All six department heads report to Olivia. There are 13 people, six teams plus the CEO’s Leadership category, and three levels. Use the existing roster for exact role strings and positions.

Strategy, Finance, and Operations use cyan; Engineering, Design, Marketing, and the CEO use gold. Links represent actual manager relationships: CEO → department head → contributor. Do not connect every contributor directly to the CEO merely to achieve a radial look.

## Interaction behavior

- **Profiles:** Clicking a node, its label, or the central orb selects that person and opens a right-side profile panel. Show initials, name, role, team, manager, direct reports, and a fictional-data note. Manager and report buttons navigate to those profiles. Highlight related graph edges. Escape or the close button dismisses it.
- **Keyboard:** SVG node groups use `role="button"`, `tabIndex={0}`, descriptive accessible names, Enter/Space activation, and a visible focus ring. Opening a profile focuses its close button; closing attempts to restore the opener’s focus. The profile is a nonmodal aside, not a modal dialog.
- **Search:** Case-insensitive substring match across name, role, and team. Combine with the selected team filter using AND. Dim nonmatching nodes and links without rearranging the graph; show match counts and clickable result names. Include no-results copy and clear-filter controls.
- **Teams:** All teams is the default. Selecting a team highlights its two people; clicking the selected team again returns to All teams.
- **Zoom:** Scale the graph around its center from 60% to 140% in 10% steps. Reset view restores 100%. Disable +/- at their limits.
- **Motion:** Toggle between animated and static presentation. Pausing unmounts the animated orb and substitutes a CSS gold-ring/cyan-particle approximation; SVG flow particles and ambient animation stop. Honor `prefers-reduced-motion` even when the toggle state is on.
- **Human View:** Disabled placeholder only. Do not add a destination or implement another view without a new request.

## Responsive behavior

Desktop uses a left control column and a large center/right stage. Styles adjust at 1100px and 700px, with extra space at 1600px and above. On mobile, controls become compact wrapping filters above the network. The graph stays 650px wide for readability and scrolls horizontally inside its own viewport. A ResizeObserver centers the scrollable graph on initial layout and viewport resizing. Profiles become a wide bottom panel. Some small header/footer labels are hidden on narrow screens.

Preserve the SVG aspect ratio and orb-to-SVG alignment when changing sizing. Do not shrink the graph into illegible labels just to fit all nodes onto a phone screen.

## Verification and operational notes

Use the setup/run commands in `README.md`. Build before claiming completion:

```sh
npm run build
git diff --check
```

The last implementation build passed compilation and TypeScript checks. Browser checks verified profiles, manager/report navigation, search, department matching, pause motion, and the latest heading/disabled button. Browser console error checks were empty during the radial-view verification. Desktop and 390px mobile layouts were visually inspected. There is no dedicated automated test suite for this UI.

For browser smoke testing:

1. Confirm MaluDb, AI AGENT VIEW, Agent View, and Goto Human View render correctly; the Human View button is disabled.
2. Allow the dynamically loaded WebGL particles to appear, then inspect orb alignment and surrounding labels.
3. Open Phoenix Baker, then Drew Cano from the direct-report list; confirm the reporting relationship.
4. Search for Lana; expect one match. Clear filters, select Design; expect two matches. Try an impossible search and verify empty-state text.
5. Pause and resume motion; verify the static fallback and restoration of the particle core.
6. Test zoom/reset, keyboard node activation, Escape dismissal, and mobile horizontal scrolling.
7. Check the browser console for errors.

Use only one server on port 3000. A production `npm start` server does not reliably adopt rebuilt output until restarted. Stop the server owned by this task, build, restart it, and reload the browser. Avoid running `next dev` and `next build` simultaneously against the same `.next` directory; an earlier parallel run caused missing build-trace files.

## Scope and next-agent guidance

The requested interface and latest copy changes are complete. No backend, authentication, actual AI agents, microphone capture, persistence, deployment, or live organization integration has been built or requested. The earlier light dashboard, directory table, CSV export, and collapsible card tree were superseded by this radial implementation; do not restore them from stale summaries.

Read applicable local instructions before editing. The user supplied a Superpowers bootstrap instruction: `~/.codex/superpowers/.codex/superpowers-codex bootstrap`. Use applicable available skills for further work; `superpowers:verification-before-completion` is useful for final checks and `superpowers:systematic-debugging` for actual failures. The `handoff` skill was used to create this document. No image-generation or website-hosting skill is needed to reproduce this local code-based visualization.

