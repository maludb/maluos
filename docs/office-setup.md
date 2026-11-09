# The office set up by Claude Code: maluos-office-setup

Written 2026-11-09 for maluos PR #6 (the owner's packaging of the handbook's
plugin, github.com/maludb/maluos-docs#1). It records what the package does,
how it reaches an office, what it leaves to the operator, and what the next
build has to decide. The plugin itself lives in the handbook repository
until it has its own (`github.com/maludb/maluos-office-setup`, the path the
package's metadata already names); this repository vendors it.

## What it is

After an office is installed from the server ISO, first boot provisions the
Business OS kernel for the placeholder domain `maluos.local` unless the
installer's First boot screen or an install plan gave it a real one
(docs/install-plan.md). The rest of the handbook's stage 1 was hand work
over SSH: the domain and the scheme, `proxy_address`, the first
administrator, `maluctl provision --force`, the proxy's nginx blocks, the
first sign-in, the provider keys, the guest agent. `maluos-office-setup`
turns that into an interview run by Claude Code on the office:

```
ssh maluos@office
tmux new -s office
maluctl office-setup            # installs Claude Code for the operator if missing, starts /office-setup
```

The first start signs the operator in to Claude Code (a URL to open on their
workstation and a code to paste back, or an API key). The skill then asks
its questions one at a time, previews every change, runs the plugin's
scripts, reads their output and reports. It is resumable: every phase
derives its state from the system, so a second run offers to continue from
the first incomplete phase or to check a finished office.

## What the package installs

| Path | What |
|---|---|
| `/usr/share/maluos/claude-plugins/maluos-office-setup/` | the plugin, root-owned: `.claude-plugin/plugin.json`, three skills, eight scripts, the references, `bootstrap.sh` (for a checkout install), `README.md`, `VENDORED` |
| `/usr/share/maluos/claude-plugins/.claude-plugin/marketplace.json` | a local marketplace named `maluos`: `/plugin marketplace add /usr/share/maluos/claude-plugins` in any Claude Code; later plugins land beside this one |
| `/etc/sudoers.d/maluos-office-setup` (mode 440, `visudo -c` in postinst) | `%sudo ALL=(root) NOPASSWD: <plugin>/scripts/*`: members of `sudo`, who already have full sudo, run exactly the plugin's scripts without a password, because Claude Code's shell has no terminal for sudo's prompt; the scripts are the whole privileged surface and live in a root-owned directory |
| `/usr/bin/maluos-office-setup` | the launcher: `claude --plugin-dir <plugin> /office-setup`, refuses to run as root |
| `/usr/lib/maluos/maluctl.d/office-setup.py` | `maluctl office-setup run\|shell\|check\|status\|providers` |

`maluctl office-setup` (or `run`) installs Claude Code for the calling user
with Anthropic's native installer (`https://claude.ai/install.sh`, into
`~/.local/bin`, as the desktop's Tools Installer does) when `claude` is not
on the path, then starts it with the plugin loaded and `/office-setup`
running. `shell` loads the plugin and starts no skill. `check`, `status`
and `providers` run the plugin's scripts without Claude: the completion
report, the readable state, a provider key through the protected prompt.

Depends: `maluos-firstboot (>= 0.1.15)`, `maludb-os-core`, `python3`,
`python3-yaml`, `curl`, `ca-certificates`, `sudo`, `iproute2`; Recommends
`tmux`. In `seeds/business-os.seed`, so `maluos-business-os` (maluos-meta
0.2.18) depends on it and every server image that carries the kernel
carries the plugin that configures it.

## The three skills

| Skill | Does | Changes the system |
|---|---|---|
| `/office-setup` | the interview, nine phases: preflight; the topology (A: an external HTTPS proxy, B: a private network over HTTP; C, TLS on the office itself, is refused in this release); the domain, the administrator and the applications; preview and apply of the kernel's block in `/etc/maluos/firstboot.yaml`; `maluctl provision --force`; the office's names; the proxy's nginx blocks rendered for the proxy's operator; the first sign-in hand-off; the provider keys; the QEMU guest agent; one topology-aware summary that declares completion only when every check passes | yes, through the scripts, after a preview and a yes |
| `/office-providers` | the provider keys alone: Anthropic (the Claude agents), OpenRouter (JEV), MaluMail (invitations), optionally OpenAI (embeddings), DeepSeek, Moonshot, Fireworks; each may be deferred | the env files, through `set-provider-key.sh` |
| `/office-check` | the state report and the live checks | nothing |

The rules every skill keeps: it runs on the office only (it stops when
`/etc/maluos/firstboot.yaml` is missing); it never displays or accepts a
secret (the generated administrator password is read by the operator with
`sudo cat`, provider keys are typed by the operator into the script's
no-echo prompt in their own terminal; a key pasted into the chat is declared
compromised); it detects rather than remembers; it previews, confirms, then
applies; it reports a failed phase as failed; it stays in stage 1 (the
applications beyond `apps.install`, the estate, the GPU node and the desks
are the handbook's later stages).

## The eight scripts

Each does one step, is idempotent, prints what it did, and elevates itself
with `sudo -n` when it needs root (the sudoers rule), or says how to run it
with sudo by hand.

| Script | Step | Reads and writes |
|---|---|---|
| `preflight.py` | the office's state as JSON, readable (`--human`) or as the completion report (`--report`, exit 1 when the chosen topology lacks anything) | reads firstboot.yaml and the done file, the units, the kernel's API, `/etc/hosts`, whether each key is set (never a value), `systemd-detect-virt`, the addresses |
| `configure-kernel.py` | the kernel's block in firstboot.yaml, line by line so comments survive: `--domain`, `--scheme`, `--proxy-address`, `--admin-email`, `--admin-name`, `--apps` (a list, `none`, `keep`); `--preview` (the block and a diff), `--apply` (a timestamped backup, an atomic write, PyYAML validation), `--show` | firstboot.yaml; never `admin_password` or a `*_api_key` |
| `provision.sh` | `maluctl provision --force` with the log kept under `/var/log/maluos-office-setup` and the kernel component's journal on failure, then `maluctl status` | what the first-boot components write |
| `verify.sh` | PASS/FAIL per line for the chosen scheme: the units, the API, the sign-in page by Host header, `APP_URL`, the done file, the office's own names (the proxy under https, loopback under http); `--external` tests the names as a client would | nothing |
| `hosts-proxy.sh` | on a release whose component does not know `proxy_address` (maluos-firstboot before 0.1.16): the office's names at the proxy in a marked `/etc/hosts` block, off every loopback line; `--remove` | `/etc/hosts` (a backup beside it) |
| `proxy-config.sh` | the proxy's nginx server blocks from `maluctl app names` (or the four kernel names): the kernel's names with long timeouts and no buffering, the applications' names, DocCloud with 512m uploads, http to https | a file for the proxy's operator; nothing installed anywhere |
| `set-provider-key.sh` | a provider key through a no-echo prompt on the operator's terminal or a mode-600 file (`--from-file`); probed on the provider's model listing where one exists; the env file written in place (owner and mode kept, a backup beside it); the unit restarted; `--status` says which keys are set | `/etc/business-os/runner.env` or `/var/www/config/.env` |
| `vm-guest.sh` | the QEMU guest agent on a KVM/QEMU guest; nothing on hardware or another hypervisor | apt |

What the scripts assume of this repository: the kernel component
(`packages/maludb-os-core/components/60-maludb-os-core.py`) and its keys
`proxy_address` (maluos-firstboot 0.1.16, docs/phase13-estate-behind-a-proxy.md)
and `apps.install` (0.1.15, docs/components.md); `maluctl provision --force`;
`maluctl app names`. They detect which of the two keys the installed
component supports and adapt (`hosts-proxy.sh` stands in for
`proxy_address` on 26.04.20261102); nothing in the component or in `maluctl`
changes for them.

## Two ways to the same office

An office can be given its configuration at install time or after it:

| | The installer's First boot screen, or an install plan | `maluctl office-setup` after first boot |
|---|---|---|
| when | at the install, before first boot (docs/install-plan.md, `firstboot.components.maludb-os-core`) | after the install, over SSH, as the operator |
| asks | the domain, the scheme, the proxy address, the administrator (the screen); everything the plan carries | the topology, the domain, the administrator, the proxy address and the office's upstream, the applications, the provider keys |
| does | writes firstboot.yaml; first boot provisions once | rewrites the kernel's block, re-provisions, renders the proxy's blocks, hands over the sign-in, takes the keys, installs the guest agent, reports |
| needs | nothing on the office | Claude Code signed in (an Anthropic account or key), network access to claude.ai from the office |

Both end in the same `firstboot.yaml` and the same `maluctl provision`. A
plan is the unattended path; the interview is the attended one, and it also
finishes an office whose plan said less than it should have.

## What stays the operator's

The proxy host and the LAN DNS (the plugin renders the configuration and
tests the result, the operator installs it); TLS on the office itself (not
supported in this release; the skill offers the proxy or the private
network instead); the browser sign-in and the password change (confirmed by
the operator, not read from the database); the provider keys themselves.

## Where it goes next

- The plugin's own repository (`maludb/maluos-office-setup`), after which
  `scripts/vendor-maluos-office-setup.sh REF` refreshes `plugin/` from it
  and `VENDORED` records the commit; today `VENDORED` names the handbook
  tree it was copied from (`ref: local`).
- Boot-test checks (`preflight.py --report` on a booted server image, the
  skill's scripts against the test VM's kernel): not written; the package
  has been built and lintian-checked here and installs its files with the
  intended modes, but no office has run the interview from the package yet.
- Claude Code on the image: the package installs Claude Code per user, on
  first use, from Anthropic's installer, so the ISO needs no Claude Code
  binary; whether the next build should instead carry it, and whether the
  desktop's Tools Installer and this launcher should share one install
  path, is the owner's call for the next build.
- The second plugin for the marketplace: the estate's join and the GPU
  node's share (the handbook's 11-gpu-server.md and 13-estate.md) are the
  same shape of hand work.

## Status

2026-11-09: PR #6 reviewed, built with `scripts/build-packages.sh` (lintian
clean but for the no-manual-page warning every maluctl front end shares; the
sourced `lib.sh` overridden), `maluos-meta` 0.2.18 regenerated from the seed
so `maluos-business-os` depends on the package, and merged. Not yet on an
image or on apt.maluos.com: that is the next build's decision.
