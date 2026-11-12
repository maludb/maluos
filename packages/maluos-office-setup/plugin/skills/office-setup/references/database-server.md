# The data on a database server

A MaluOS server keeps its data in its own PostgreSQL cluster unless its `/etc/maluos/firstboot.yaml`
has a `database_server` block naming another MaluOS server. That other server is installed with
`role: database-server`: it runs PostgreSQL 18 with the MaluDB engine and the engine's listener, makes
an admin role for the servers that use it (`maluos_admin`: it may create roles and databases, it is not
a superuser), turns TLS on with a certificate of its own, and admits clients by address. It runs no
Business OS kernel and no application.

## What this plugin supports

| Layout | State |
|---|---|
| One server: kernel, applications and data together | supported (the default) |
| A database server, and one server running the kernel and its applications with its data there | supported: Phase 1b of `/office-setup`, or the `database_server` block given at install time |
| Further application servers, each running one or more applications apart from the kernel | **not supported yet**. The kernel's installer puts every application on the kernel's own server. Say so plainly; do not improvise it. |
| Two servers (two kernels, or a kernel and another MaluOS server) sharing one database server | **not supported**: both would claim the same service roles on it, and the second would reset the first one's passwords. One database server serves one kernel server today. |
| Moving an office that already holds data to a database server | **not supported**: nothing is copied. |

## On the database server (its operator, before `/office-setup` here)

```yaml
# /etc/maluos/firstboot.yaml on the database server (or its install plan)
role: database-server
database_server:
  listen: 0.0.0.0                      # or its LAN address
  clients: [192.168.100.0/24]          # the networks or addresses of the servers that may connect
  names: [db-1.example.com]            # the names those servers will use; they go into the certificate
```

```bash
sudo maluctl provision --force         # after any change to the block
sudo maluctl db status                 # role, clients, TLS, the certificate's fingerprint
sudo maluctl db export /root/db-export # db-admin.txt (the admin password, mode 600), db-ca.pem, database-server.yaml
```

The operator copies `db-admin.txt` and `db-ca.pem` to this server (`scp`, or the plan's medium at
install time) and removes them from shared media once this server has provisioned.

## The name

- Use a name this server resolves on its own network: LAN DNS, or a line in this server's `/etc/hosts`.
- The certificate must carry it. It always carries the database server's host name and its full name;
  anything else is listed under `database_server.names` there.
- Not the estate's overlay name (`<host>.internal`). The overlay's members are rows of the kernel's
  database, so the kernel cannot reach that database over the overlay when it starts.

## What changes on this server

- First boot's services (the vault, the gateway, the memory face, the MaluDB API) and the kernel
  connect to the database server over TLS with the certificate verified; each service has its own role
  and password, kept root-only here or in the vault.
- `sudo maluctl db status` says where the data is and whether it answers; `sudo maluctl db psql` opens
  a session there as the admin role. Nobody is a PostgreSQL superuser on this server.
- The applications installed beside the kernel get their databases on the database server too.
- Backups of the data are the database server's business, not this server's.

## Checks

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/database-server.py --show
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/verify.sh --domain <domain> --scheme <scheme> [--proxy-address <proxy>]   # "## the data"
```
