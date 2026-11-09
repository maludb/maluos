#!/usr/bin/python3
"""Phase 14's pure parts (docs/phase14-database-server.md), no PostgreSQL, no root: where the data is from
firstboot.yaml (the local cluster, a database server, the server itself), the admin credential and the
certificate taken from the plan's medium once, the PGPASSFILE line and its escapes, the connection string
(never a password in it), the service keys, the pg_hba block (replaced, never doubled), and the install
plan's role and database_server keys with what the installer writes into the target.

  python3 tests/database-server-test.py
"""
import os, stat, sys, tempfile, unittest, warnings
warnings.simplefilter("ignore", ResourceWarning)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="maluos-dbs-")
os.environ.update(MALUOS_SECRETS_DIR=os.path.join(TMP, "secrets"), MALUOS_DB_CA=os.path.join(TMP, "ca.pem"),
                  MALUOS_FIRSTBOOT_CONFIG=os.path.join(TMP, "firstboot.yaml"), MALUOS_STATE_DIR=os.path.join(TMP, "state"))
sys.path.insert(0, os.path.join(ROOT, "packages/maluos-firstboot/lib"))
sys.path.insert(0, os.path.join(ROOT, "packages/maluos-installer/lib"))
import maluos_provision as mp  # noqa: E402
from maluos_installer import plan as P  # noqa: E402

MINIMAL = """maluos-install:
  version: 1
  storage: {disk: first, erase: true}
  identity: {user: {name: ed, password: "plain:secret"}}
"""


def put(path, text):
    with open(path, "w") as f:
        f.write(text)


class Target(unittest.TestCase):
    def test_local_by_default(self):
        self.assertIsNone(mp.database_target({}))
        self.assertIsNone(mp.database_target({"database_server": {}}))
        self.assertIsNone(mp.database_target({"database_server": {"host": "local"}}))
        self.assertEqual(mp.service_target(), {})

    def test_the_server_itself_is_local(self):
        cfg = {"role": "database-server", "database_server": {"listen": "0.0.0.0", "host": "ignored", "cluster": "18/x"}}
        self.assertTrue(mp.is_database_server(cfg))
        self.assertIsNone(mp.database_target(cfg))
        self.assertEqual(mp._TARGET.get("cluster"), "18/x")
        mp._TARGET.pop("cluster", None)

    def test_an_office(self):
        t = mp.database_target({"database_server": {"host": "db-1.example.com", "credential": "file:/m/db-admin.txt", "ca": "file:/m/ca.pem"}})
        self.assertEqual((t["host"], t["port"], t["admin"], t["sslmode"]), ("db-1.example.com", 5432, "maluos_admin", "verify-full"))
        self.assertEqual((t["credential"], t["ca"]), ("/m/db-admin.txt", "/m/ca.pem"))
        t = mp.database_target({"database_server": {"host": "10.0.0.5", "port": 5433, "admin": "a"}})
        self.assertEqual((t["port"], t["sslmode"], t["ca"]), (5433, "require", None))      # no certificate: encrypted, not verified
        st = mp.service_target()
        self.assertEqual(st, {"pg_host": "10.0.0.5", "pg_port": 5433, "pg_sslmode": "require"})
        mp.database_target({})

    def test_conninfo_has_no_password(self):
        t = {"host": "db-1", "port": 5432, "admin": "maluos_admin", "sslmode": "verify-full", "ca": "/etc/x.pem"}
        c = mp.conninfo(t, "maludb")
        self.assertIn("host=db-1 port=5432 user=maluos_admin dbname=maludb sslmode=verify-full", c)
        self.assertIn("sslrootcert=/etc/x.pem", c)
        self.assertNotIn("password", c)
        self.assertIn("user=svc", mp.conninfo(t, "maludb", user="svc"))


class Credential(unittest.TestCase):
    def test_taken_once_from_the_medium(self):
        medium = os.path.join(TMP, "medium"); os.makedirs(medium, exist_ok=True)
        put(os.path.join(medium, "db-admin.txt"), "s3:cr\\et\n"); put(os.path.join(medium, "ca.pem"), "CERT\n")
        t = {"host": "db-1", "port": 5432, "admin": "maluos_admin", "sslmode": "verify-full",
             "credential": os.path.join(medium, "db-admin.txt"), "ca": os.path.join(medium, "ca.pem")}
        mp.prepare_remote(t)
        self.assertEqual(open(mp.DB_ADMIN_FILE).read(), "s3:cr\\et\n")
        self.assertEqual(open(mp.DB_PGPASS).read(), "db-1:5432:*:maluos_admin:s3\\:cr\\\\et\n")      # ':' and '\' escaped
        for f in (mp.DB_ADMIN_FILE, mp.DB_PGPASS):
            self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(mp.SECRETS_DIR).st_mode), 0o700)
        self.assertEqual((t["ca"], open(mp.DB_CA).read()), (mp.DB_CA, "CERT\n"))
        # the medium gone: the stored copies serve
        os.remove(os.path.join(medium, "db-admin.txt")); os.remove(os.path.join(medium, "ca.pem"))
        t2 = {"host": "db-1", "port": 5432, "admin": "maluos_admin", "sslmode": "verify-full",
              "credential": os.path.join(medium, "db-admin.txt"), "ca": os.path.join(medium, "ca.pem")}
        mp.prepare_remote(t2)
        self.assertEqual(t2["ca"], mp.DB_CA)

    def test_none_is_an_error(self):
        os.makedirs(mp.SECRETS_DIR, exist_ok=True)
        for f in (mp.DB_ADMIN_FILE, mp.DB_PGPASS):
            if os.path.exists(f):
                os.remove(f)
        with self.assertRaisesRegex(RuntimeError, "no admin password"):
            mp.prepare_remote({"host": "db-1", "port": 5432, "admin": "a", "sslmode": "require", "credential": "/nowhere", "ca": None})


class Hba(unittest.TestCase):
    BASE = "local all postgres peer\nhost all all 127.0.0.1/32 scram-sha-256\n"

    def test_block(self):
        out = mp.hba_block(self.BASE, ["192.168.100.0/24", "10.0.0.7", "fd00::1"])
        self.assertTrue(out.startswith(self.BASE))
        self.assertIn("hostssl all all 192.168.100.0/24 scram-sha-256", out)
        self.assertIn("hostssl all all 10.0.0.7/32 scram-sha-256", out)          # a bare address is one host
        self.assertIn("hostssl all all fd00::1/128 scram-sha-256", out)
        self.assertNotIn("\nhost all all 192.168", out)                          # never without TLS

    def test_replaced_not_doubled(self):
        once = mp.hba_block(self.BASE, ["192.168.100.0/24"])
        twice = mp.hba_block(once, ["10.1.0.0/16"])
        self.assertEqual(twice.count("# maluos database-server begin"), 1)
        self.assertNotIn("192.168.100.0/24", twice)
        self.assertIn("10.1.0.0/16", twice)
        self.assertEqual(mp.hba_block(twice, ["10.1.0.0/16"]), twice)             # idempotent


class Plan(unittest.TestCase):
    def test_default_is_local(self):
        p = P.load(MINIMAL)
        self.assertEqual(p["firstboot"]["role"], "")
        self.assertEqual(p["firstboot"]["database_server"]["host"], "")

    def test_office(self):
        p = P.load(MINIMAL + "  firstboot: {database_server: {host: db-1.example.com, credential: 'file:plans/db-admin.txt', ca: 'file:plans/db-ca.pem'}}\n")
        ds = p["firstboot"]["database_server"]
        self.assertEqual((ds["host"], ds["port"], ds["admin"]), ("db-1.example.com", 5432, "maluos_admin"))
        self.assertEqual(P.redact(p)["firstboot"]["database_server"]["credential"], "<redacted>")
        with tempfile.TemporaryDirectory() as media:
            os.makedirs(os.path.join(media, "plans"))
            put(os.path.join(media, "plans/db-admin.txt"), "pw-from-the-server\n"); put(os.path.join(media, "plans/db-ca.pem"), "-----BEGIN CERTIFICATE-----\nx\n")
            P.resolve_refs(p, media=media)
        self.assertEqual(ds["credential"], "pw-from-the-server")
        self.assertTrue(ds["ca"].startswith("-----BEGIN CERTIFICATE-----"))

    def test_errors(self):
        for body, needle in (
                ("{database_server: {host: db-1}}", "credential is required"),
                ("{database_server: {host: 'bad host', credential: x}}", "neither an address nor a host name"),
                ("{database_server: {host: db-1, credential: x, sslmode: verify-full}}", "needs firstboot.database_server.ca"),
                ("{database_server: {host: db-1, credential: x, port: 0}}", "is not a port"),
                ("{database_server: {credential: x}}", "names no host"),
                ("{role: database-server, database_server: {host: db-1}}", "this host is the server"),
                ("{role: database-server, database_server: {clients: [nonsense]}}", "is not an address or a network"),
                ("{role: database-server, components: {maludb-os-core: {enabled: true, domain: x.local}}}", "runs no Business OS kernel"),
                ("{role: application-server}", "expected one of")):
            with self.subTest(body=body):
                with self.assertRaises(P.PlanError) as cm:
                    P.load(MINIMAL + "  firstboot: " + body + "\n")
                self.assertIn(needle, str(cm.exception))

    def test_server(self):
        p = P.load(MINIMAL + "  firstboot: {role: database-server, database_server: {listen: 0.0.0.0, clients: [192.168.100.0/24]}}\n")
        self.assertEqual(p["firstboot"]["role"], "database-server")
        self.assertEqual(p["firstboot"]["database_server"]["clients"], ["192.168.100.0/24"])


class Configure(unittest.TestCase):
    """What the installer writes into the target's firstboot.yaml (sub_firstboot), against a fake context."""

    def run_sub(self, body):
        import yaml
        from maluos_installer.steps import configure as C
        p = P.load(MINIMAL + "  firstboot: " + body + "\n")
        target = tempfile.mkdtemp(prefix="maluos-target-")

        class Ctx:
            plan = p
            written = {}

            def tpath(self, path): return os.path.join(target, path.lstrip("/"))
            def run(self, argv, check=True): return None

            def write(self, path, content, mode=0o644, in_target=True):
                self.written[path] = (content, mode)
        ctx = Ctx()
        C.sub_firstboot(ctx)
        text, _ = ctx.written["/etc/maluos/firstboot.yaml"]
        return yaml.safe_load(text), ctx.written

    def test_office(self):
        doc, w = self.run_sub("{cloud_init: false, database_server: {host: db-1.example.com, credential: the-password, ca: PEM}}")
        self.assertEqual(doc["database_server"], {"host": "db-1.example.com", "port": 5432, "admin": "maluos_admin",
                                                  "credential": "file:/var/lib/maluos/secrets/db-admin.password",
                                                  "ca": "file:/etc/maluos/database-server-ca.pem", "sslmode": "verify-full"})
        self.assertEqual(w["/var/lib/maluos/secrets/db-admin.password"], ("the-password\n", 0o600))
        self.assertEqual(w["/etc/maluos/database-server-ca.pem"], ("PEM\n", 0o644))
        self.assertNotIn("the-password", w["/etc/maluos/firstboot.yaml"][0])      # the password is never in firstboot.yaml
        self.assertNotIn("role", doc)

    def test_office_without_certificate(self):
        doc, w = self.run_sub("{cloud_init: false, database_server: {host: 10.0.0.5, credential: pw}}")
        self.assertEqual(doc["database_server"]["sslmode"], "require")
        self.assertNotIn("ca", doc["database_server"])

    def test_server(self):
        doc, w = self.run_sub("{cloud_init: false, role: database-server, database_server: {listen: 0.0.0.0, clients: [192.168.100.0/24], names: [db-1.example.com]}}")
        self.assertEqual(doc["role"], "database-server")
        self.assertEqual(doc["database_server"], {"listen": "0.0.0.0", "clients": ["192.168.100.0/24"], "names": ["db-1.example.com"], "admin": "maluos_admin"})
        self.assertNotIn("/var/lib/maluos/secrets/db-admin.password", w)

    def test_default_writes_nothing(self):
        doc, w = self.run_sub("{cloud_init: false}")
        self.assertNotIn("database_server", doc); self.assertNotIn("role", doc)


if __name__ == "__main__":
    unittest.main()
