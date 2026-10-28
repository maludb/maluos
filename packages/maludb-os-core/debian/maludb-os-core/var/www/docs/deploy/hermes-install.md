# Installing the agent runtime on an office VM

What stage H2 put on this server, in order. Everything is idempotent.

```bash
# 1. Users. The runner may read its env file; the agent process may read neither secrets file.
sudo useradd --system --no-create-home --shell /usr/sbin/nologin bos-runner
sudo useradd --system --no-create-home --shell /usr/sbin/nologin bos-agent
sudo usermod -a -G bos-agent bos-runner
sudo install -d -o bos-runner -g bos-agent -m 2770 /var/lib/business-os /var/lib/business-os/agents

# 2. Hermes, pinned, root-owned, read-only. Bump the tag ONLY after the conformance suite passes on it.
sudo git clone --depth 1 --branch v2026.9.14 https://github.com/NousResearch/hermes-agent.git /opt/hermes/src   # 345cd2b0
sudo uv venv --python 3.12 /opt/hermes/venv
sudo uv pip install --python /opt/hermes/venv/bin/python -e '/opt/hermes/src[mcp,anthropic]'
sudo uv pip install --python /opt/hermes/venv/bin/python /var/www/mcp/bos_hermes        # a copy, not editable
sudo chmod -R go-w /opt/hermes

# 3. Database: db/097, 099, 100, 101 as postgres; then give the role a password.
sudo -u postgres psql -d maludb_os -c "ALTER ROLE app_runner PASSWORD '…'"

# 4. Secrets: /etc/business-os/runner.env from runner.env.example (root:bos-runner 0640);
#    ACTIONS_RELAY_KEY and RUNNER_KEY added to config/.env.

# 5. The sandboxed launcher, its sudoers rule, the unit.
sudo install -o root -g root -m 0755 docs/deploy/bos-agent-exec /usr/local/sbin/bos-agent-exec
sudo install -o root -g root -m 0440 docs/deploy/bos-runner.sudoers /etc/sudoers.d/bos-runner && sudo visudo -cf /etc/sudoers.d/bos-runner
sudo install -m 0644 docs/deploy/maludb-os-agent-runner.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now maludb-os-agent-runner
sudo systemctl restart maludb-os-records-mcp maludb-os-activity-mcp maludb-os-actions-mcp   # run tokens + grant enforcement
curl -s http://127.0.0.1:8815/health
```

**Upgrading Hermes:** install the new tag in a scratch venv with `mcp/hermes_conformance/plugins`,
run `mcp/hermes_conformance/run_conformance.py --hermes <venv>/bin/hermes`, read the INFO rows against
the last result, and only then move `/opt/hermes` and run the evals. The conformance plugins are
logging stand-ins and are never installed in `/opt/hermes`.

**What the sandbox is** (`bos-agent-exec`, verified 2026-09-19): user `bos-agent`; read-only
filesystem except the agent's own directory; no network beyond localhost — `api.anthropic.com` and
`1.1.1.1` are unreachable, the ledger proxy and the MCP servers are reachable; cannot read
`runner.env` or `config/.env`. Credentials and instructions reach it on stdin and a root-only
`EnvironmentFile` removed when the run ends: sudo logs a preserved environment and its command line,
and `systemctl show` reveals a transient unit's `Environment=`. Residual: other localhost listeners
(PostgreSQL, the MaluDB API) are reachable at the network level — the agent holds no credential for
any of them, and systemd's IP filter is per address, not per port.
