# Installing the Business OS kernel on a MaluDB hosting virtual machine

**For the installer** — a Claude Code session, or a person — on a virtual machine provisioned by MaluDB hosting.
The owner starts the install with one prompt:

> Use the installation instructions in https://github.com/maludb/maludb-os-core.git to install the MaluDB Business OS Core.

This document is that path. It is the hosting-VM edition of the fresh-host runbook, [`install.md`](install.md):
the host already has **Ubuntu 24.04**, **PostgreSQL 17** and **MaluDB core** installed, and an existing application
in **`/var/www`** whose configuration file names the tenant's database connection and MaluDB memory schema. The
kernel replaces the contents of `/var/www`; the existing application is moved aside, never deleted. Every other
step is `install.md`'s, and this document says which of its sections to run, which to skip and what to substitute.
Read both before starting; execute from this one.

Written 2026-10-07 from the reference installation and from `install.md` (proven 2026-10-06).

---

## How to behave as the installer

1. **Ask first, then run.** §1 below is a short interview. Do not touch the host before the answers are in hand
   and the DNS reminder has been given.
2. **Two actions change what was there**: moving `/var/www` aside (§4) and replacing Apache's default site (§6).
   Say what you are about to do, name the destination, and do it only once the owner has agreed.
3. **Secrets never appear in output** — not the tenant's database password, not a generated key, not a token. Read
   them from files, write them into env files with a heredoc or `sed`, and print a prefix or a length at most.
4. **Every step ends with its check** (the `#` comment on the command line). A check that does not match stops the
   install: report what you saw, do not improvise around it.
5. **`sudo` is expected.** The deploy user is the login you are running as (on MaluDB hosting that is normally
   `maludb`, which is also what the MaluDB API's unit assumes). Anything that `install.md` runs as `postgres` or
   `root` is run with `sudo` here.
6. **The order is this document's.** Section numbers in **bold** (§3–§13 of `install.md`) are the fresh-host
   runbook's; plain section numbers are this document's.

---

## 1. The interview — what only the owner can answer

Ask these before anything else, in one message:

| Ask | Why | If the owner has no answer |
|---|---|---|
| **The domain name of the installation**, e.g. `example.com` | Everything is configured by domain: `os.`, `app.`, the bare name, and one name per application. Use it as `$DOMAIN` below. | Stop. Nothing below can be configured. |
| **The first super-admin's email and name** | `bin/bootstrap_organizer.php` (**§10.1**). | Stop. |
| **`ANTHROPIC_API_KEY`** | The Installer agent and every agent on the Claude harness. API keys only. | Install anyway; no Claude agent can run until it is set (`docs/deploy/set-provider-key.sh`). |
| **`OPENROUTER_API_KEY`** | JEV: the eval grader and the `system_one` agents. | Install anyway; evals and the Auditor/Sysadmin wait. |
| **A MaluMail API key and sender** | Invitations, password resets, notifications. | `APP_ENV=prod` refuses to send without one; invitations then need the printed link (`bin/invitation_link.php`). |
| **An OpenAI key** (optional) | A real embedding model for memory, before memory accumulates (**§11.4**). | Memory ranks by hash vectors until one is set. |

Then give **the DNS reminder**, with the real names filled in and the host's public address beside them:

> Before people can reach the installation, these names must have **DNS A records** pointing at this machine
> (`<the host's public IPv4>`). TLS is terminated by the proxy in front; the vhosts listen on :80.
>
> | Name | What answers there |
> |---|---|
> | `example.com` (and `www.example.com`) | the landing page |
> | `app.example.com` | sign-in and the launcher, for everyone |
> | `os.example.com` | the operating system, for super-admins and agents |
> | `hr.example.com` | HR |
> | `helpdesk.example.com` | Help Desk |
> | `spaces.example.com` | Spaces |
> | `projects.example.com` | Projects |
>
> The install does not wait for DNS: the names resolve to loopback through `/etc/hosts` for the checks, and I
> will repeat this list at the end with anything still unresolved.

`hr`, `helpdesk`, `spaces` and `projects` are the four default applications `bin/install_default_applications.sh`
installs (**§12**); each is its own vhost at its own name. Find the public address with `curl -s https://api.ipify.org`
or ask the owner; `hostname -I` shows the interfaces when the VM has a public one.

```bash
export DOMAIN=example.com ADMIN_EMAIL=you@example.com ADMIN_NAME="Your Name"
```

---

## 2. Survey the host — what is already there

Confirm the premises before relying on them. Each line's check is what a MaluDB hosting VM shows.

```bash
lsb_release -ds                                                                   # Ubuntu 24.04.x LTS
psql --version && systemctl is-active postgresql                                  # psql (PostgreSQL) 17.x, active
sudo -u postgres psql -Atc "select default_version from pg_available_extensions where name='maludb_core'"   # 0.106.0 or later
ls /etc/maludb/                                                                   # maludb.conf, maludb-modeld.conf, maludb-mc2dbd.conf (the bootstrap's tree)
curl -s http://127.0.0.1:8000/health                                              # {"status":"ok"} — the MaluDB API, if hosting installed it
systemctl is-active apache2; php --version | head -1; node --version; composer --version 2>/dev/null | head -1
ls -la /var/www                                                                   # the existing application
```

What the survey decides:

- **MaluDB core present** → skip **§1.1** entirely. Never run `maludb-bootstrap` on a hosting VM; hosting owns
  PostgreSQL and the extension.
- **MaluDB API absent** (nothing on :8000) → run **§2.1** as written (the API server in the deploy user's home,
  bound to loopback). If present, skip **§2.1** and use the running one.
- **Apache, PHP 8.3, Composer or Node 24 absent** → run **§1.2** for what is missing. An existing Apache is kept;
  only its default site changes (§6 below).
- **Something else lives on :80, :3000, :8080, :8811–8816** (`ss -ltnp`) → stop and report; the kernel's ports are
  Appendix B of `install.md`.

---

## 3. Read the existing application's configuration

The application in `/var/www` was configured by hosting with the tenant's database connection and MaluDB memory
schema. The kernel reuses **the memory schema** (that is the tenant's memory, and it stays theirs) and creates
**its own records database** beside it (**§4**), exactly as on the reference host: the kernel's database never
holds MaluDB, memory lives in the tenant's database behind the API, and each application the installer adds
gets a database of its own anyway.

Find the file. Look, in this order, and stop at the first that names a database:

```bash
cd /var/www && ls -la; ls -la config .env* 2>/dev/null
grep -rIl --exclude-dir=vendor --exclude-dir=node_modules -iE 'dbname|DB_NAME|PG_DATABASE|pg_dbname|DATABASE_URL|schema' \
     --include='*.env' --include='.env*' --include='*.php' --include='*.ini' --include='*.json' --include='*.yaml' --include='*.yml' --include='*.conf' . 2>/dev/null | head
```

The usual shapes: an env file (`.env`, `config/.env`: `DB_HOST=…`, `DB_NAME=…`, `DB_USER=…`, `DB_PASSWORD=…`,
`MALUDB_SCHEMA=…`), a PHP array (`config.php`, `config/database.php`: `'dbname' => …`, `'schema' => …`), a PDO DSN
(`pgsql:host=…;dbname=…`), or a `DATABASE_URL`. Take from it:

| Value | Becomes | Note |
|---|---|---|
| host, port | `$MEM_HOST`, `$MEM_PORT` | `/var/run/postgresql` (a socket) means `127.0.0.1:5432` for the API's purposes |
| database | `$MEM_DB` → `MALUDB_MEMORY_DB` | the tenant's database |
| user, password | `$MEM_USER`, the password in `~/.mem.pw` (mode 600) → `MALUDB_MEMORY_USER`, `MALUDB_MEMORY_PASSWORD` | the tenant's memory role |
| MaluDB schema | `$MEM_SCHEMA` | the schema `enable_memory_schema` was run for; on the reference host it equals the role's name |

**Show the owner the host, port, database, user and schema — never the password — and have them confirm**
before going on. If the file names no schema, the schema is the one that holds the memory tables (next check).
If no such file exists, stop: ask the owner for the tenant's connection and schema.

Verify the connection and that the schema is memory-enabled:

```bash
umask 077; printf '%s' '<the password, pasted by the owner or copied from the file>' > ~/.mem.pw; umask 022
export MEM_HOST=127.0.0.1 MEM_PORT=5432 MEM_DB=<database> MEM_USER=<user> MEM_SCHEMA=<schema>
PGPASSWORD="$(cat ~/.mem.pw)" psql -h "$MEM_HOST" -p "$MEM_PORT" -U "$MEM_USER" -d "$MEM_DB" -Atc "select 1"            # 1
sudo -u postgres psql -d "$MEM_DB" -Atc "select extversion from pg_extension where extname='maludb_core'"                # 0.106.0+
sudo -u postgres psql -d "$MEM_DB" -Atc "select count(*) from information_schema.tables where table_schema='$MEM_SCHEMA' and table_name='maludb_episode'"   # 1
```

A `0` on the last line means the schema was never enabled for memory; that is **§2.2**'s two calls, run against
the tenant's database and schema instead of `maludb_os_memory`/`maludb_os_mem`:

```bash
sudo -u postgres psql -d "$MEM_DB" -Atc "SELECT count(*) FROM maludb_core.enable_memory_schema('$MEM_SCHEMA')"   # ~190 objects
sudo -u postgres psql -d "$MEM_DB" -Atc "SELECT maludb_core.grant_memory_access('$MEM_SCHEMA')"
```

Keep `~/.mem.pw` until `config/.env` holds the password (**§5**), then shred it.

---

## 4. Move the existing application aside

Nothing is deleted. The application goes to a dated sibling directory with its ownership intact; its Apache
site file is copied beside it so it can be put back.

```bash
STAMP=$(date +%Y%m%d)
sudo systemctl stop apache2
sudo cp -a /etc/apache2/sites-available/000-default.conf /etc/apache2/sites-available/000-default.conf.previous-$STAMP 2>/dev/null || true
sudo cp -a /etc/apache2/ports.conf /etc/apache2/ports.conf.previous-$STAMP
sudo mv /var/www /var/www-previous-$STAMP
ls -ld /var/www-previous-$STAMP                                                   # the old application, owner unchanged
sudo install -d -o "$USER" -g "$USER" -m 755 /var/www
```

Tell the owner the path. If the previous application had a systemd unit, a cron line or a database of its own,
leave them; this install creates nothing with the same names (the kernel's are `maludb-os-*`), and removing the
old ones is the owner's decision later.

Apache stays stopped until §6 installs the kernel's site.

---

## 5. The kernel's code, database and configuration (§3, §4, §5)

Run **§3** (clone, Composer, `storage/`, `config/.env`), **§4** (the `maludb_os` database, all `db/*.sql` in
order as `postgres`, passwords for the four roles, the checks) and **§5** (the keys, the two env files) exactly as
written, with these substitutions:

- **§3's first line** is already done: `/var/www` exists, empty, owned by you. Skip the `rm -rf /var/www/html`.
- **§2.2 and §2.3 are replaced** by §3 above: the memory database, user and password are the tenant's. Mint the
  kernel's memory token against them:

  ```bash
  curl -s -X POST http://127.0.0.1:8000/v1/tokens -H 'Content-Type: application/json' \
    -d "{\"pg_dbname\":\"$MEM_DB\",\"pg_user\":\"$MEM_USER\",\"pg_password\":\"$(cat ~/.mem.pw)\",\"label\":\"kernel\"}" \
    | jq -r .token > ~/.maludb.token && chmod 600 ~/.maludb.token && head -c 10 ~/.maludb.token; echo …
  curl -s http://127.0.0.1:8000/v1/whoami -H "Authorization: Bearer $(cat ~/.maludb.token)" | jq -c .   # the tenant's database and role
  ```

- **In `config/.env`** (**§5**) set `MALUDB_MEMORY_DB=$MEM_DB`, `MALUDB_MEMORY_USER=$MEM_USER`,
  `MALUDB_MEMORY_PASSWORD=<~/.mem.pw>` in place of the `maludb_os_memory`/`maludb_os_mem` defaults, and
  `MALUDB_API_TOKEN` from `~/.maludb.token`. `bin/app_install.php` mints each application's memory token with
  these three, so they must be the tenant's real login. Everything else in §5 is as written: `OS_HOST=os.$DOMAIN`,
  `APP_HOST=app.$DOMAIN`, `SESSION_COOKIE_DOMAIN=.$DOMAIN`, `APP_URL=https://app.$DOMAIN`, `APP_ENV=prod`, the
  seven generated keys and their pairings, the MaluMail key and sender if given.
- The kernel's records database stays **`maludb_os`** with its four roles; the tenant's database is not touched
  by the migrations. `db/000`'s `NOTICE: maludb extension not available` is expected here too (it looks for an
  extension named `maludb`, not `maludb_core`).

---

## 6. Apache — the kernel's site replaces the default site (§6)

Run **§6** as written. It overwrites `/etc/apache2/sites-available/000-default.conf` (a copy is beside it from
§4 above), adds `Listen 127.0.0.1:8080`, installs the PHP ini, puts `$DOMAIN` into the landing page and the
loopback names into `/etc/hosts`. Then start what §4 stopped:

```bash
sudo apache2ctl configtest && sudo systemctl start apache2 && systemctl is-active apache2          # active
curl -s http://127.0.0.1:8080/api/v1/health                                                        # {"status":"ok",…}
```

If hosting had other sites enabled (`ls /etc/apache2/sites-enabled/`), leave them; only the default site is the
kernel's, and a `ServerName` clash shows in `configtest`.

---

## 7. The front end, the MCP servers, the runner, the super-admin, the agents (§7–§11)

Run **§7** through **§11** exactly as written. Nothing about them depends on the hosting VM. Two reminders:

- **§9.2** copies `MALUDB_API_TOKEN` from `~/.maludb.token` into `/etc/business-os/runner.env` — the same token as
  `config/.env`; `ANTHROPIC_API_KEY` and `OPENROUTER_API_KEY` go there and nowhere else.
- **§10.2** needs a real model id and today's prices; **§10.1** prints the super-admin's generated password once,
  for the owner to store — not to be repeated in a summary.

---

## 8. The default applications (§12)

Run **§12** as written. It installs HR, Projects, Help Desk and Spaces from GitHub, each at `/srv/apps/<key>` with
its own database, vhost `<label>.$DOMAIN`, units and agents, and adds each name to `/etc/hosts` when it does not
resolve yet.

```bash
cd /var/www && php bin/app_install.php plan https://github.com/maludb/maludb-os-hr.git --by "$ADMIN_EMAIL" --domain "$DOMAIN"
sudo bin/install_default_applications.sh --by "$ADMIN_EMAIL" --domain "$DOMAIN" --scheme https
sudo -u postgres psql -d maludb_os -Atc "select app_key||' '||status from applications where app_key is not null order by id"   # hr, projects, helpdesk, spaces
```

---

## 9. Proof, clean-up, and the DNS reminder again (§13)

Run **§13**'s checks. Then:

```bash
shred -u ~/.pw.* ~/.mem.pw ~/.maludb.token          # once every env file holds its value
for n in "" app. os. hr. helpdesk. spaces. projects.; do printf '%-28s %s\n' "$n$DOMAIN" "$(dig +short "$n$DOMAIN" A | head -1)"; done
```

Close with a report the owner can act on, in this order:

1. Where the previous application went (`/var/www-previous-<date>`, and the two Apache copies).
2. The DNS table from §1 with the current A record beside each name, and the host's public address: any name
   still empty or pointing elsewhere is owed by the owner, with TLS at the proxy in front.
3. The super-admin's sign-in address (`https://app.$DOMAIN`) and that the password was shown once in **§10.1**.
4. What was left unset from the interview (keys, MaluMail, the embedder) and the command that sets each.
5. What stays the owner's — **§14** of `install.md`: DNS and TLS, provider keys and budgets, backups of
   `maludb_os`, the tenant's memory database and every application database.

---

## Appendix — the differences from `install.md`, on one page

| `install.md` | On a MaluDB hosting VM |
|---|---|
| §0 the owner's answers | §1 here: the same answers, asked as an interview, plus the DNS reminder with seven names |
| §1.1 MaluDB core and PostgreSQL 17 | **Skip.** Present; hosting owns them. Verified by §2 here. |
| §1.2 Apache, PHP, Composer, Node | Run only for what §2's survey finds missing |
| §2.1 the MaluDB API | Run only if nothing answers on :8000 |
| §2.2 `maludb_os_memory` / `maludb_os_mem` | **Replaced**: the tenant's database and memory schema from the existing application's configuration (§3 here) |
| §2.3 the memory token | Minted against the tenant's database and role (§5 here) |
| §3 clone to `/var/www` | After moving the existing application to `/var/www-previous-<date>` (§4 here) |
| §4 the `maludb_os` database | As written: a new database beside the tenant's |
| §5 `config/.env` | `MALUDB_MEMORY_DB/USER/PASSWORD` are the tenant's; the rest as written |
| §6 Apache | As written, after copying the previous default site and `ports.conf` aside |
| §7–§14 | As written |
