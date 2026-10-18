# Installing the Business OS kernel on a fresh server

The complete, in-order runbook for putting `maludb-os-core` on a clean **Ubuntu 24.04** host, from an empty
machine to a signed-in super-admin with the kernel's agents hired and the default applications installed.
It is written to be executed step by step by a person or by a Claude Code session with `sudo` on the new
host; every step ends with a check, and nothing needs a browser until the last section.

Written 2026-10-06 from the reference installation (`subello.com`) and proven against it: every one of the
154 migrations applies clean, in order, on an empty database (90 tables, the five standing departments, the
Office location, 46 catalog rows, the JEV model), and `bin/bootstrap_organizer.php` makes a super-admin on it.

What this document is **not**: the install of an *application* beside the kernel (that is
`bin/app_install.php` and the `maludb-os-integration` plugin's `os-install` skill, §12 here only calls it),
and not an upgrade of an existing kernel (pull, then run the new migrations in order).

---

## 0. Before you start — what only the owner can answer

Collect these first; the steps below use them as `$DOMAIN`, `$ADMIN_EMAIL`, `$ADMIN_NAME`.

| Needed | Why | If missing |
|---|---|---|
| **The business domain** `example.com` | The kernel has three names: `os.<domain>` (super-admins and agents), `app.<domain>` (everyone's sign-in and launcher), the bare name (a static landing page). Each application gets `<label>.<domain>`. | Stop. Everything below is configured by domain. |
| **DNS and TLS** | A records (or the owner's reverse proxy) for `os.`, `app.`, the bare name and later every application name, pointing at this host. TLS is terminated by the proxy in front; the vhosts listen on :80 and honour `X-Forwarded-Proto`. | Install anyway; the names resolve to loopback through `/etc/hosts` for the checks. Record "DNS/TLS owed". |
| **The first super-admin's email and name** | `bin/bootstrap_organizer.php` | Stop. |
| **`ANTHROPIC_API_KEY`** | The Installer agent and every agent on the Claude harness. API keys only (CLAUDE.md). | The platform runs; no Claude agent can. |
| **`OPENROUTER_API_KEY`** | JEV (`typesafe/jev-1.13`): the eval grader and the `system_one` agents (Auditor, Sysadmin). | Evals and the two system agents cannot run. |
| **A MaluMail API key** and sender | Invitations, password resets, notifications (`MALUMAIL_API_KEY`, `MAIL_FROM`). | With `APP_ENV=dev` mail is logged, not sent; with `prod` it is refused. Invitations then need the printed link (`bin/invitation_link.php`). |
| **An OpenAI key** (optional) | A real embedding model for MaluDB memory (`bin/maludb_set_embedder.php`). Set it before memory accumulates. | Memory ranks by hash vectors: exact but unordered. |
| **The deploy user** | A login user with `sudo`. The MaluDB API's unit assumes a user named `maludb` with the API checked out in its home, so the simplest host has the deploy user **named `maludb`** (as the reference host does). | Edit `User=`, `WorkingDirectory=` and `ExecStart=` in `deploy/maludb-api.service`. |
| **Which agents to hire now** | The Installer is always hired (§11). The JEV prompt writer, the Auditor and the Sysadmin are the owner's choice; the default applications hire their own. | Hire later; the scripts are idempotent. |

Secrets never go on a command line in this runbook: keys are read from files you create with mode 600
outside the repository, and env files are written with an editor or a heredoc as root.

Conventions below: `$DOMAIN`, `$ADMIN_EMAIL`, `$ADMIN_NAME` are shell variables you export once; `deploy`
means the deploy user's login shell (on the reference host, `maludb`).

```bash
export DOMAIN=example.com ADMIN_EMAIL=you@example.com ADMIN_NAME="Your Name"
```

---

## 1. The host

Order matters: **MaluDB's bootstrap installs PostgreSQL 17** (from PGDG, with pgvector, pgaudit and
pg_partman) and builds the extension, so it runs before anything else touches PostgreSQL.

```bash
sudo apt update && sudo apt -y upgrade
sudo apt install -y git curl jq build-essential python3-venv python3-pip unzip
```

### 1.1 MaluDB core (the memory engine) — PostgreSQL 17 comes with it

```bash
cd ~ && git clone https://github.com/maludb/maludb-core && cd maludb-core
git submodule update --init --recursive
sudo scripts/maludb-bootstrap          # PG17 from PGDG + pgvector + pgaudit + pg_partman, builds and installs maludb_core
sudo scripts/maludb-validate            # the post-install validator must pass
sudo -u postgres psql -Atc "select name, default_version from pg_available_extensions where name='maludb_core'"
# → maludb_core|0.106.0  (or later)
sudo -u postgres psql -Atc "show pgaudit.log"
# → write, ddl, role   (the bootstrap's default; never add 'read' or 'function' without a logrotate
#   maxsize — SESSION logging of every query filled the reference host's disk on 2026-10-05)
```

The bootstrap creates a database named `maludb` holding the extension. **That database is only the
extension's bootstrap — never a tenant.** The kernel's memory goes in its own database (§2.3).

The detailed playbook, its failure modes and the listener/model-gateway services (which the kernel does not
need) are `maludb-core/docs/install.md`.

### 1.2 Apache, PHP 8.3, Composer, Node 24

```bash
sudo apt install -y apache2 libapache2-mod-php8.3 php8.3-cli php8.3-pgsql php8.3-curl php8.3-gd \
    php8.3-mbstring php8.3-xml php8.3-zip php8.3-opcache php8.3-readline composer
sudo a2enmod proxy proxy_http rewrite headers
curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -     # the reference host runs Node 24 from NodeSource
sudo apt install -y nodejs
php -v | head -1; php -m | grep -E '^(pdo_pgsql|pgsql|sodium|curl|mbstring|gd|zip)$' | wc -l   # 8.3.x; 7
node -v; npm -v; composer --version | head -1                                                   # v24.x
```

`sodium` ships inside `php8.3-common` and is needed (TOTP secrets, the hand-off token). `pdo_pgsql` is in
`php8.3-pgsql`. PHP runs as the Apache module (`libapache2-mod-php8.3`), user `www-data`, as the
reference host does; the units and file modes below assume that.

---

## 2. MaluDB — the API server and the kernel's memory database

### 2.1 The API server (as the `maludb` user, in its home)

```bash
cd ~ && git clone https://github.com/maludb/maludb-python-api-server.git && cd maludb-python-api-server
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && deactivate
sudo install -d -o maludb -g maludb -m 750 /var/log/maludb
```

The unit binds `0.0.0.0:8000`. Nothing off this host needs the API (desks are deferred), so narrow it:

```bash
sed 's/--host 0.0.0.0/--host 127.0.0.1/' deploy/maludb-api.service | sudo tee /etc/systemd/system/maludb-api.service >/dev/null
sudo systemctl daemon-reload && sudo systemctl enable --now maludb-api
curl -s http://127.0.0.1:8000/health      # {"status":"ok"}
```

The API keeps its token store in SQLite at `data/auth.db` (set `MALUDB_STORE_KEY` in
`config/maludb.env` to seal it; the README's "Configuration" section). Its background workers (embedding,
reindex) are optional timers in `deploy/`; the embedding worker only matters once an embedder is set (§11.4).

### 2.2 The kernel's memory database

One database, one schema and one login role, all named for the kernel. The names are the ones
`config/.env` carries (`MALUDB_MEMORY_DB`, `MALUDB_MEMORY_USER`); keep them unless you change both.

```bash
umask 077; openssl rand -hex 24 > ~/.mem.pw; umask 022       # the memory role's password, in a file
sudo -u postgres createdb maludb_os_memory
sudo -u postgres psql -d maludb_os_memory -c "CREATE EXTENSION maludb_core CASCADE"
sudo -u postgres psql -d maludb_os_memory -c "CREATE ROLE maludb_os_mem LOGIN PASSWORD '$(cat ~/.mem.pw)'"
sudo -u postgres psql -d maludb_os_memory -c "CREATE SCHEMA maludb_os_mem AUTHORIZATION maludb_os_mem"
sudo -u postgres psql -d maludb_os_memory -Atc "SELECT count(*) FROM maludb_core.enable_memory_schema('maludb_os_mem')"
sudo -u postgres psql -d maludb_os_memory -Atc "SELECT maludb_core.grant_memory_access('maludb_os_mem')"
sudo -u postgres psql -d maludb_os_memory -Atc "SELECT extversion FROM pg_extension WHERE extname='maludb_core'"   # 0.106.0+
```

`enable_memory_schema` reports the objects it created (about 190 on 0.106.0); re-run it after every
extension upgrade. Keep `~/.mem.pw` until `config/.env` holds the password (§5), then delete it.

### 2.3 The kernel's memory token

```bash
curl -s -X POST http://127.0.0.1:8000/v1/tokens -H 'Content-Type: application/json' \
  -d "{\"pg_dbname\":\"maludb_os_memory\",\"pg_user\":\"maludb_os_mem\",\"pg_password\":\"$(cat ~/.mem.pw)\",\"label\":\"kernel\"}" \
  | jq -r .token > ~/.maludb.token && chmod 600 ~/.maludb.token && head -c 10 ~/.maludb.token; echo …
curl -s http://127.0.0.1:8000/v1/whoami -H "Authorization: Bearer $(cat ~/.maludb.token)" | jq -c .
```

The token does not expire unless `expires_in_days` was asked for. It goes into `config/.env`
(`MALUDB_API_TOKEN`) and the runner's env file (§9); the same token in both.

---

## 3. The kernel's code

Apache's stock placeholder lives in `/var/www/html`; the kernel's `html/` replaces it.

```bash
sudo rm -rf /var/www/html && sudo chown "$USER":"$USER" /var/www && chmod 755 /var/www
git clone https://github.com/maludb/maludb-os-core.git /var/www
cd /var/www && composer install --no-dev --no-interaction          # vendor/ is gitignored; composer.lock pins it
sudo install -d -o www-data -g www-data -m 750 /var/www/storage     # uploads; STORAGE_ROOT empty = here
cp config/.env.example config/.env && sudo chgrp www-data config/.env && chmod 640 config/.env
```

Ownership: the repository belongs to the deploy user; `www-data` needs **group read** on everything PHP
serves and on `config/.env` (mode 640, group `www-data`) — never make the secrets world-readable.

---

## 4. The database

### 4.1 Create it and run every migration, in order

```bash
sudo -u postgres createdb maludb_os
cd /var/www
for f in db/*.sql; do
  sudo -u postgres psql -v ON_ERROR_STOP=1 -q -d maludb_os -f "$f" >/dev/null || { echo "FAILED at $f"; break; }
done
```

What to expect:

- `db/000` prints one `NOTICE: maludb extension not available` — expected and harmless. The kernel's
  database never holds MaluDB; memory lives in `maludb_os_memory` behind the API.
- Two files share the number 107 and two the number 145; the shell's sort order (`107_calendar…` before
  `107_runner…`, `145_application…` before `145_system_one`) is the right order.
- `db/133` is the kernel cut: it **drops** the business modules that earlier files created. On a fresh
  database that is simply part of the sequence.
- Nothing asks for input. The whole run takes about a minute.

### 4.2 Passwords for the four roles

`db/000` creates `app_rw`, `app_records_ro`, `app_activity_ro`; `db/097` creates `app_runner`. None has a
password until you set one. Keep each in a 600 file until the env files carry it (§5, §9).

```bash
umask 077; for r in app_rw app_records_ro app_activity_ro app_runner; do openssl rand -hex 24 > ~/.pw.$r; done; umask 022
for r in app_rw app_records_ro app_activity_ro app_runner; do
  sudo -u postgres psql -c "ALTER ROLE $r PASSWORD '$(cat ~/.pw.$r)'"
done
```

### 4.3 Check

```bash
sudo -u postgres psql -d maludb_os -Atc "select count(*) from pg_tables where schemaname='public'"      # 90
sudo -u postgres psql -d maludb_os -Atc "select string_agg(name, ', ' order by id) from departments"       # HR, Audit, Accounting, Front Office, IT
sudo -u postgres psql -d maludb_os -Atc "select kind||' '||name from locations"                           # office Office
sudo -u postgres psql -d maludb_os -Atc "select model_key from model_registry"                            # jev:typesafe/jev-1.13
PGPASSWORD="$(cat ~/.pw.app_rw)" psql -h 127.0.0.1 -U app_rw -d maludb_os -Atc "select 1"                # 1
```

---

## 5. Configuration: `config/.env` and `web/.env.local`

Fill `config/.env` from the example; **every key is documented there** and the file's order is this
runbook's order. Values are taken whole to the end of the line — no comment after a value.

Generate the seven keys once (never reuse one across hosts) and keep the pairings straight:

| Key | Generate | Also goes in |
|---|---|---|
| `APP_TOTP_KEY` | `openssl rand -hex 32` | — |
| `ACTION_TOKEN_KEY` | `openssl rand -hex 32` | `/etc/business-os/runner.env` (same value) |
| `SECRETS_KEY` | `openssl rand -hex 32` | — ; **never replace**, rotation adds `SECRETS_KEY_V2` |
| `WEB_INTERNAL_KEY` | `openssl rand -hex 32` | `web/.env.local` (same value) |
| `RUNNER_KEY` | `openssl rand -hex 32` | `runner.env` (same value) |
| `ACTIONS_RELAY_KEY` | `openssl rand -hex 32` | nowhere else — never the runner, never an agent |
| `PROXY_KEY_SECRET` | `openssl rand -hex 32` | `runner.env` only (§9) |

And the values from earlier sections: `DB_PASSWORD` (= `~/.pw.app_rw`), `MCP_RECORDS_DB_PASSWORD`
(`app_records_ro`), `MCP_ACTIVITY_DB_PASSWORD` (`app_activity_ro`), `MALUDB_API_TOKEN` (`~/.maludb.token`),
`MALUDB_MEMORY_PASSWORD` (`~/.mem.pw`), `OS_HOST=os.$DOMAIN`, `APP_HOST=app.$DOMAIN`,
`SESSION_COOKIE_DOMAIN=.$DOMAIN`, `APP_URL=https://app.$DOMAIN`, the MaluMail key and sender.

`APP_ENV`: `prod` on a host reached over TLS (cookies are always `Secure`); `dev` only on a local http box.

```bash
cd /var/www && php -r 'require "app/bootstrap.php"; echo db()->query("select current_user")->fetchColumn(), PHP_EOL;'   # app_rw
```

Then the front end's file:

```bash
cd /var/www/web && cp .env.example .env.local
# set LOGIN_URL=https://app.$DOMAIN/login and WEB_INTERNAL_KEY (the same value as config/.env)
sudo chown www-data:www-data .env.local && sudo chmod 640 .env.local
```

Delete the `~/.pw.*`, `~/.mem.pw` and `~/.maludb.token` files once the env files hold their values (after §9).

---

## 6. Apache: the two vhosts and the landing page

The repository's `docs/deploy/apache-react-cutover.conf` is the reference host's live configuration; only the
domain changes. It defines three virtual hosts: the public front door on `*:80` (`os.` and `app.` → the
React app on :3000, plus the allow-list of PHP endpoints and the two MCP proxies), the bare name (the static
landing page), and the **internal PHP JSON API on `127.0.0.1:8080`**, which Apache must be told to listen on.

```bash
cd /var/www
grep -q '^Listen 127.0.0.1:8080' /etc/apache2/ports.conf || echo 'Listen 127.0.0.1:8080' | sudo tee -a /etc/apache2/ports.conf
sed "s/subello\.com/$DOMAIN/g" docs/deploy/apache-react-cutover.conf | sudo tee /etc/apache2/sites-available/000-default.conf >/dev/null
sudo install -m 644 docs/deploy/php-99-business-os.ini /etc/php/8.3/apache2/conf.d/99-business-os.ini   # 25 MB uploads
sed -i "s/subello\.com/$DOMAIN/g" landing/index.html        # the landing page's three doors; its wording is yours to edit too
sudo apache2ctl configtest && sudo systemctl restart apache2
curl -s http://127.0.0.1:8080/api/v1/health                 # {"status":"ok","time":"…"}
```

The `landing/index.html` edit is a local change to a tracked file (the page says "Subello" where it should
say the business's name); keep it across pulls, or replace the page with your own. Until DNS exists, add the
names to loopback for the checks that follow:

```bash
echo "127.0.0.1 os.$DOMAIN app.$DOMAIN $DOMAIN www.$DOMAIN" | sudo tee -a /etc/hosts
```

---

## 7. The React front end (`maludb-os-web`, :3000)

The build user and the run user differ on purpose (the unit's header explains): build as the deploy user,
hand `.next` to `www-data`, and reverse that before every rebuild.

```bash
cd /var/www/web && npm ci && npm run build
sudo chown -R www-data:www-data /var/www/web/.next
sudo install -m 644 /var/www/docs/deploy/maludb-os-web.service /etc/systemd/system/
sudo install -d /etc/systemd/system/maludb-os-web.service.d
sed "s/subello\.com/$DOMAIN/g" /var/www/docs/deploy/maludb-os-web.service.d-cutover.conf \
  | sudo tee /etc/systemd/system/maludb-os-web.service.d/cutover.conf >/dev/null
sudo systemctl daemon-reload && sudo systemctl enable --now maludb-os-web
sleep 3; curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' -H "Host: app.$DOMAIN" http://127.0.0.1/     # 307 …/login  (or 200)
curl -s -o /dev/null -w '%{http_code}\n' -H "Host: $DOMAIN" http://127.0.0.1/                                  # 200 — the landing page
```

Rebuild later with: `sudo chown -R $USER:$USER .next && npm ci && npm run build && sudo chown -R www-data:www-data .next && sudo systemctl restart maludb-os-web`.

---

## 8. The MCP servers and the activity ingest

Four Python servers (records :8811, activity :8812, actions :8813, memory :8814) and a one-minute timer that
ships `activity_log` to MaluDB. All run as `www-data` from one virtualenv that the deploy user creates
world-readable (the default umask does that).

```bash
cd /var/www && python3 -m venv mcp/venv && mcp/venv/bin/pip install -q -r mcp/requirements.txt
sudo install -m 644 docs/deploy/maludb-os-records-mcp.service docs/deploy/maludb-os-activity-mcp.service \
    docs/deploy/maludb-os-actions-mcp.service docs/deploy/maludb-os-memory-mcp.service \
    docs/deploy/maludb-os-activity-ingest.service docs/deploy/maludb-os-activity-ingest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now maludb-os-records-mcp maludb-os-activity-mcp maludb-os-actions-mcp maludb-os-memory-mcp maludb-os-activity-ingest.timer
ss -ltn | grep -cE ':881[1-4] '                                   # 4
sudo systemctl start maludb-os-activity-ingest.service && journalctl -u maludb-os-activity-ingest -n 2 --no-pager
```

The actions server loads `mcp/action_registry.json` (tracked; rebuilt from the action manifest by
`bin/build_action_registry.php`) and every `mcp/registries/<app_key>.json` — files the application installer
writes for **this** host (gitignored). A fresh clone has none; that is right.

Verify a token works end to end: mint one for yourself after §10 and POST an MCP `initialize` to
`http://127.0.0.1/mcp/records` with `Authorization: Bearer <token>` and `Host: os.$DOMAIN` (CLAUDE.md,
"Useful commands").

---

## 9. The agent runner and its sandbox

`docs/deploy/hermes-install.md` and `docs/deploy/claude-agent-install.md` are the two originals; this is their
union for a fresh host, Hermes optional.

### 9.1 Users, directories, the sandboxed launcher

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin bos-runner
sudo useradd --system --no-create-home --shell /usr/sbin/nologin bos-agent
sudo usermod -a -G bos-agent,adm,systemd-journal bos-runner        # adm + systemd-journal: the Sysadmin agent's read-only collectors
sudo install -d -o bos-runner -g bos-agent -m 2770 /var/lib/business-os /var/lib/business-os/agents
cd /var/www
sudo install -o root -g root -m 0755 docs/deploy/bos-agent-exec /usr/local/sbin/bos-agent-exec
sudo install -o root -g root -m 0440 docs/deploy/bos-runner.sudoers /etc/sudoers.d/bos-runner && sudo visudo -cf /etc/sudoers.d/bos-runner
```

### 9.2 The runner's own env file (root:bos-runner 0640)

```bash
sudo install -d -m 755 /etc/business-os
sudo install -o root -g bos-runner -m 640 docs/deploy/runner.env.example /etc/business-os/runner.env
sudoedit /etc/business-os/runner.env
```

Fill: `RUNNER_DB_PASSWORD` (`~/.pw.app_runner`), `ACTION_TOKEN_KEY` and `RUNNER_KEY` (**the same values as
`config/.env`**), `PROXY_KEY_SECRET` (new), `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `MALUDB_API_URL`,
`MALUDB_API_TOKEN` (the same token as `config/.env`), `RUNNER_SCHEDULER=on`. Other providers' keys are added
later with `docs/deploy/set-provider-key.sh <provider> <key-file>`, which checks the key before restarting
anything. `ACTIONS_RELAY_KEY` never goes here.

### 9.3 The Claude Code CLI, pinned

Follow `docs/deploy/claude-agent-install.md` step 1 exactly (it pins `@anthropic-ai/claude-code@2.1.278` at
`/opt/claude-agent`, root-owned, read-only). The version is pinned because `mcp/claude_conformance` was
proven on it; bump only after that suite passes on the new one.

### 9.4 Hermes (optional)

Only if an agent will run on the Hermes harness: `docs/deploy/hermes-install.md` step 2 (a pinned clone at
`/opt/hermes`, needs `uv`). Hermes is not supported with a Claude subscription and no default agent needs it.

### 9.5 The unit, and the proof

```bash
sudo install -m 644 docs/deploy/maludb-os-agent-runner.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now maludb-os-agent-runner
sudo systemctl restart maludb-os-records-mcp maludb-os-activity-mcp maludb-os-actions-mcp
curl -s http://127.0.0.1:8815/health
# {"ok":true,"running":[],"harnesses":["claude_agent_sdk","system_one"],"subscription":false}   (+ "hermes" if installed)
cd /var/www/mcp/claude_conformance && python3 run_conformance.py --claude /opt/claude-agent/bin/claude   # green before any agent runs
```

The Claude subscription switch (`docs/deploy/set-claude-subscription.sh`) is the owner's own install only
and **off by default**; do not enable it on a new host.

---

## 10. The first super-admin, the first model, the business

### 10.1 The super-admin

```bash
cd /var/www && php bin/bootstrap_organizer.php --email "$ADMIN_EMAIL" --name "$ADMIN_NAME"
# Created super-admin #1: … ; Generated password (store it now, shown once): …
sudo -u postgres psql -d maludb_os -Atc "select id, business_role from members"       # 1|super_admin
```

(The script makes a **super-admin** since 2026-10-06. Before that it created an ordinary user, which on a
fresh host locked everyone out of the `os.` face — if you ever see `business_role = user` on member 1, the
fix is `UPDATE members SET business_role='super_admin' WHERE id=1`.)

### 10.2 A model on the Claude harness

A fresh registry holds only JEV. The Installer agent (and any Claude agent) needs an **active model on the
`claude_agent_sdk` harness**. The screen is **AI Ops → Settings → Models** on `https://os.$DOMAIN/settings/models`
(`model_save`, super-admin), and that is the preferred way because it is logged. Headless, the same row:

```bash
sudo -u postgres psql -d maludb_os -c "INSERT INTO model_registry
  (model_key, display_name, provider, provider_model_id, harness, price_input_per_mtok, price_output_per_mtok,
   price_cache_read_per_mtok, price_cache_write_per_mtok, currency, status, auth_mode)
  VALUES ('claude-fable-5-1', 'Claude Fable 5.1', 'anthropic', 'claude-fable-5-1', 'claude_agent_sdk',
          10, 50, 0.25, 12.5, 'USD', 'active', 'api_key')"
```

Prices are per million tokens and are what the prompt ledger bills with — take them from the provider's
pricing page the day you install, never guess a model id. Prove the key and the model before anyone is hired on it:

```bash
cd /var/www/mcp && sudo -u bos-runner env RUNNER_ENV_FILE=/etc/business-os/runner.env venv/bin/python -m agent_runner.probe_model claude-fable-5-1
```

### 10.3 The business's own facts

Sign in at `https://os.$DOMAIN` (or through the loopback entry) as the super-admin and set the business
name, time zone and currency at **Settings → Business** (`/settings/business`); the seed says
"MaluDB OS", UTC, USD. Upload the logo there too.

### 10.4 Cron

```bash
sudo touch /var/log/maludb-os-cron.log && sudo chown www-data:www-data /var/log/maludb-os-cron.log
sudo crontab -u www-data /var/www/docs/deploy/crontab.example && sudo crontab -u www-data -l | grep -c php     # 3
```

---

## 11. The kernel's own agents

Each script is idempotent: a second run reconciles and changes nothing else.

### 11.1 The Installer (IT) — always

It needs the integration plugin's three skills from a local clone:

```bash
cd ~ && git clone https://github.com/maludb/maludb-os-integration.git
cd /var/www && php bin/hire_installation_agent.php --by "$ADMIN_EMAIL" --plugin-dir ~/maludb-os-integration
```

It plans, a person approves, it applies through the kernel; it never holds a token or root.

### 11.2 The JEV prompt writer (Audit) — recommended

```bash
php bin/hire_jev_prompt_writer.php --by "$ADMIN_EMAIL"
```

### 11.3 The Auditor and the Sysadmin (`system_one`, shadow) — the owner's choice

Hired by a person in **Agent HR**, not by a script: harness `system_one`, model `jev:typesafe/jev-1.13`,
starting in shadow — the Auditor in Audit with playbooks `scheduled_evals`, `trace_sampling`,
`evidence_integrity` (hourly); the Sysadmin in IT with `health` and `logs_and_guardrails` (every five
minutes). The exact steps and what each needs: `docs/build-specs/system-one-harness.md`, "Hiring". Their
duties fire only with `RUNNER_SCHEDULER=on` (§9.2). Findings advise; nothing is ever suspended by them.

### 11.4 A real embedding model for memory — before memory accumulates

```bash
php bin/maludb_set_embedder.php --check
php bin/maludb_set_embedder.php --key-file ~/.openai.key      # OpenAI text-embedding-3-small; the key is stored by MaluDB, never printed
```

Changing the embedder later means re-embedding everything, so do it now or decide not to.

---

## 12. The default applications (HR, Projects, Help Desk, Spaces)

Each application from us is its own repository, database, vhost and pair of MCP servers, installed beside the
kernel by `bin/app_install.php` from its manifest. The wrapper installs the four defaults straight from
GitHub, hires their agents and grants every standing department the member role:

```bash
cd /var/www && php bin/app_install.php plan https://github.com/maludb/maludb-os-hr.git --by "$ADMIN_EMAIL" --domain "$DOMAIN"   # read-only preview
sudo bin/install_default_applications.sh --by "$ADMIN_EMAIL" --domain "$DOMAIN" --scheme https
```

What it does per application (all idempotent): clones to `/srv/apps/<key>`, creates its database and roles,
runs its migrations, writes its `config/.env` (including the MaluMail key from `~/.malumail` or the kernel's
own env, §0), its vhost `<label>.$DOMAIN` plus a loopback port, its systemd units and venv, registers it in the
kernel (catalog row, application, endpoints, scopes, roles from `app_roles`, its token, sign-on paths), writes
`mcp/registries/<key>.json` and restarts the actions server, hires the agents the manifest declares, and adds a
loopback line to `/etc/hosts` when the name does not resolve yet. `plan` on the same command afterwards must
read all `done`.

Owed to the owner after it: DNS and TLS for each `<label>.$DOMAIN`, and any grant beyond the standing
departments.

---

## 13. Proof the installation is whole

```bash
systemctl is-active apache2 maludb-os-web maludb-os-records-mcp maludb-os-activity-mcp maludb-os-actions-mcp \
    maludb-os-memory-mcp maludb-os-agent-runner maludb-api maludb-os-activity-ingest.timer | sort | uniq -c   # all active
curl -s http://127.0.0.1:8080/api/v1/health | jq -c .                      # PHP
curl -s -o /dev/null -w '%{http_code}\n' -H "Host: app.$DOMAIN" http://127.0.0.1/login      # 200 — React
curl -s http://127.0.0.1:8815/health | jq -c .harnesses                     # the runner's harnesses
curl -s http://127.0.0.1:8000/health                                        # MaluDB API
sudo -u postgres psql -d maludb_os -Atc "select count(*) from activity_log"                   # grows with every write
sudo -u postgres psql -d maludb_os -Atc "select last_id from activity_ingest_state"  # advances within a minute of the above
sudo -u postgres psql -d maludb_os -Atc "select display_name||' ('||business_role||')' from members order by id"
sudo -u postgres psql -d maludb_os -Atc "select app_key||' '||status from applications where app_key is not null order by id"
```

In the browser: `https://app.$DOMAIN` signs in and shows the launcher; `https://os.$DOMAIN` opens the OS
for the super-admin and refuses (403) anyone else; the bare name shows the landing page; `/launch/<id>` of an
installed application lands signed in on it.

Clean up: `shred -u ~/.pw.* ~/.mem.pw ~/.maludb.token` once every env file holds its value.

---

## 14. What stays the owner's

DNS and TLS for every name; provider keys and their budgets; the MaluMail sending domain; Sign in with Google
(`GOOGLE_*`); an assistant's Telegram, Twilio or MaluMail mailbox (`bin/channel_endpoint_set.php`); the
business's notification number for applications' texts (`bin/notify_endpoint_set.php`); backups of `maludb_os`,
`maludb_os_memory` and every application database (`pg_dump -Fc`; MaluDB's data is carried by `pg_dump`
since extension 0.105.0); and the Claude subscription switch, which stays off.

---

## Appendix A — every file in `docs/deploy/` and where it goes

| File | Installed at | Owner:group mode | Edit |
|---|---|---|---|
| `apache-react-cutover.conf` | `/etc/apache2/sites-available/000-default.conf` | root 644 | `subello.com` → your domain |
| `apache-mcp-proxy.conf`, `apache-canonical-urls.conf` | (fragments already inside the file above; kept for reference) | — | — |
| `php-99-business-os.ini` | `/etc/php/8.3/apache2/conf.d/99-business-os.ini` | root 644 | — |
| `maludb-os-web.service` | `/etc/systemd/system/` | root 644 | — |
| `maludb-os-web.service.d-cutover.conf` | `/etc/systemd/system/maludb-os-web.service.d/cutover.conf` | root 644 | the two hosts |
| `maludb-os-records-mcp.service`, `-activity-mcp`, `-actions-mcp`, `-memory-mcp` | `/etc/systemd/system/` | root 644 | — |
| `maludb-os-activity-ingest.service`, `.timer` | `/etc/systemd/system/` | root 644 | — |
| `maludb-os-agent-runner.service` | `/etc/systemd/system/` | root 644 | — |
| `maludb-os-channels.service` | `/etc/systemd/system/` (only once an assistant has a channel) | root 644 | — |
| `runner.env.example` | `/etc/business-os/runner.env` | root:bos-runner 640 | every value |
| `bos-agent-exec` | `/usr/local/sbin/bos-agent-exec` | root 755 | — |
| `bos-runner.sudoers` | `/etc/sudoers.d/bos-runner` | root 440 | — |
| `crontab.example` | `crontab -u www-data` | — | — |
| `set-provider-key.sh`, `set-claude-subscription.sh` | run from the repo | — | — |
| `hermes-install.md`, `claude-agent-install.md` | the two harness originals | — | — |

## Appendix B — ports on the kernel host

| Port | What |
|---|---|
| 80 | Apache: `os.`, `app.`, the bare name (TLS terminated in front) |
| 127.0.0.1:8080 | Apache: the PHP JSON API (Next.js and the actions server only) |
| 3000 | Next.js (`maludb-os-web`) |
| 8811–8814 | records, activity, actions, memory MCP servers |
| 8815 / 8816 | agent runner API / ledger proxy |
| 8000 | MaluDB API |
| 5432 | PostgreSQL 17 (local only) |
| 81xx, 88xx | each installed application's loopback PHP port and its two MCP servers (assigned by the installer) |

## Appendix C — how this runbook was checked (2026-10-06)

On the reference host: a scratch database took all 154 files of `db/` in order with `ON_ERROR_STOP` and no
error (90 tables; the five departments; the Office; 46 catalog rows; the JEV model); `bin/bootstrap_organizer.php`
against it created member 1 — which exposed that it made an ordinary user, fixed the same day; the live
systemd units, sudoers, launcher and Apache configuration were diffed against their copies in `docs/deploy/`
(identical; the activity-ingest unit and timer were missing from the repository and were added); every
environment key the PHP, Python and TypeScript code reads was listed and compared with the example files
(fourteen keys were missing from `config/.env.example` and are there now); `mcp/requirements.txt` lacked
`cryptography`, which `mcp/secrets_store.py` imports; and the tracked `mcp/registries/*.json` named the
reference host, so they are install-specific and gitignored now.
