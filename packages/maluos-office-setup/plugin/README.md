# maluos-office-setup

A Claude Code plugin that configures a freshly installed **MaluOS office** (the server that runs the
MaluDB Business OS kernel) after first boot and SSH access: the handbook's stage 1c
(`10-office-configuration.md`) as an interview instead of hand edits.

It asks for the deployment topology, the business domain, the first administrator and the applications;
previews and writes `/etc/maluos/firstboot.yaml`; re-provisions the kernel; points the office's names at
the TLS proxy; renders the proxy's nginx blocks; hands over the first browser sign-in; takes provider
keys through a prompt the operator answers in their own terminal; installs the QEMU guest agent on a VM;
and ends with one topology-aware summary that declares completion only when every check passes.

## Install on the office

**From the MaluOS package** (the `maluos-office-setup` package, in the `maluos-business-os` metapackage
from the release after 26.04.20261106; before that, from the repository once published, or the deb in
`dist/` for a test):

```bash
sudo apt install maluos-office-setup        # or: sudo apt install ./maluos-office-setup_0.1.0_all.deb
maluctl office-setup                        # installs Claude Code for you if missing, starts /office-setup
```

The package puts the plugin under `/usr/share/maluos/claude-plugins/maluos-office-setup` with a local
marketplace beside it, the sudoers rule that lets members of `sudo` run exactly the plugin's scripts as
root without a password (Claude Code's shell cannot answer a sudo prompt), the launcher
`/usr/bin/maluos-office-setup` and `maluctl office-setup run|shell|check|status|providers` (`check`,
`status` and `providers` run the scripts without Claude). The package source is
`packages/maluos-office-setup` in the `maluos` repository; `scripts/vendor-maluos-office-setup.sh` there
refreshes the vendored plugin.

**From a checkout**, as the operator (`maluos`), in a tmux session over SSH:

```bash
git clone https://github.com/maludb/maluos-office-setup && maluos-office-setup/bootstrap.sh
maluos-office-setup
```

`bootstrap.sh` installs Claude Code for the user with Anthropic's native installer when it is missing,
copies the plugin root-owned to `/usr/local/share/maluos/claude-plugins/maluos-office-setup` (or uses the
package's copy when present), offers the same sudoers rule, and links `/usr/local/bin/maluos-office-setup`.
Without git: `curl -fsSL https://raw.githubusercontent.com/maludb/maluos-office-setup/main/bootstrap.sh | bash`.

Either way the first start signs you in to Claude Code (a URL to open on your workstation and a code to
paste back, or an API key). The scripts do the privileged work; Claude asks the questions, runs the
scripts, reads their output and explains. In any Claude Code the plugin also installs from its own
marketplace (`/plugin marketplace add maludb/maluos-office-setup`, then
`/plugin install maluos-office-setup@maluos-office-setup`) or from the package's local one
(`/plugin marketplace add /usr/share/maluos/claude-plugins`); the scripts still have to run on the office.

## Skills

| Skill | What it does |
|---|---|
| `/office-setup` | The interview: preflight, topology, domain and administrator, preview and apply, provision, the names, the proxy's blocks, the first sign-in hand-off, provider keys, VM integration, summary. Resumable: it detects what is already in place |
| `/office-providers` | The provider keys alone (Anthropic, OpenRouter, MaluMail, OpenAI), entered by the operator in their own terminal, confirmed through the runner's health |
| `/office-check` | The state report and the live checks, changing nothing |
| `/office-website` | The public page at the bare name: the starter from first boot (Bootstrap 5.3 + htmx) turned into the business's own on a working copy, shown, then published |

## Scripts (`scripts/`)

Each is one step, idempotent, and elevates itself with `sudo -n` when it needs root.

| Script | Step |
|---|---|
| `preflight.py` | the office's state as JSON, readable (`--human`) or as the completion report (`--report`) |
| `configure-kernel.py` | sets `components.maludb-os-core` in `firstboot.yaml` line by line (comments kept, duplicates removed, PyYAML validation, timestamped backup); `--preview`, `--apply`, `--show` |
| `provision.sh` | `maluctl provision --force` with the log kept and the kernel component's journal on failure; then `maluctl status` |
| `verify.sh` | PASS/FAIL checks for the chosen scheme; `--external` tests the names as a client |
| `hosts-proxy.sh` | on releases before `proxy_address` (maluos-firstboot 0.1.16), the marked `/etc/hosts` block that points the office's names at the proxy |
| `proxy-config.sh` | renders the proxy's nginx server blocks from `maluctl app names` (or the four kernel names) |
| `set-provider-key.sh` | a provider key through a no-echo prompt or a mode-600 file; probes where possible; restarts the unit; `--status` |
| `landing-site.sh` | the public page: `status`, `checkout DIR` (a working copy), `publish DIR` (checked, the live page backed up and replaced), `restore` |
| `vm-guest.sh` | the QEMU guest agent on a KVM/QEMU guest; nothing elsewhere |

## What it refuses or leaves to the operator

- Direct TLS on the office (a dedicated public IP with no proxy): not supported in this release. The
  skill says so and offers the proxy or the private-network topology.
- Anything on the proxy host or the LAN DNS: the plugin renders the configuration and tests the result;
  the operator installs it.
- Secrets: the generated administrator password and provider keys are never displayed or accepted in
  the conversation. The operator reads the password with `sudo cat` and types keys into
  `set-provider-key.sh` themselves.
- The browser sign-in and password change: confirmed by the operator, not verified in the database.

## Compatibility

Written against MaluOS 26.04.20261102 and 26.04.20261106 (maluos-firstboot 0.1.15 and 0.1.16,
maludb-os-core at db/193). The scripts detect whether the kernel's component knows `proxy_address` and
`apps.install` and adapt. Nothing here replaces the first-boot component or `maluctl`; the plugin drives
them.

## Development

The plugin lives in the handbook repository under `plugins/maluos-office-setup/` until it moves to its
own repository (`maludb/maluos-office-setup`, the path the README and `bootstrap.sh` assume). To try it
from a checkout on an office: `bootstrap.sh` from the checkout installs that copy. To load it in any
Claude Code without installing: `claude --plugin-dir plugins/maluos-office-setup`.

`configure-kernel.py` can be exercised anywhere against a copy of the shipped `firstboot.yaml` with
`--file`; the other scripts expect an office.

`packaging/build-deb-without-dpkg.py --maluos <maluos checkout>` assembles the Debian package from
`packages/maluos-office-setup` on a machine without Debian tooling (control, md5sums, postinst, the data
tree with the modes `debian/rules` sets, the `/usr/bin` link) into `dist/`, for a test install with
`apt install ./…deb`. The canonical build is `scripts/build-packages.sh` in the `maluos` repository.
