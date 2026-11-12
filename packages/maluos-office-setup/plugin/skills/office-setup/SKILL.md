---
name: office-setup
description: Configure a freshly installed MaluOS office (the MaluDB Business OS kernel) after first boot and SSH access - the interview that asks for the deployment topology, business domain, first administrator and applications, then provisions the kernel, points its names at the proxy, hands over the first browser sign-in, takes provider keys and reports one topology-aware summary. Use when the user says "set up the office", "configure the Business OS", "office setup", "give the kernel its domain", or invokes /office-setup. Resumable; safe to run again on a configured office.
---

# Office setup: stage 1c of the MaluOS handbook

You are configuring **the office**: the MaluOS server that runs the Business OS kernel. The operator
installed MaluOS from the ISO, first boot provisioned a kernel for the placeholder domain
`maluos.local`, and they have a shell as the Linux user `maluos` with sudo. Your job is the handbook's
original steps 5 to 9 with questions instead of hand edits: the deployment topology, the domain and the
first administrator, the re-provision, the office's own names, the first sign-in, the provider keys, the
VM integration, and a summary that says what works and what was deferred.

Every change goes through a script in `${CLAUDE_PLUGIN_ROOT}/scripts/`. Each does one step, is
idempotent, prints what it did, and elevates itself with `sudo -n` (the plugin's sudoers rule). Run the
scripts; do not reproduce their work with `sed`, `tee` or hand-written YAML. Read
`references/topologies.md` before the topology question and `references/troubleshooting.md` when a
check fails. `references/firstboot-keys.md` says what the kernel's component reads.

## Rules that hold throughout

- **This runs on the office.** If `/etc/maluos/firstboot.yaml` is missing, stop: tell the operator to run
  `maluos-office-setup` on the office over SSH (in tmux), not on their workstation.
- **Never display a secret.** Not the generated admin password, not a provider key, not the contents of
  `/var/lib/maluos/secrets`, `runner.env` or `config/.env`. Tell the operator the path and the command
  to read it themselves. Provider keys are typed by the operator into `set-provider-key.sh` in their
  own terminal; you never receive one. If the operator pastes a key into the chat, say that it is now
  in the transcript and should be rotated, and do not put it anywhere.
- **Detect, don't remember.** Every phase derives its state from the system (`preflight.py`). On a
  re-run, report what is already in place and offer to continue from the first incomplete phase.
- **Preview, confirm, apply.** Show the configuration block and the diff before writing
  `firstboot.yaml`; provision only after the operator says yes to the preview.
- **Ask, don't assume**, for every input in the table below. Validate as the scripts do; the scripts
  refuse bad values, so show their error and ask again.
- **Long commands run with a long timeout** (provisioning: 10 minutes or more with applications). Run
  `provision.sh` in the foreground with a 600000 ms timeout; if it is still running, say so and wait
  rather than starting it again (`maluctl provision` must not run twice at once).
- **Report failures as failures.** A phase that did not pass is not "done with a caveat". The final
  summary comes from `preflight.py --report` and declares completion only when it finds no failure.
- **Stay in scope.** Applications beyond the first-boot `apps.install` list, the estate, the GPU node
  and desks are later stages (12-applications.md, 13-estate.md, 14-desks.md). Point there; do not start them.

## Inputs you will ask for

| Input | Ask | Validation | Used by |
|---|---|---|---|
| Topology | A: external HTTPS proxy, B: private network over HTTP, C: direct TLS on the office (not supported, see below) | one of A/B | everything below |
| Where the data lives | this server's own PostgreSQL (the default), or a MaluOS database server (one installed with `role: database-server`) | for a database server: its name on the LAN, and the two files its `maluctl db export` wrote | `database-server.py` |
| Business domain | `example.com`, no scheme, no `www`, no path | lowercase labels with a dot | `--domain` |
| Administrator email and display name | the Business OS super-admin; not the Linux user `maluos` | an email; a one-line name | `--admin-email`, `--admin-name` |
| Proxy address (A only) | the TLS proxy's address **as the office reaches it** (LAN address, e.g. `192.168.100.1`) | IPv4 or hostname, not loopback | `--proxy-address` |
| Office upstream (A only) | the office's address **as the proxy reaches it** (preflight lists the office's addresses) and the port the proxy should use (80) | an address the operator confirms stable (DHCP reservation or static) | `proxy-config.sh --upstream` |
| Certificate paths (A only, optional) | where the proxy keeps the certificate and key for `$DOMAIN` and its subdomains | paths; default Let's Encrypt layout | `proxy-config.sh --cert/--key` |
| Applications at first boot | on a release whose component supports `apps.install`: install `hr, projects, helpdesk, spaces` (and `doccloud`) now, or defer to stage 2 | catalog keys | `--apps` |
| Provider keys | Anthropic (Claude agents), OpenRouter (JEV), MaluMail (invitations), optionally OpenAI (embeddings); each may be deferred | typed by the operator into the script | `set-provider-key.sh` |

Ask with one question per message (AskUserQuestion where the choice is from a list), and restate the
collected answers in a table before the preview.

## Phase 0: preflight

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/preflight.py --human
```

Read the assessment line and act on it:

- `on_office=False`: stop (see the rules).
- `firstboot_running=True`: first boot has not finished. Do not change anything. Show
  `systemctl show -p SubState --value maluos-firstboot` and the journal tail, wait, and re-run preflight.
- `firstboot_failed_components` not empty: show each failure, and for `maludb-os-core` show
  `sudo journalctl -u maluos-firstboot --no-pager | grep -i maludb-os-core | tail -20`. Explain that
  every step is idempotent and `provision.sh` resumes after the fix. If the failure is in another
  component, the kernel's configuration can still proceed, but say the component stays failed.
- `domain_chosen=True`: the office is already configured for a domain. Summarize what is in place and
  ask whether to **check** (go to Phase 9), **change** the configuration (continue from Phase 1 with the
  current values offered as defaults), or **continue** from the first phase whose assessment is false.
- If `application-server.py --show` says this server is configured as an application server, or the
  operator says this server is to run applications for a kernel on another server, this skill's kernel
  phases do not apply: follow `references/application-server.md`, "On an application server".
- The `data:` line says where this server keeps its data and what first boot provisioned against.
  If it says `THIS HOST IS A DATABASE SERVER`, stop: a database server runs no kernel and this skill
  has nothing to configure on it (its own steps are in `references/database-server.md`).
- Note `component.supports_proxy_address` and `supports_apps`: they decide Phase 4 and the applications
  question. Note `virt.type` for Phase 8.
- On the 26.04.20261102 ISO (`maluos-firstboot` below 0.1.16) `proxy_address` is not native: say so once;
  the plan uses `hosts-proxy.sh` instead and the key is still written for the next release's upgrade.

Before Phase 1, back the configuration up once (the apply step also keeps a timestamped backup):

```bash
sudo cp -a /etc/maluos/firstboot.yaml /etc/maluos/firstboot.yaml.before-office-setup 2>/dev/null || true
```

## Phase 1: topology

Explain the three choices in two sentences each (from `references/topologies.md`) and ask. If the
operator chooses C (TLS on the office itself, dedicated public IP without a proxy): say plainly that
this plugin does not configure it (no certificate issuance or listener on the office exists in this
release); offer A (put a TLS proxy in front, on the LAN or on the same host as a separate service) or B
(HTTP on a private network), and record the choice in the summary as "direct TLS requested, not
supported". Do not configure https without a proxy.

## Phase 1b: where the data lives

Ask whether this server keeps its data in **its own PostgreSQL** (one server does everything: the
default, and nothing to do in this phase) or on a **MaluOS database server** (a separate machine
installed with `role: database-server`; this server then runs the kernel and the applications and
holds no database). Read `references/database-server.md` before answering questions about it.

If preflight's `data:` line already names a database server (it was given at install time, in the plan
or the installer's Database group), say so and only run the check below against the configured values.

For a database server, collect:

1. Its **name as this server resolves it on the LAN** (not an address typed from memory, and not the
   estate's overlay name ending in `.internal`: an office cannot reach its own database over the
   overlay). The name must be one the server's certificate carries.
2. The paths **on this server** of `db-admin.txt` and `db-ca.pem`, which `sudo maluctl db export DIR`
   on the database server wrote and the operator copied here (for example with `scp`). Never read,
   print or copy `db-admin.txt` yourself: it is the admin role's password. Refer to it by path only.

Check before writing anything:

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/database-server.py --check --host <name> --credential <path>/db-admin.txt --ca <path>/db-ca.pem
```

Show its lines as they are. On a FAIL its NOTE says which side to fix (the name is not in the
certificate: `database_server.names` on the database server; this server's address is not admitted:
`database_server.clients` there; a wrong password; nothing listening). Those fixes are made on the
database server by its operator; wait and run the check again. Do not continue past a failed check and
do not fall back to the local cluster without asking.

When it passes:

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/database-server.py --apply --host <name> --credential <path>/db-admin.txt --ca <path>/db-ca.pem
```

If it refuses because the kernel was already provisioned on this server's own cluster, explain what
`--data-not-moved` means (the next provisioning starts empty on the database server: a new kernel
database, a new administrator password, nothing carried over) and add the flag only when the operator
says this server holds nothing to keep. An office with real data is not moved by this skill.

Provisioning (Phase 4) then creates this server's databases and roles on the database server. The two
files must stay where they are until Phase 4 has run once.

## Phase 2: the domain, the administrator, the applications

Ask for each input of the table that the topology needs. For the applications: if
`supports_apps=False`, do not ask; say stage 2 installs them. Otherwise ask whether to install the four
defaults now (adds several minutes of cloning and building; needs network access to github.com from
the office), add `doccloud`, or defer (`--apps none`). Offer "keep" when the file already lists them.

## Phase 3: preview and apply

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/configure-kernel.py --domain "$DOMAIN" --scheme https --proxy-address "$PROXY" \
  --admin-email "$ADMIN_EMAIL" --admin-name "$ADMIN_NAME" --apps hr,projects,helpdesk,spaces --preview
```

(`--scheme http` and no `--proxy-address` for topology B; `--apps none` to defer; `--apps keep` to
leave the list as it is.) Show the resulting block and the diff to the operator and ask for a yes. Then
the same command with `--apply`. The script backs the file up, writes atomically and refuses a result
that does not read back as intended.

## Phase 4: provision

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/provision.sh
```

Explain first what it does: every first-boot component re-runs; the kernel's environment files, vhosts
and hosts lines are re-rendered for the domain; databases, secrets and hired agents are kept; the
super-admin with the new email is created if no member has it. On the reference ISO two harmless
leftovers remain: the `maluos.local` hosts lines and the first super-admin `admin@maluos.local`, which
the operator can retire from `os.$DOMAIN` later (the same generated password opens both until changed).

Then:

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/verify.sh --domain "$DOMAIN" --scheme https --proxy-address "$PROXY"
```

Under topology A on a release without native `proxy_address`, the self-resolution check fails here by
design; fix it now:

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/hosts-proxy.sh --domain "$DOMAIN" --proxy-address "$PROXY"
```

and run `verify.sh` again. Under topology B the names must resolve to loopback on the office; first boot
writes that line. Any other FAIL: `references/troubleshooting.md`, fix, re-run; do not continue past a
failing kernel.

## Phase 5: the names outside the office

**Topology A.** Render the proxy's server blocks and hand them over:

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/proxy-config.sh --domain "$DOMAIN" --upstream "$OFFICE_ADDR" --out ~/office-nginx-$DOMAIN.conf
```

Tell the operator: install this on the proxy (the file's header says what to adjust), make sure the
LAN DNS resolves every listed name to the proxy for the desks and that the proxy's certificates cover
them, reload nginx, then say "done". Then, from the office:

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/verify.sh --domain "$DOMAIN" --scheme https --proxy-address "$PROXY" --external
```

A 502 means the proxy was reached but could not serve its upstream: the upstream address or port on
the proxy. A connection or TLS error is a route, DNS or certificate problem on the proxy side. Report
them as the proxy operator's items; the office side is done when the non-external checks pass.

**Topology B.** Nothing to render. Say that the LAN's DNS (or each client's hosts file, as a stopgap)
must resolve the four kernel names and each application name to the office's address, which must be
stable (DHCP reservation or static). Give the operator the check to run from a second LAN machine:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://app.$DOMAIN/login     # 200
```

and record "LAN DNS: operator-confirmed" or "not yet" in the summary accordingly.

## Phase 6: the first sign-in

First prove on the office that the sign-in can work, without seeing the password:

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/admin-login.py --check
```

It checks the administrator's member record, the stored password against it, the sign-in throttle, the
session cookie for the scheme, and makes one real sign-in against the kernel. Do not hand over while a
line says FAIL: show the line and act on it (a wrong `APP_URL`: `provision.sh`; a Secure cookie under
http: update `maludb-os-core`, or use https; a stored password that is not the member's:
`admin-login.py --reset`, with the operator's consent, which sets a new generated password and stores
it in the same root-only file).

Then give the hand-off without revealing anything:

- URL: `https://app.$DOMAIN` (or `http://` under B).
- Sign-in name: write out the administrator's email in full, exactly as configured (`$ADMIN_EMAIL`). Say
  plainly that this is the name to type: not `admin`, not the Linux user `maluos`, not another address
  of theirs. A correct password under another email is refused with the same message as a wrong one.
- Password: generated at provisioning and kept root-only in
  `/var/lib/maluos/secrets/business-os/admin-password`. The operator reads it in their own terminal:
  `sudo cat /var/lib/maluos/secrets/business-os/admin-password`. Do not run that command yourself.
- The launcher shows the built-ins and (if installed at first boot) the applications; `https://os.$DOMAIN`
  opens the operating system; Settings → Estate is empty at this stage.
- Change the password now on the profile page. The file keeps the old one; that is expected.
- The Linux `maluos` password and this Business OS password are different credentials.

Ask the operator to confirm the sign-in and the password change, and record their answer (do not
verify it by reading the database). If they say the password is refused, first ask which email they
typed and compare it with `$ADMIN_EMAIL` (the commonest cause), then run `admin-login.py --check`
again and read its lines to them (a NOTE counts the sign-ins tried under an email no member has): when every line passes, the cause is between their browser and the
office (the name's DNS, the proxy's server block, `http` typed where the office is `https` or the
reverse), not the password; `admin-login.py --reset` is for a stored password that no longer matches.

Claude Code itself: `maluctl office-setup` installed it in `~/.local/bin`. Tell the operator that a new
terminal finds `claude`, and that `maluctl office-setup shell` always starts it with this plugin.

## Phase 7: provider keys

Explain what each key enables and what stays unavailable without it (Anthropic: no Claude agent
runs; OpenRouter: no JEV grading or `system_one` agents; MaluMail: invitations print a link instead of
sending mail; OpenAI: optional, the embedding model for memory, worth setting before memory accumulates).
For each key the operator has now, give them the command to run **in their own terminal**:

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/set-provider-key.sh anthropic
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/set-provider-key.sh openrouter
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/set-provider-key.sh malumail --mail-from "no-reply@$DOMAIN"
```

The script prompts with echo off, probes the key where the provider has a listing, writes the env file
in place (owner and mode kept, backup beside it), restarts the unit and reports the runner's harnesses.
When they say done, confirm with:

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/set-provider-key.sh --status
```

Deferring is a valid answer; the `/office-providers` skill does this phase alone later.

## Phase 8: VM integration

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/vm-guest.sh
```

Installs the QEMU guest agent on a KVM/QEMU guest (Proxmox then shows the address), does nothing on
physical hardware or another hypervisor, and says which.

## Phase 8b: application servers (only when the business separates them)

Ask whether applications will run on servers of their own. If not, skip this phase. If so, read
`references/application-server.md` and do "On the kernel server: admit the application servers": the
addresses, `configure-kernel.py --application-servers`, `provision.sh`, then the command that mints a
join code per server for the operator to run. The proxy's blocks (Phase 5) are rendered again once the
application servers have installed their applications, so each name gets its own upstream.

## Phase 9: the summary

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/preflight.py --report
```

Show the report as it is. Add the operator-confirmed items (browser sign-in, password changed, proxy
installed, LAN DNS) and the deferred items in your own words. If the report exits non-zero, the stage is
not complete: list what is missing and how to resume (`/office-setup` again, which detects the state).
When complete, the stable address, the domain and the names list are what stage 2 and the estate need;
say that the bare name shows a starter page until `/office-website` replaces it with the business's own; and
point to `12-applications.md` (or straight to `11-gpu-server.md` / `13-estate.md` when the applications
were installed at first boot).
