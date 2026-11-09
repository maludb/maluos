# What the kernel's first-boot component reads

`/etc/maluos/firstboot.yaml`, `components.maludb-os-core`. The component is
`/usr/lib/maluos/components/60-maludb-os-core.py`, shipped by the `maludb-os-core` package and run by
`maluos-firstboot.service` on first boot and by `sudo maluctl provision --force` afterwards. Every step
is idempotent. The summary it returns lands in `/var/lib/maluos/firstboot/done` and in `maluctl status`.

| Key | Meaning | Set by |
|---|---|---|
| `enabled` | provision the kernel at all (the shipped file has `false` on newer images, `true` with `maluos.local` on 26.04.20261102) | `configure-kernel.py` (always `true`) |
| `domain` | the business domain; names `<domain>`, `www.`, `os.`, `app.` and `<label>.<domain>` per application | `configure-kernel.py --domain` |
| `scheme` | `http` on a LAN, `https` behind a TLS proxy; becomes `APP_URL`, the login URL and the cookie policy | `--scheme` |
| `proxy_address` | (0.1.16 and later) the TLS proxy as the office reaches it; the component writes the kernel's and every installed application's names to it in a marked `/etc/hosts` block and removes them from loopback | `--proxy-address`; `hosts-proxy.sh` emulates it on older releases |
| `admin_email`, `admin_name` | the first super-admin; created if no member has that email yet | `--admin-email`, `--admin-name` |
| `admin_password` | optional; otherwise generated once and kept in `/var/lib/maluos/secrets/business-os/admin-password` (root, 600) | never by this plugin |
| `model_key`, `model_name`, `model_provider_id` | the first model registry row (default `claude-fable-5-1`) | not asked; defaults |
| `anthropic_api_key`, `openrouter_api_key`, `malumail_api_key` | copied into `runner.env` / `config/.env` at provisioning | never by this plugin: `set-provider-key.sh` writes the env files directly, so a key never sits in a YAML file |
| `apps.install` | (0.1.15 and later) the applications the kernel's installer clones and installs at provisioning, in order (HR first); `[]` none; absent: the four defaults | `--apps` |
| `apps.ref`, `apps.propose_agents` | per-key git ref; keys whose agents are proposed rather than hired | not asked; edit by hand if needed |

## What the component writes

| Where | What |
|---|---|
| `/etc/hosts` | loopback lines for the four kernel names (and the proxy block under `proxy_address`) |
| `/var/www/config/.env` | `APP_URL`, `OS_HOST`, `APP_HOST`, `SESSION_COOKIE_DOMAIN`, database and MCP credentials, `MAIL_FROM`, `MALUMAIL_API_KEY` if given; root:www-data 640 |
| `/var/www/web/.env.local` | the Next.js front end's `LOGIN_URL` and internal key |
| `/etc/business-os/runner.env` | the agent runner's database credentials and provider keys; root:bos-runner 640 |
| `/etc/apache2/sites-available/maludb-os.conf` | the kernel's vhosts for the domain |
| `/var/lib/maluos/secrets/business-os/` | generated passwords and keys (600), the MaluDB API token |
| `/var/lib/maluos/business-os/` | the migration ledger, agent-hire markers, application markers and logs |
| the databases `maludb_os`, `maludb_os_memory` | created once; migrations applied from the ledger; kept across re-provisions |

Units the kernel runs: `apache2`, `maludb-api`, `maludb-os-web`, `maludb-os-records-mcp`,
`maludb-os-activity-mcp`, `maludb-os-actions-mcp`, `maludb-os-memory-mcp`, `maludb-os-agent-runner`,
`maludb-os-activity-ingest.timer`. Health: `http://127.0.0.1:8080/api/v1/health` (the kernel's PHP API),
`http://127.0.0.1:8815/health` (the runner; `.harnesses` lists the harnesses with a key).
