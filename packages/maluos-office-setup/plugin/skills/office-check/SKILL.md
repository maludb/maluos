---
name: office-check
description: Report the state of a MaluOS office's Business OS configuration without changing anything - first boot, the kernel's domain and scheme, the names, services, health, which provider keys are set, the VM guest agent, and a topology-aware completion summary. Use when the user asks "is the office configured", "check the office", "office status", "what is still missing", or invokes /office-check.
---

# Office check: where does the office stand?

Read-only. Two commands, both from `${CLAUDE_PLUGIN_ROOT}/scripts/`:

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/preflight.py --human
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/preflight.py --report
```

(`sudo` so the root-only files are inspected; the script reports only whether a secret is set, never its
value. Without the sudoers rule run them without `sudo` and say which rows read "unknown".)

Then, when the kernel is configured for a domain, the live checks for its scheme:

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/verify.sh --domain <domain> --scheme <scheme> [--proxy-address <proxy>] [--external]
```

Use `--external` only when the operator says the proxy (https) or the LAN DNS (http) is in place; it
tests the names as a client would, from the office.

Present the report as it is, then one short paragraph: what is complete, what is not, and which
handbook document or skill handles each missing item (`/office-setup` for configuration, `/office-providers`
for keys, 12-applications.md for applications, 30-reverse-proxy.md for the proxy). Do not fix anything
from this skill; offer `/office-setup`, which detects the state and resumes.

Never display the generated administrator password or any key, and do not read
`/var/lib/maluos/secrets`, `runner.env` or `config/.env` yourself.
