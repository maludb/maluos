# MaluDB OS Core

The **kernel** of a Business OS: a hosted platform that manages a company's **AI agent workforce**,
the **super-admins** who run it, and **single sign-on** for every business application — and runs
no business application itself.

Business applications (HR, projects, reservations, scheduling, …) are separate products with their
own repositories, database, MCP servers and expert agent. They plug into this kernel through a
published integration contract and are signed in by it.

> **Status:** active development. This repository started a clean public history on 2026-09-29.

---

## Contents

- [What the kernel does](#what-the-kernel-does)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [Services and scheduled jobs](#services-and-scheduled-jobs)
- [Configuration and secrets](#configuration-and-secrets)
- [Roles and access](#roles-and-access)
- [Agents](#agents)
- [Integrating an application](#integrating-an-application)
- [Development conventions](#development-conventions)
- [Documentation map](#documentation-map)
- [Security](#security)
- [License](#license)

---

## What the kernel does

| Area | What it provides |
|---|---|
| **Estate** | One location tree — building → office (a VM) → desk (an enrolled desktop) — and the applications that reside there. |
| **Departments and people** | Org chart, department membership and administration, the directory of people, invitations. |
| **Agent HR** | Hiring, versioning and activating agents; prompts, skills, tool grants, duties, delegation; each agent has a human manager. |
| **Agent runtime** | Runs agents through per-model harnesses behind one interface; every model call is recorded in a prompt ledger. |
| **Applications** | Catalog and registry of applications, their roles and rights, scopes (sites or departments), and who holds what. |
| **Single sign-on** | `/launch/<id>` mints a 60-second, single-use hand-off token and signed claims and sends the browser to the application. |
| **Directory API** | Bearer-token API through which applications read (and, if allowed, change) people, departments and access. |
| **Approvals** | Sensitive agent and application actions pause for a super-admin's decision. |
| **AI Ops** | Runs, traces, evals, run verdicts, skill library, token spend and monthly **ledger statements** (dollar costs; no books). |
| **Assistants and messaging** | A personal assistant per person; agents message one another along the org tree; Telegram, SMS and email channels. |
| **Services for applications** | An application can text a member or call another application's shared tool through the kernel, without ever holding a provider key. |

## Architecture

Three names per company, one kernel:

```
 www.<domain>   public website (out of scope here)
 os.<domain>    THIS platform — super-admins and agents only
 app.<domain>   sign-in + launcher, for every human
 <app>.<domain> one name per application (own Apache / PostgreSQL / PHP / HTMX, own MCP, own expert agent)
```

```
 browser ──► Apache :80 ──► Next.js/React (web/, :3000)
                 │                 │  server components + actions only
                 │                 ▼
                 │          PHP JSON API (html/, 127.0.0.1:8080)  ──►  PostgreSQL 17 (maludb_os)
                 │                 ▲
                 └─ /mcp/* ────────┼──►  MCP servers (Python, mcp/)
                                   │        records · activity · actions · memory
                                   │
                     agent runner (:8815/8816) ──► harnesses (Hermes, Claude Agent SDK, system_one)
                                   │
                                   └──► ledger proxy ──► model providers
                     MaluDB (activity memory, port 8000) ◄── activity ingest (every minute)
```

Key points:

- **React is the only UI.** `web/` reads through server components and writes through server actions, both via
  `web/lib/api.ts`. **The browser never talks to PHP.**
- **PHP is a localhost-only JSON API.** The public port exposes only an allow-list: `/api/v1/{health,me,members,org-graph}`,
  the `/mcp/*` proxies and a voice webhook. See `docs/deploy/apache-react-cutover.conf`.
- **Two faces on one codebase.** `OS_HOST` (super-admins and agents) and `APP_HOST` (sign-in, launcher, settings); leaving
  both empty gives a single face.
- **Memory-first.** Every state change is logged to `activity_log` and shipped to MaluDB; agents read records and activity
  through MCP servers.

## Repository layout

```
app/         PHP application code: bootstrap, auth, db, http helpers, and app/features/<feature>/ (handlers, queries, presenters)
html/        PHP endpoints (the web root of the internal :8080 vhost), incl. html/api/v1/ (directory, ledger, runs, agents, notify, apps)
web/         Next.js 15 / React 19 front end (the only UI); web/lib/api.ts is the sole path to PHP
mcp/         Python MCP servers, the agent runner (mcp/agent_runner/), harnesses, smoke tests (mcp/smoke/), action registries
db/          numbered, additive SQL migrations (000 → latest)
bin/         CLI tools: installer, agent hiring, token minting, channel setup, cron jobs (bin/cron/)
skills/      skills shipped with the kernel's own agents
config/      config/.env.example (the real config/.env is gitignored)
docs/        requirements, build plan, integration design, per-feature specs (docs/build-specs/), deployment files (docs/deploy/)
landing/     static landing page for the bare domain
```

## Tech stack

- **PHP 8.3** — vanilla, feature-oriented page controllers with procedural PDO queries (no framework); Composer dependencies in `composer.json`.
- **PostgreSQL 17** — row-level security, security-barrier views, additive migrations.
- **Next.js 15 / React 19 / TypeScript** on Node 24 — Bootstrap 5.3 “nxl” look for day-to-day screens.
- **Python 3.12 (FastMCP, asyncpg, uvicorn)** — MCP servers and the agent runner (`mcp/requirements.txt`).
- **MaluDB** — activity memory (`maludb_core` Postgres extension plus its API service).
- **Apache 2.4** reverse proxy, **systemd** services, **cron** for the few scheduled PHP jobs.

## Getting started

**The fresh-install runbook is [`docs/install.md`](docs/install.md)** — Ubuntu 24.04, from an empty host to a signed-in
super-admin with the kernel's agents hired and the default applications installed, every step followed by its check,
written so a person or a Claude Code session with `sudo` can execute it. In outline:

1. **The host** — MaluDB core's bootstrap first (it brings PostgreSQL 17 from PGDG, pgvector, pgaudit and builds the
   `maludb_core` extension), then Apache + PHP 8.3 (`libapache2-mod-php8.3`, `php8.3-pgsql` …), Composer, Node 24.
2. **MaluDB** — the API service (:8000) and the kernel's own memory database `maludb_os_memory` (schema and role
   `maludb_os_mem`, `enable_memory_schema`, `grant_memory_access`), then a token from `POST /v1/tokens`.
3. **The code** — clone to `/var/www`, `composer install --no-dev`, `storage/` for `www-data`, `config/.env` (mode 640,
   group `www-data`) from `config/.env.example`, which documents **every** key the code reads.
4. **The database** — `createdb maludb_os`, then `db/*.sql` in order as `postgres` (all 154 apply clean on an empty
   database); passwords for `app_rw`, `app_records_ro`, `app_activity_ro`, `app_runner`.
5. **Apache** — `docs/deploy/apache-react-cutover.conf` with your domain, `Listen 127.0.0.1:8080`, the PHP ini.
6. **The front end** — `npm ci && npm run build`, hand `.next` to `www-data`, the unit and its host drop-in.
7. **MCP servers and the activity ingest** — one venv from `mcp/requirements.txt`, five units and a timer.
8. **The agent runner** — `bos-runner`/`bos-agent`, the sandboxed launcher, `/etc/business-os/runner.env` (provider keys
   live only there), the pinned Claude Code CLI and its conformance suite.
9. **First super-admin** (`bin/bootstrap_organizer.php`), a model on the Claude harness, the business's settings, cron.
10. **The kernel's agents** — the Installer (`bin/hire_installation_agent.php`), the JEV prompt writer, the Auditor and
    Sysadmin in shadow, the embedding model for memory.
11. **The default applications** — `sudo bin/install_default_applications.sh --by <email> --domain <domain>`.

**Migrations are numbered and additive**: never edit an applied file, add the next number. Views keep
`WITH (security_barrier = true)`, and new columns are appended last.

### Installing on a MaluDB hosting virtual machine (with Claude Code)

A VM from MaluDB hosting already has Ubuntu 24.04, PostgreSQL 17 and MaluDB core, and an application in
`/var/www` whose configuration names the tenant's database connection and MaluDB memory schema. The kernel
**replaces the contents of `/var/www`**: the existing application is moved to a dated sibling directory, never
deleted, and its memory schema becomes the kernel's. Start a Claude Code session on the VM as the deploy user
(normally `maludb`, with `sudo`) and give it this prompt:

```
Use the installation instructions in https://github.com/maludb/maludb-os-core.git to install the MaluDB Business OS Core.
```

**The instructions are [`docs/install-on-maludb-hosting.md`](docs/install-on-maludb-hosting.md)** — the hosting
edition of the fresh-host runbook, which it calls section by section. The installer:

1. **Asks for the domain name of the installation** and the first super-admin's email and name, and which keys
   are available (Anthropic, OpenRouter, MaluMail, an embedder) — and reminds you that these names need **DNS A
   records** pointing at the VM before anyone can reach them:

   | Name | What answers there |
   |---|---|
   | `domain.com` (and `www.`) | the landing page |
   | `app.domain.com` | sign-in and the launcher |
   | `os.domain.com` | the operating system — super-admins and agents |
   | `hr.domain.com`, `helpdesk.domain.com`, `spaces.domain.com`, `projects.domain.com` | the four default applications |

   The install does not wait for DNS (the names resolve to loopback for its checks); the list is repeated at the end
   with the current A record beside each name.
2. **Surveys the host** (PostgreSQL 17, the `maludb_core` extension, the MaluDB API on :8000, Apache/PHP/Node) and
   installs only what is missing — never MaluDB's own bootstrap.
3. **Reads the existing application's configuration file** for the database host, port, name, user, password and
   MaluDB schema, confirms them with you (never printing the password), and checks the schema is memory-enabled.
4. **Moves `/var/www` to `/var/www-previous-<date>`** (and copies the Apache default site aside) after telling you,
   clones the kernel there and follows `docs/install.md` §3–§13 with the tenant's memory database in place of the
   runbook's `maludb_os_memory`.
5. **Installs the four default applications** and closes with the DNS table, where the previous application went,
   the sign-in address, and what was left for you to set.

### Testing

- `php bin/test_app_services.php` — application services (SMS, application reads).
- `mcp/smoke_actions.py run mcp/smoke/<n>.json` — write-path smoke tests. **They write real rows** named `SMOKE <run>`; run them
  only against a development database.
- `mcp/agent_runner/tests/` — runner unit tests.

## Services and scheduled jobs

| systemd unit | Port | Purpose |
|---|---|---|
| `maludb-os-web` | 3000 | Next.js front end |
| `maludb-os-records-mcp` | 8811 | record-memory MCP (PostgreSQL) |
| `maludb-os-activity-mcp` | 8812 | activity-memory MCP (MaluDB) |
| `maludb-os-actions-mcp` | 8813 | action MCP: state-changing tools, approval hook in front |
| `maludb-os-memory-mcp` | 8814 | agent memory MCP |
| `maludb-os-agent-runner` | 8815/8816 | agent runner and ledger proxy |
| `maludb-os-channels` | — | Telegram / SMS / email channel worker |
| `maludb-os-activity-ingest.timer` | — | ships `activity_log` to MaluDB every minute |

Cron (`docs/deploy/crontab.example`): invitation-expiry report, outbound-email flush, approval expiry. Agents' scheduled duties
are fired by the runner's scheduler, not by cron.

## Configuration and secrets

- `config/.env` (PHP and tooling) and `web/.env.local` are **gitignored** — never commit them. Copy from the `*.example` files.
- Provider keys (Anthropic, OpenRouter, …) live in the runner's own environment file (`docs/deploy/runner.env.example`), never in `config/.env`.
- Tenant secrets stored by the platform are encrypted with `SECRETS_KEY`. **Never replace it; rotation adds a version.**
- API keys only: no consumer-account logins are used for model access.
- Session transcripts (`claude-log/`) and `.env` backups are gitignored because they may contain pasted secrets.

## Roles and access

Exactly three business roles: `super_admin`, `dept_admin`, `user`. “External” is a flag on a user, not a role, and agents are always
`user`. A dept-admin administers only the departments they are flagged admin of or manage; elsewhere they are an ordinary user.
Only super-admins may use the `os.` face, decide approvals, and grant application access. Application users are not OS users.

## Agents

- **Harness per model** behind one runner interface. Built: `hermes`, `claude_agent_sdk`, and `system_one` (JEV-driven playbooks).
- **Five standing departments** in every tenant: Front Office (root of the org chart), HR, Accounting, Audit, IT.
- **Every application has an expert agent and every department a lead**, proposed by the platform and confirmed by a person.
- **Prompt ledger:** every model call is recorded with full context, response, tokens, latency and cost, and linked to the activity log.
- **Evals** run on demand or on schedule by an Auditor agent, are graded by JEV, and *advise* — they never block an agent. An eval run may not change anything.
- **Approvals** pause sensitive actions until a super-admin decides.
- **Skills** are versioned in a library (AI Ops → Skills) and read by agents through the records MCP.

## Integrating an application

An application from us:

1. lives in its own repository (installed by convention at `/srv/apps/<catalog_key>`), with its own PostgreSQL database, PHP/HTMX UI and MCP servers;
2. declares itself in a `maludb-os.json` manifest — roles and rights, scopes, shared and consumed tools, its expert agent;
3. accepts the kernel's **hand-off token** at its `sso_path` and verifies the signed claims;
4. reads people and access through the **directory API**, and receives a change feed;
5. runs its agents through the kernel's **chat endpoint** and never holds a model key;
6. exports token accounting through the kernel's **ledger period export**.

The installer is `bin/app_install.php plan|apply <repository>` (`plan` is read-only; `apply` is run by a person with root) and
`bin/install_default_applications.sh`, which installs the four default applications (HR, Projects, Help Desk, Spaces) straight from GitHub. The contract is documented
in `docs/business-os-integration.md` and the `kernel-*.md` specs in `docs/build-specs/`.

### Repositories

Everything that is part of the OS lives under [github.com/maludb](https://github.com/maludb). The kernel is `maludb-os-core`;
every application is `maludb-os-<catalog_key>`, where `catalog_key` is the key its `maludb-os.json` declares and the directory it
installs to under `/srv/apps/`.

| Repository | What it is | Installed |
|---|---|---|
| [maludb-os-core](https://github.com/maludb/maludb-os-core) | The kernel (this repository) | always |
| [maludb-os-integration](https://github.com/maludb/maludb-os-integration) | The Claude Code plugin that fits an application to the kernel (`os-integration`, `os-adopt`, `os-install`) | — |
| [maludb-os-hr](https://github.com/maludb/maludb-os-hr) | HR — employment, pay records, leave, reviews; the one application that changes the directory | by default |
| [maludb-os-projects](https://github.com/maludb/maludb-os-projects) | Projects — backlogs, sprints, kanban; agents as assignees | by default |
| [maludb-os-helpdesk](https://github.com/maludb/maludb-os-helpdesk) | Help Desk — issues and requests from employees, customers and agents, worked to resolution | by default |
| [maludb-os-cidery](https://github.com/maludb/maludb-os-cidery) | Cidery — inventory, receiving and production for a cidery; an `htmx-php-builder` product adopted onto the kernel behind `OS_ENABLED` | on request |
| [maludb-os-txtschedules](https://github.com/maludb/maludb-os-txtschedules) | txtSchedules — restaurant staff scheduling | on request |
| [maludb-os-reservations](https://github.com/maludb/maludb-os-reservations) | Reservations (ZozoCal) — an existing product adopted onto the kernel (branch `os-adoption`) | on request |
| [maludb-os-pro-appointments](https://github.com/maludb/maludb-os-pro-appointments) | Pro Appointments (ZozoCal-Professional) — appointment scheduling for professional services, adopted onto the kernel 2026-10-09 with `os-adopt`: a clean repository (the source's history carried credentials), thirteen security fixes, the kernel's sign-on behind `OS_ENABLED`, each business a site, `app_roles` on a kernel-only MCP endpoint, proven on a scratch copy (124 checks) and read clean by the installer; catalog key `pro_appointments`, DNS label `appointments`; the record is `docs/os-adoption.md` there | on request |
| [maludb-os-htmx-php-guidelines](https://github.com/maludb/maludb-os-htmx-php-guidelines) | The Claude Code plugin (`htmx-php-builder`) that builds these applications — the stack, design system, PHP patterns and the OS-ready conventions | — |
| [maludb-os-docker](https://github.com/maludb/maludb-os-docker) | The dockerized install — one systemd container (`bos`) on a MaluDB hosting VM with PostgreSQL and the MaluDB API on the host: `host-install.sh`, `bos-set-keys.sh`, `bos-app.sh`; also the Claude Code plugin `maludb-os-docker` (skills `os-docker`, `os-docker-new-app`, `os-docker-change-app`, `os-docker-kernel`) for building and changing applications and the kernel against that install (2026-10-07) | — |
| [maludb-os-gl](https://github.com/maludb/maludb-os-gl) | General Ledger — chart of accounts, journal, financial statements, AR, AP, cash management; the kernel's AI statement becomes bills (planned 2026-10-04, private) | on request |
| [maludb-os-consultant-tracking](https://github.com/maludb/maludb-os-consultant-tracking) | Consultant Tracking — professional-services time, expenses with receipts, AI hosting and model-usage pass-through, T&M and fixed-bid invoicing for a technical/AI consultancy; the accounting system reads it through K7 (planned 2026-10-04, private; catalog key `consultant_tracking`, DNS label `consulting`) | on request |
| [maludb-os-spaces](https://github.com/maludb/maludb-os-spaces) | Spaces — the collaborative workspace: spaces holding pages built from Notion's block model, a wiki with verification, databases with views, and channels with threads (Notion + Slack), with OS agents as members, mentioned and DM'd (planned and approved 2026-10-05; Phase 0 built and proven, Phase 1 approved, Phase 3 complete 2026-10-06 — Phase 2 and slices 1–4 by the planning model (the block editor and channels the two exemplars), slices 5–9 by Sonnet 5.5 workers, 58/58 screens, 118/118 actions; Phase 4 the MCP servers built 2026-10-06 (68 tools, 443 checks); Phase 5 the owner's (deploy/ROOT_STEPS.sh); the fourth default) | by default |
| [maludb-os-knowledge](https://github.com/maludb/maludb-os-knowledge) | Knowledge — upload documents, get a knowledge base you can ask: sources cut into sections, typed guidelines and focus areas compiled into a MaluDB knowledge graph, asked through an ask-me-anything window whose answers cite verified quotes, a token API with keys and the kernel's agents; siblings read it through K7 (planned and approved 2026-10-05, private; catalog row db/170; Phase 1 approved and Phase 2 the shell built 2026-10-06) | on request |
| [maludb-os-processcore](https://github.com/maludb/maludb-os-processcore) | ProcessCore — a base manufacturing application for converting processes (receive lots → production orders → runs on equipment → packaging → release → shipments; heats and certificates following every child lot; industry is data, not code — a profile is seed data and skills, steel processing the default: coils slit and cut to length into sheets and blanks); forked from the cidery with its history 2026-10-08, plan `docs/processcore-design.md` there awaiting the owner's decisions (private) | on request |
| [maludb-os-inventory](https://github.com/maludb/maludb-os-inventory) | Inventory — sales inventory for a retailer that holds some stock and drop-ships the rest (modelled on mattress retail): a catalog with GTINs and every seller's identifier, own stock by location on a transaction ledger, sources read politely (Shopify `products.json`, WooCommerce's Store API, JSON-LD, supplier feeds, the marketplaces as a reference, another installation's feed) with every offer snapshotted and matched to the catalog, Find, orders filled from stock or drop-shipped with the supplier's and the customer's secure links; the ledger reads it through K7 (planned and approved 2026-10-05, private; five connectors in v1 by the owner's D7, the marketplaces Extended; catalog row db/172; Phase 0 complete and Phase 1 written 2026-10-05 — 517 + 42 + 511 proof checks, 108 screens, 132 actions, ten slice specs; Phase 1 approved and Phase 2 the shell built and proven 2026-10-09 — 327 checks under php -S, 330 under Apache; slice 1 the catalog built the same day — 310 checks; slice 2 locations and stock the same day — 325 checks; slice 3 sources and matching, the exemplar, the same day — 290 checks; slice 4 Find, availability and watches 2026-10-10 — 305 checks; the handoff; slices 5–9 by workers the same day — Phase 3 complete, 108/108 screens, 132/132 actions; Phase 4 the MCP servers (83 + 7 tools, 682 checks) the same day; Phase 5 applied by the owner 2026-10-11 — application 71, its two agents Buyer; owed the grants, the first sources, the end-to-end proof) | on request |
| [maludb-os-doccloud](https://github.com/maludb/maludb-os-doccloud) | DocCloud — the business's document cloud (Dropbox / Box / Nextcloud): libraries (personal, group, shared) of folders and documents with versions and de-duplicated blobs, tags, sharing by principal with inheritance (members, groups, departments, agents, guests, applications), secure links and file requests, keyword search in PostgreSQL, and a dedicated document graph in a MaluDB memory database of its own — never the agents' memory, never the default ask-me-anything (planned 2026-10-09, public since the owner pushed it 2026-10-11; plan `docs/doccloud-design.md` there approved the same day, D1–D16 all the recommendations; catalog row db/176; Phase 0 next; ports 8190/8841/8842) | on request |
| [maludb-os-sales-crm](https://github.com/maludb/maludb-os-sales-crm) | Sales CRM — prospecting and customer relationship management: leads worked and converted into account + contact + deal, accounts and contacts with one timeline, deals through several pipelines on a kanban board that shows the sales cycle (a drag is a POST; Pipedrive's next-activity colours, rotting, required fields per stage), every call, email, meeting and task as an activity with a reminder on a server-rendered calendar with an ICS feed, email logged by a BCC mailbox and sent through MaluMail with templates, campaigns, lists, imports, duplicates and merge, forecast and funnel reports; the Sales CRM Expert and the Sales Assistant; the ledger, Help Desk, Inventory and Consultant Tracking read it through K7 (planned 2026-10-09, private; catalog key `sales_crm`, DNS label `crm`; plan `docs/sales-crm-design.md` there approved the same day, D1–D16 and three open questions all the recommendations; catalog row db/177; Phase 0 complete and Phase 1 written the same day — 173 + 71 proof checks, 84 screens, 121 actions, 72 + 7 tools, ten slice specs, 55 consistency checks; Phase 1 approved by the owner as written the same day; Phase 2 the shell built and proven the same day (271 checks under php -S, 276 under Apache); slice 1 accounts and contacts built and proven the same day (234 checks); slice 2 leads, import, duplicates and merge built and proven 2026-10-10 (202 checks); slice 3 the board and deals built and proven the same day (191 checks); slice 4 activities, reminders and the calendar built and proven 2026-10-11 (263 checks) — the handoff point; ports 8191/8843/8844) | on request |
| [maludb-os-shareholder-intelligence](https://github.com/maludb/maludb-os-shareholder-intelligence) | Shareholder Intelligence — shareholder surveillance for a publicly traded company (or an advisory firm serving several): the DTC Security Position Report, the NOBO list and the transfer agent's register uploaded and reconciled with the share count, holders matched across lists, SEC EDGAR (filings, the XBRL share count, a full-text watch for dilution terms, 13F, 13D/13G, Forms 3/4/5, 144), FINRA short interest and daily short volume, the SEC's fails-to-deliver and the Reg SHO threshold lists fetched under a declared policy, prices and events, nineteen signal rules with an evidence class on every signal for a person to judge; the Expert and the Surveillance Analyst; nothing leaves the business (planned 2026-10-09, private; catalog key `shareholder_intelligence`, DNS label `shareholders`; plan `docs/shareholder-intelligence-design.md` there approved the same day, D1–D16 and (a)–(d) all the recommendations; K34 built as kernel db/178; Phase 0 complete the same day — schema db/001–016 proven against the anonymised reference files, 142 + 73 checks; Phase 1 next; ports 8192/8845/8846) | on request |
| [maludb-os-datalake](https://github.com/maludb/maludb-os-datalake) | Data Lake — the business's own data lake with a built-in lakehouse, on open formats and embeddable libraries (DuckLake on a PostgreSQL catalog, Parquet, DuckDB) with no data platform adopted: datasets in four zones (landing → raw → curated → product) written only by the application's writer service, a catalog filled by the machine (profiles, usage, lineage, freshness) with owners, stewards, descriptions, classifications and a glossary, contracts and checks with quarantine, incidents and computed certification, grants with masks by classification and row filters, one sandboxed query service as the only door to the data with every read audited, retention and an erasure pipeline with a proof, a SQL editor, saved and verified queries, metrics and an ask window whose answers show their SQL; the Data Lake Expert and the Data Steward; extracts of the siblings' data only through the kernel (planned 2026-10-10, **public**; catalog key `datalake`, DNS label `datalake`; plan `docs/datalake-design.md` there awaiting the owner's decisions; owes the kernel K36 the catalog row, K37 dataset feeds, K38 run facts that say who asked; ports 8193/8847/8848) | on request |
| [maludb-os-boards](https://github.com/maludb/maludb-os-boards) | Boards — a Miro-style infinite whiteboard where people and the OS's agents work on the same canvas: sticky notes, shapes, text, connectors that stay attached, frames, pen, images and files, comments pinned to the canvas with mentions; live cursors and edits through a small Python WebSocket relay over server-authoritative PostgreSQL rows (per-property last-writer-wins, an op log, no CRDT); the canvas a TypeScript + Konva.js island with a committed bundle, every other screen HTMX; every object a row in the record memory, every committed batch an episode in the activity memory; agents read a board as search → a region in an SVG dialect and write through the same handlers, so their stickies appear live; the Boards Expert and the Facilitator (planned 2026-10-10, private; catalog key `boards`, DNS label `boards`; plan `docs/boards-design.md` there awaiting the owner's decisions; owes the kernel K40 the catalog row, optionally K41 installer ports for services and K42 a `realtime` endpoint kind; ports 8198/8849/8850, live 8851) | on request |
| [maludb-os-malumail](https://github.com/maludb/maludb-os-malumail) | MaluMail — a Gmail-style webmail for the business's MaluMail mailboxes, used by people and the OS's agents alike: conversations across folders, search with Gmail's operators over an index of every message (MaluMail's server stays the record), safe HTML rendering, compose with undo and scheduled send, labels, snooze and delegation; agents read and write their own mailboxes through MCP under a policy, their held mail reviewed by the people who oversee them, arriving mail reaching them as untrusted content; super-admins create mailboxes and forwarding addresses through MaluMail's API; the Mail Expert and the Mail Clerk (planned 2026-10-10, **public**; catalog key `malumail`, DNS label `webmail`; plan `docs/malumail-design.md` there awaiting the owner's decisions; owes the kernel K43 the catalog row, K44 the overseer link, K45 an intake independent of `\Seen`, K46 agent sends through its outbox; owes MaluMail MM1 application passwords and MM2; ports 8199/8852/8853, mail service 8854, image door 8855) | on request |
| [maludb-os-developer](https://github.com/maludb/maludb-os-developer) | Developer — a web tool for database development and administration over PostgreSQL 17 and the MaluDB memory system, in the manner of phpMyAdmin: browse and maintain database objects graphically (tables, columns, constraints, indexes, views, functions, triggers, types, roles and grants), browse and edit data, an SQL editor with plans, schema compare, monitoring, and a curated view of the MaluDB memory databases; for admins, software engineers and DBAs (planned 2026-10-11, **public**; catalog key `developer`, DNS label `developer`; plan `docs/developer-design.md` there awaiting the owner's decisions; owes the kernel K49 the catalog row, K50 the developer exception in the contract, K51 an installer migration ledger, K52 a database registry door (optional), K53 the estate hardening sweep, K54 an application on its own PHP-FPM pool; ports 8201/8858/8859) | on request |

## Development conventions

- **Read the docs first, in order:** `docs/business-os-integration.md`, `docs/business-os-requirements.md`, `docs/business-os-build-plan.md`. `CLAUDE.md` holds the standing project rules for AI-assisted work.
- **Every slice ships whole:** screens (no modals, full-page create/edit, works at 375px), handlers, activity logging, action-manifest entries and MCP tools.
- **Every state-changing handler:** `require_post()`, `verify_csrf()`, an authorization check, and `log_activity()`.
- **Reads** go through whitelist presenters in `app/features/<feature>/present.php`; never serialize raw rows.
- **Writes** report through `emit_action_status()` and `json_mode_finish()`.
- **No new PHP templates.** `app/views/` holds only mail bodies.
- **Public (no-login) pages** go on the public list in `web/middleware.ts`, never on Apache's allow-list.
- **Commit style:** one commit per finished step, on `main`.

## Documentation map

| Topic | Where |
|---|---|
| Kernel boundary and integration design | `docs/business-os-integration.md` |
| Requirements and build plan | `docs/business-os-requirements.md`, `docs/business-os-build-plan.md` |
| Per-feature specs and the slice template | `docs/build-specs/` (start at `README.md`, `react-slice-template.md`) |
| Kernel specs (sign-on, directory API, ledger, chat, scopes, roles, services) | `docs/build-specs/kernel-*.md` |
| Agent runtime, evals, skills | `docs/build-specs/agent-*.md`, `eval-*.md`, `system-one-harness.md`, `skill-library.md` |
| React migration record | `docs/react-migration-plan.md`, `docs/react-cutover-runbook.md` |
| Fresh install runbook, the MaluDB-hosting edition, deployment files | `docs/install.md`, `docs/install-on-maludb-hosting.md`, `docs/deploy/` |
| Action manifest and MCP tool surface | `docs/business-os-action-manifest.md`, `docs/business-os-mcp-tool-surface.md` |

## Security

Please report vulnerabilities privately to the maintainers rather than opening a public issue. Never post credentials, tokens or
tenant data in issues or pull requests.

## License

[MIT](./LICENSE) © 2026 ehonour
