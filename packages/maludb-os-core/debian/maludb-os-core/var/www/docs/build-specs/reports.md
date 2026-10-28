# Build spec: Reports & dashboards — "show me the numbers, the way I asked for them last time"

2026-09-20 · Module 13 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
Schema: db/062 (`report_definitions`, `report_runs`, `report_schedules`, `dashboards`,
`dashboard_widgets`; views `mcp_report_definitions`, `mcp_report_runs`, `mcp_report_schedules`,
`mcp_dashboards`, `mcp_dashboard_widgets`) + additive **db/117**. Manifest "Reporting &
dashboards": 9 screens, 9 actions. Tools: `find_reports`, `run_report`, `report_schedules`.
**Installed:** `chart.js` + `react-chartjs-2` (npm, bundled — the browser loads nothing from a CDN).

## A report is a tool call, not SQL
A saved report = a read tool of the records (or activity) MCP server + its parameters + how to
draw the answer. There is no SQL editor and no free-form query anywhere. **PHP runs a report by
calling the MCP server as the VIEWING member** (`app/mcp_client.php`), so a report shows each
viewer exactly what the tool would show them: row visibility is the tool's, never the report's.
The same saved report run by two people returns two different answers, by design.

**Token mechanics.** Per run (per page, for a dashboard) PHP inserts ONE row in
`mcp_access_tokens` for the viewer — label `report-run`, scope `mcp`, `expires_at = now() + 2
minutes` — uses it for the MCP session on localhost, and **deletes the row in a `finally`**; if
the delete ever fails the token still dies in two minutes. Only its sha256 is stored; the raw
value lives in one PHP variable and is never sent to the browser, logged or returned. An agent
running a report gets a token for the agent, so its tool grants apply (`mcp/agent_grants.py`).

**The catalogue** is the server's own `tools/list` (read-only tools), cached for five minutes in
`storage/cache/` (the list is the same for every person; an agent's filtered list is never
cached). A tool's JSON schema drives the form: enum → select, boolean → yes / no, number →
number, anything else → text; `params` as JSON is what an agent passes. Saved params are checked
against the schema (unknown key, wrong type, bad enum value, a required param that is neither
given nor asked at run time); the tool's own validation is the final word at run time and its
refusal is shown as a sentence, never a 500. `prompt_params` are asked on the report page each
time (the period, usually). Tools that answer an OBJECT rather than rows (`get_ticket`,
`mail_thread`, `employment_profile`, …) are offered and drawn as a **detail** — its plain values,
and each list inside it as its own table; they cannot be charted.

**db/117 (additive):** `report_definitions.presentation jsonb NOT NULL DEFAULT '{}'` —
`{label, values[], columns[]}`: which column names a row, which numeric columns are drawn, which
columns the table shows — appended to `mcp_report_definitions`. With none chosen: the label is
the first text column, the values the first numeric columns that are not ids. The five system
reports of db/062 get working params (e.g. AI spend grouped by department).

**Nothing of a result is stored.** `report_runs` records who, when, params, status, row count,
duration, error — never rows. No result cache. `report_export` does not file a document.

## Who may do what
`mcp_report_definitions`: an insider holding the report's `module` sees it when it is shared or
theirs. Saving: any insider for their own (they must hold the module they name); sharing needs
`mod:reports`; a system report is changed only by a super-admin — anyone copies it (the form
opens prefilled from `?copy=`). Archive: own, or `mod:reports`. Schedules: `mod:reports` or
admin. Dashboards: own; shared ones are an admin's. A widget's report must be visible to whoever
adds it; whoever LOOKS at the dashboard sees each widget as themself — a widget they may not run
says so in its own tile and the rest of the page is unharmed.

## Scheduled delivery emails a LINK, never the data
There are no attachments and no server-side rendering for somebody else: the recipient opens
`/reports/{id}?…params` and sees the report as THEMSELF. Recipients are active insiders of this
business, never a typed outside address (`recipient_emails` stays empty — OPEN). Tools that
return prompt payloads or pay (`prompt_for_request`, `ledger_calls`, `payroll_summary`,
`pay_runs`, `employment_profile`) can be saved and run by whoever could call them, but **not
scheduled** (OPEN). `report_schedule_save` pauses for approval when an agent asks (db/105).
`bin/run_report_schedules.php` (advisory lock; a schedule is claimed by moving `next_run_at`
before anything is sent, so a slot is delivered once) mails each recipient through `send_email`
(`emails/report-link`), writes a `report_runs` row for the delivery and logs
`report_schedule.deliver` (source `cron`). `--dry-run` prints who would be mailed which link and
**writes nothing**. Its cron line is in `docs/deploy/crontab.example` and is NOT installed
(owner's decision pending, as for the other lines). Times are in the business timezone;
`day_of_week` 0 = Sunday; quarterly = the first month of each quarter.

## Charts
Chart.js through `react-chartjs-2`: bar, line, pie; `number` is the first value, big; `list` and
`table` are tables. Every chart has its table beneath it (accessibility, print). At most 500
rows reach a screen, 50 points a chart, 5 000 rows a CSV.

## Export
CSV: `GET /reports/download.php?report=&params=` through `/api/download` — runs as the viewer,
logs `report.export`, streams; cells beginning `= + - @` (or tab / CR) are prefixed with `'`.
The action `report_export` (agents) answers the CSV text in its result, capped at 200 KB. PDF is
refused as not available yet (OPEN).

## Screens
| Screen | React route | PHP read |
| --- | --- | --- |
| `reports-list` | `/reports?category=&mine=&archived=` | `html/reports/index.php` |
| `report-view` | `/reports/{id}?params…` | `html/reports/view.php` (runs it; logs `report.run`) |
| `report-add` / `report-edit` | `/reports/new?tool=&category=&copy=`, `/reports/{id}/edit?tool=` | `html/reports/form.php` |
| `report-schedules` | `/reports/schedules` | `html/reports/schedules.php` |
| `report-schedule-add` | `/reports/{id}/schedule?schedule=` | `html/reports/schedule.php` |
| `dashboards-list` | `/dashboards` (with the "new dashboard" form) | `html/dashboards/index.php` |
| `dashboard-view` | `/dashboards/{id}` | `html/dashboards/view.php` (runs every widget, one MCP session, 8 s each) |
| `dashboard-edit` | `/dashboards/{id}/edit` | `html/dashboards/form.php` |

Widgets: at most 12; kinds `report` (drawn as the report says), `metric` (its first number),
`list` (its first 8 rows), `text`; width half or full; reordered by up / down.

## Actions
As the manifest lists them (`html/reports/`, `html/dashboards/`). The manifest gains, as optional
parameters: `label_column`, `value_columns`, `columns`, `description` on `report_save`; `move` on
`dashboard_widget_save`. `report_save` with `report` is a partial update for agents.
