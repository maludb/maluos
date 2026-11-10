# When a check fails

| Symptom | Likely cause | What to do |
|---|---|---|
| `maluos-firstboot` SubState `running` for a long time | first boot still provisioning (the applications step clones and builds; minutes each) | wait; `sudo journalctl -u maluos-firstboot -f`. Never run `provision.sh` meanwhile |
| `provision.sh` fails in `maludb-os-core` | the journal names the step: a migration, Apache configtest, the PHP API not becoming healthy, github.com unreachable for an application | fix the named thing (`sudo journalctl -u maluos-firstboot \| grep -i maludb-os-core \| tail -20`), run `provision.sh` again; every step resumes |
| `APP_URL` wrong after apply | provision not run after the edit, or a YAML error (the component read the old file) | `configure-kernel.py --show`, then `provision.sh` |
| `app.$DOMAIN` resolves to `127.0.0.1` under https | the component predates `proxy_address` (before 0.1.16) and wrote loopback lines | `hosts-proxy.sh --domain D --proxy-address P` |
| `app.$DOMAIN` resolves to nothing | no hosts line and no DNS for the name on the office | https: `hosts-proxy.sh`; http: `provision.sh` writes the loopback line |
| sign-in page by Host header is not 200 | Apache vhost not rendered for the domain, or `maludb-os-web` down | `systemctl status apache2 maludb-os-web`; `sudo apache2ctl -S`; `provision.sh` |
| `--external` gives 502 | the proxy answered but could not reach the upstream | on the proxy: upstream address and port (the office on :80), firewall between proxy and office |
| `--external` gives 000 | no route, DNS not pointing at the proxy from here, or TLS failure (certificate does not cover the name) | `getent hosts app.$DOMAIN` on the office should be the proxy; `curl -vk https://app.$DOMAIN/login` to see the TLS step; the proxy's certificate SANs |
| the generated password is refused at the sign-in page | under http: the kernel marked its session cookie Secure, the browser dropped it and every sign-in failed (maludb-os-core before 2026.11.09maluos2). Otherwise: the password was changed after first boot (the file keeps the first one), five failed attempts in 15 minutes, or the email is not the configured administrator's | `admin-login.py --check` names which; `admin-login.py --reset` sets a new generated password and clears the failed attempts |
| `claude: command not found` after the setup | the shell was opened before Claude Code was installed in `~/.local/bin` | open a new terminal, or `export PATH="$HOME/.local/bin:$PATH"`; `maluctl office-setup shell` always finds it |
| sign-in loops back to the login page through the proxy | the proxy does not send `X-Forwarded-Proto https`, so the kernel sets a secure cookie the browser drops, or the `Host` header is rewritten | the rendered `proxy-config.sh` block has both headers; compare with the proxy's actual block |
| the launcher opens but an application tile fails health | stage 2 matter: the application's units, or the office cannot reach its own application name (https without the names pointed at the proxy) | `hosts-proxy.sh` refreshes the block with the installed applications' names; then 12-applications.md §4 |
| `set-provider-key.sh` says "no terminal to prompt on" | it was run from the coding agent's shell | the operator runs it in their own terminal, or `--from-file` with a mode-600 file |
| runner `harnesses` does not list Claude after the Anthropic key | the runner did not restart, or the key was written to the wrong file | `systemctl status maludb-os-agent-runner`; `set-provider-key.sh --status`; `sudo journalctl -u maludb-os-agent-runner -n 30` |
| `sudo -n` refused inside the scripts | no sudoers rule for the plugin's scripts | `bootstrap.sh --sudoers`, or run the script with `sudo` in the operator's terminal |
| `qemu-guest-agent` installs but Proxmox shows no address | the VM's "QEMU Guest Agent" option is off on the hypervisor side | enable it in the VM's Options and restart the VM when convenient |

Where things are: the provisioning logs under `/var/log/maluos-office-setup/`, the first-boot
state in `/var/lib/maluos/firstboot/done`, backups of edited files beside them with a
`.before-office-setup-<timestamp>` suffix (mode 600).
