# Three kinds of server

A small business runs everything on one MaluOS server. A larger one separates the servers:

| Server | Runs | Does not run |
|---|---|---|
| **Database server** (`role: database-server`) | PostgreSQL with the MaluDB engine and its listener | the kernel, applications, agents |
| **Kernel server** (no role: the default) | the Business OS kernel (`os.`, `app.`, the public page), the agent runner, the MaluDB API, the vault, the gateway; optionally applications beside it | |
| **Application server** (`role: application-server`) | one or more applications; the vault, the gateway and the memory face, so agents can run on it | the kernel |

`preflight.py --human` says which this server is on its `data:` line and `application-server.py --show`.

## The order

1. **The database server**, if there is one: install it with `role: database-server` (its `clients` list
   must admit the kernel server and every application server), then `sudo maluctl db export DIR` and copy
   `db-admin.txt` and `db-ca.pem` to each of the other servers.
2. **The kernel server**: `/office-setup` as usual (Phase 1b for the database server). Then tell it which
   servers may use its applications' door (below), and mint one join code per application server.
3. **Each application server**: `/office-setup` there detects nothing to configure for a kernel and follows
   "On an application server" below.
4. **The proxy**: `proxy-config.sh` on the kernel server renders one upstream per name: the kernel server
   for its own names, each application server for its applications.

## On the kernel server: admit the application servers

The kernel opens its applications' door (port 8081 on its LAN address, plain HTTP, admitted by address)
only when it has a list of servers. Add them and provision again:

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/configure-kernel.py --domain <domain> --scheme <scheme> --admin-email <email> --admin-name "<name>" \
     [--proxy-address <proxy>] --application-servers 192.168.100.21,192.168.100.22 --preview     # then --apply
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/provision.sh
```

Give the same values as before for the other options (`--show` prints them); `--application-servers none`
closes the door. Addresses must be stable (static or reserved).

Mint a join code for each application server, **naming the applications it will install**. The code is
shown once, lasts fifteen minutes and is used once; the operator carries it to the application server.
Do not print it into the conversation yourself: give the operator the command to run in their own terminal.

```bash
sudo -u www-data php /var/www/bin/mint_desk_code.php --email <administrator's email> --kind server --name app-1 --apps hr,projects
```

## On an application server

Ask for, one at a time:

1. Where the data lives: this server's own PostgreSQL, or the database server (then exactly Phase 1b:
   `database-server.py --check`, `--apply`). On the database server this server gets a database and
   roles of its own (`maludb_<name>`, `maluos-vault-<name>`, …), so it never touches the kernel server's.
2. The kernel server's door: `http://<the kernel server's LAN name or address>:8081`.
3. The estate's public URL (`https://app.<domain>`), the applications, and the path of a file holding
   the join code (the operator writes it there; never read it into the conversation).

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/application-server.py --check --kernel http://kernel.example.lan:8081
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/application-server.py --apply --kernel http://kernel.example.lan:8081 --apps hr,projects \
     --estate-url https://app.example.com --code-file /root/join-code.txt
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/provision.sh
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/application-server.py --show
```

A failed `--check` says which side to fix: the door does not admit this server (the kernel's list), nothing
listens (the list is empty there), the name does not resolve, a firewall. Those fixes are made on the kernel
server; wait and check again.

Provisioning joins the estate, then installs each application here and registers it with the kernel. The
install log of an application is `/var/lib/maluos/business-os/apps/<key>.log`; a failed one is retried by
`sudo maluctl app install <key>` or the next `provision.sh`.

Afterwards the application's public name (`hr.<domain>`) must reach **this** server: at the proxy
(`proxy-config.sh` on the kernel server renders it) or in the LAN's DNS.

## What to say plainly

- The door and the applications' internal ports are plain HTTP on the LAN, protected by address lists and
  by the tokens every call carries. The servers belong on a network segment the business trusts.
- An application server holds the kernel's signing keys, as every application does today. A key per
  application comes later.
- One database server serves one kernel server and its application servers.
- Not supported: moving an installed application from one server to another; an application server for
  two kernels.
