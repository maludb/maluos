---
name: office-providers
description: Give a MaluOS office its model and mail provider keys (Anthropic for Claude agents, OpenRouter for JEV, MaluMail for invitations, optionally OpenAI for embeddings) through a protected prompt the operator answers in their own terminal, then confirm what each key enabled. Use when the user says "set the API keys", "add the Anthropic key", "agents can't run", "invitations don't send", "provider keys", or invokes /office-providers. Never accepts a key in the conversation.
---

# Office providers: the keys, without ever seeing one

The office's agent runner reads provider keys from `/etc/business-os/runner.env` (root:bos-runner,
640); the kernel reads the mail key from `/var/www/config/.env`. Keys are set with
`${CLAUDE_PLUGIN_ROOT}/scripts/set-provider-key.sh`, which prompts with echo off **in the operator's
terminal**, writes the file in place (owner and mode kept, backup beside it), restarts the right unit
and probes. You run only its `--status` form.

## Rules

- You never receive, display or store a key. If one is pasted into the chat, say it is now in the
  transcript and should be rotated; do not write it anywhere.
- Do not read `runner.env`, `config/.env` or anything under `/var/lib/maluos/secrets`.
- Deferring a key is a valid outcome. Say what stays unavailable.

## Steps

1. State:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/scripts/set-provider-key.sh --status
   ```
   If the files are not readable as the operator, run it with `sudo` (the sudoers rule covers it).
   Report which keys are set (never values) and the runner's harnesses.

2. Explain, briefly, what each key enables:

   | Key | Enables | Without it |
   |---|---|---|
   | Anthropic | every Claude agent (the installer agent, the application experts, the kernel's harness `claude_agent_sdk`) | no Claude agent can run |
   | OpenRouter | JEV: the eval grader and the two `system_one` agents | evaluations and those agents unavailable |
   | MaluMail (+ `MAIL_FROM`) | invitations and notifications by mail | invitations print a link (`php bin/invitation_link.php <id>` in `/var/www`) |
   | OpenAI (optional) | also usable as MaluDB's embedding model for memory, set before memory accumulates | ranking inside memory results stays hash-based |
   | DeepSeek, Moonshot, Fireworks (optional) | other runner providers | nothing lost |

3. For each key the operator wants to set now, give the exact command to run **in their own terminal**
   (a second SSH session or after suspending this one):
   ```bash
   sudo ${CLAUDE_PLUGIN_ROOT}/scripts/set-provider-key.sh anthropic
   sudo ${CLAUDE_PLUGIN_ROOT}/scripts/set-provider-key.sh openrouter
   sudo ${CLAUDE_PLUGIN_ROOT}/scripts/set-provider-key.sh malumail --mail-from "no-reply@<domain>"
   sudo ${CLAUDE_PLUGIN_ROOT}/scripts/set-provider-key.sh openai
   ```
   A key kept in a file with mode 600 can be given with `--from-file /path`. Wait for "done".

4. Confirm with `--status` again. For Anthropic and OpenRouter the runner's `harnesses` list is the
   evidence; for MaluMail, suggest sending one test invitation from `os.<domain>`. For OpenAI as the
   embedder, point to `sudo -u www-data php /var/www/bin/maludb_set_embedder.php --check` and
   `--key-file`.

5. Report: set, deferred, and what remains unavailable. If a probe refused a key, the script changed
   nothing; say so and let the operator retry.
