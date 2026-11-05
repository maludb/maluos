#!/usr/bin/python3
"""The applications step's pure parts (the maluos-apps proposal, phase 1), no kernel, no root: the apps
block of firstboot.yaml normalised, the installer's command line, the install loop against a fake runner
(markers, a failure that does not stop the next, a re-run that reconciles from the markers, the order),
the office's DNS names from a fixture of two manifests, the domain from the first-boot state or the
kernel's config, and `maluctl app names` through the plugin.

  python3 tests/apps-test.py
"""
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "packages/maludb-os-core/lib")
sys.path.insert(0, LIB)
import maludb_os_apps as A  # noqa: E402

HR = {"schema": "maludb-os.application/1", "catalog_key": "hr", "name": "HR",
      "vhost": {"label": "hr", "document_root": "html", "internal_port_env": "APP_INTERNAL_PORT"}}
APPOINTMENTS = {"schema": "maludb-os.application/1", "catalog_key": "pro_appointments", "name": "Pro Appointments",
                "vhost": {"label": "appointments"}}


def fixture(d):
    """Two installed applications (one whose label differs from its key), a directory without a manifest
    (not an application) and one whose manifest does not parse (still a name the office owes)."""
    for key, m in (("hr", HR), ("pro_appointments", APPOINTMENTS)):
        os.makedirs(os.path.join(d, key)); put(os.path.join(d, key, "maludb-os.json"), json.dumps(m))
    os.makedirs(os.path.join(d, "scratch"))
    os.makedirs(os.path.join(d, "broken")); put(os.path.join(d, "broken", "maludb-os.json"), "{not json")


def put(path, text):
    with open(path, "w") as f:
        f.write(text)


class Config(unittest.TestCase):
    def test_defaults(self):
        c = A.apps_config(None)
        self.assertEqual(c, {"install": ["hr", "projects", "helpdesk", "spaces"], "ref": {}, "propose_agents": []})
        self.assertEqual(A.apps_config({})["install"], A.DEFAULT_APPS)

    def test_empty_list_installs_none(self):
        self.assertEqual(A.apps_config({"install": []})["install"], [])

    def test_order_dedupe_and_options(self):
        c = A.apps_config({"install": ["spaces", "HR ", "doccloud", "spaces"], "ref": {"doccloud": "v0.3.1", "hr": None},
                           "propose_agents": "doccloud"})
        self.assertEqual(c["install"], ["spaces", "hr", "doccloud"])
        self.assertEqual(c["ref"], {"doccloud": "v0.3.1"})
        self.assertEqual(c["propose_agents"], ["doccloud"])
        self.assertEqual(A.apps_config({"install": "hr"})["install"], ["hr"])

    def test_bad_key_refused(self):
        with self.assertRaises(ValueError):
            A.apps_config({"install": ["hr", "../etc"]})
        with self.assertRaises(ValueError):
            A.apps_config({"install": ["Sales-CRM"]})


class Command(unittest.TestCase):
    def test_hired_with_ref(self):
        self.assertEqual(A.install_command("hr", "admin@example.com", "example.com", "https", ref="v1.2"),
                         ["php", "bin/app_install.php", "apply", "https://github.com/maludb/maludb-os-hr.git", "--by", "admin@example.com",
                          "--domain", "example.com", "--scheme", "https", "--grant-standing-departments", "--hire-agents", "--ref", "v1.2"])

    def test_proposed(self):
        cmd = A.install_command("doccloud", "a@b.c", "b.c", "http", hire=False)
        self.assertNotIn("--hire-agents", cmd); self.assertNotIn("--ref", cmd); self.assertIn("--grant-standing-departments", cmd)


class FakeRun:
    """The installer as a runner: records every call, fails the keys named, writes a line to the log."""
    def __init__(self, fail=()):
        self.fail, self.calls = set(fail), []

    def __call__(self, cmd, cwd=None, stdout=None, stderr=None, env=None, timeout=None):
        key = cmd[3].rsplit("maludb-os-", 1)[1][:-4]
        self.calls.append((key, cmd, cwd, env))
        stdout.write(f"Applying {key}\n")
        class R: pass
        r = R(); r.returncode = 2 if key in self.fail else 0
        if r.returncode: stdout.write("Stopped at code: could not read the repository\n")
        return r


class Install(unittest.TestCase):
    def test_order_markers_and_a_failure(self):
        with tempfile.TemporaryDirectory() as d:
            run, logs = FakeRun(fail={"projects"}), []
            cfg = A.apps_config({"install": ["hr", "projects", "helpdesk"], "propose_agents": ["helpdesk"], "ref": {"hr": "v2"}})
            res = A.install_apps(cfg, "admin@x.y", "x.y", "https", d, www="/nonexistent/www", run=run, log=logs.append, wait=lambda h: True)
            self.assertEqual([c[0] for c in run.calls], ["hr", "projects", "helpdesk"], "in the listed order; the failure does not stop the next")
            self.assertEqual(res["installed"], ["hr", "helpdesk"]); self.assertEqual(res["failed"], ["projects"])
            self.assertIn("could not read the repository", res["errors"]["projects"])
            self.assertTrue(os.path.exists(os.path.join(d, "hr"))); self.assertFalse(os.path.exists(os.path.join(d, "projects")))
            with open(os.path.join(d, "helpdesk")) as f:
                marker = json.load(f)
            self.assertEqual((marker["agents"], marker["ref"], marker["source"]), ("proposed", None, "https://github.com/maludb/maludb-os-helpdesk.git"))
            with open(os.path.join(d, "hr")) as f:
                self.assertEqual(json.load(f)["ref"], "v2")
            with open(os.path.join(d, "projects.log")) as f:
                self.assertIn("Applying projects", f.read())
            hr_cmd, hd_cmd = run.calls[0][1], run.calls[2][1]
            self.assertIn("--hire-agents", hr_cmd); self.assertNotIn("--hire-agents", hd_cmd); self.assertEqual(hr_cmd[-2:], ["--ref", "v2"])
            self.assertEqual(run.calls[0][2], "/nonexistent/www")
            self.assertEqual((run.calls[0][3]["HOME"], run.calls[0][3]["COMPOSER_ALLOW_SUPERUSER"], run.calls[0][3]["GIT_TERMINAL_PROMPT"]), ("/root", "1", "0"))
            self.assertTrue(any("FAILED" in l for l in logs))
            # the re-run reconciles from the markers: only the failed one runs again
            run2 = FakeRun()
            res = A.install_apps(cfg, "admin@x.y", "x.y", "https", d, run=run2, log=logs.append, wait=lambda h: True)
            self.assertEqual([c[0] for c in run2.calls], ["projects"])
            self.assertEqual((res["installed"], res["failed"]), (["hr", "projects", "helpdesk"], []))

    def test_empty_install_runs_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            run = FakeRun()
            res = A.install_apps(A.apps_config({"install": []}), "a@b.c", "b.c", "http", os.path.join(d, "apps"), run=run, wait=lambda h: self.fail("no wait"))
            self.assertEqual(run.calls, []); self.assertEqual(res, {"installed": [], "failed": [], "errors": {}})
            self.assertFalse(os.path.exists(os.path.join(d, "apps")))

    def test_network_wait_is_asked_once_for_the_first_pending(self):
        with tempfile.TemporaryDirectory() as d:
            asked = []
            A.install_apps(A.apps_config({"install": ["hr", "spaces"]}), "a@b.c", "b.c", "http", d, run=FakeRun(), log=lambda m: None, wait=lambda h: asked.append(h) or False)
            self.assertEqual(asked, ["github.com"])

    def test_wait_for_network_times_out(self):
        self.assertFalse(A.wait_for_network("nonexistent.invalid", 443, timeout=0, sleep=lambda s: None))


class Names(unittest.TestCase):
    def test_office_names(self):
        with tempfile.TemporaryDirectory() as d:
            fixture(d)
            self.assertEqual(A.office_names("example.com", d),
                             ["example.com", "www.example.com", "app.example.com", "os.example.com",
                              "broken.example.com", "hr.example.com", "appointments.example.com"])
            self.assertEqual(A.office_names("x.y", os.path.join(d, "scratch")), ["x.y", "www.x.y", "app.x.y", "os.x.y"])

    def test_office_domain(self):
        with tempfile.TemporaryDirectory() as d:
            done, env = os.path.join(d, "done"), os.path.join(d, ".env")
            self.assertIsNone(A.office_domain(done, env))
            put(env, "APP_ENV=prod\nAPP_HOST=app.kernel.test\n")
            self.assertEqual(A.office_domain(done, env), "kernel.test")
            put(done, json.dumps({"components": {"maludb-os-core": {"domain": "office.test"}}}))
            self.assertEqual(A.office_domain(done, env), "office.test")


class Plugin(unittest.TestCase):
    def run_plugin(self, env, *args):
        code = ("import sys, importlib.util; spec = importlib.util.spec_from_file_location('app', %r); m = importlib.util.module_from_spec(spec); "
                "spec.loader.exec_module(m); sys.exit(m.main(sys.argv[1:]))") % os.path.join(LIB, "maluctl.d/app.py")
        return subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, env=env)

    def test_maluctl_app_names(self):
        with tempfile.TemporaryDirectory() as d:
            fixture(d)
            done = os.path.join(d, "done"); put(done, json.dumps({"components": {"maludb-os-core": {"domain": "example.com"}}}))
            env = dict(os.environ, MALUOS_APPS_DIR=d, MALUOS_FIRSTBOOT_DONE=done, MALUOS_KERNEL_ENV="/nonexistent/.env", PYTHONPATH=LIB)
            r = self.run_plugin(env, "names")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.split(), ["example.com", "www.example.com", "app.example.com", "os.example.com",
                                                "broken.example.com", "hr.example.com", "appointments.example.com"])
            r = self.run_plugin(env, "names", "--json", "--domain", "other.test")
            self.assertEqual(json.loads(r.stdout)["names"][:2], ["other.test", "www.other.test"])
            env["MALUOS_FIRSTBOOT_DONE"] = "/nonexistent/done"
            r = self.run_plugin(env, "names")
            self.assertEqual(r.returncode, 1); self.assertIn("no office domain yet", r.stderr)
            self.assertEqual(self.run_plugin(env, "help").returncode, 0)
            self.assertEqual(self.run_plugin(env, "list").returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
