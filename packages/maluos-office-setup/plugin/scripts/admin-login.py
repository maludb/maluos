#!/usr/bin/env python3
"""admin-login.py: does the first sign-in work, and if not, why; and a way to make it work.

  admin-login.py --check [--email E]    PASS/FAIL per line: the administrator's member record, the stored
                                        password against it, the sign-in throttle, the session cookie for the
                                        office's scheme, then a real sign-in against the kernel on this host.
                                        Exit 1 when any FAIL. Never prints the password.
  admin-login.py --reset [--email E]    a new generated password for that member (the member is created as a
                                        super-admin when no member has the email), written to the root-only
                                        file, failed sign-in attempts cleared; then the same checks.

The email defaults to components.maludb-os-core.admin_email of /etc/maluos/firstboot.yaml. The password
is the one in /var/lib/maluos/secrets/business-os/admin-password: first boot generates it once, for the
first super-admin; the operator reads it with `sudo cat`. This script reads it, compares it, replaces it
on --reset, and never shows it. Needs root (the plugin's sudoers rule covers it).
"""
import argparse, http.client, json, os, re, secrets, subprocess, sys, urllib.parse

E = os.environ.get      # the overrides are for the package's test (a scratch kernel on a development host)
FIRSTBOOT_YAML = E("MALUOS_FIRSTBOOT_CONFIG", "/etc/maluos/firstboot.yaml")
ADMIN_PW = E("MALUOS_ADMIN_PW_FILE", "/var/lib/maluos/secrets/business-os/admin-password")
KERNEL = E("MALUOS_KERNEL_DIR", "/var/www")
KERNEL_ENV = os.path.join(KERNEL, "config/.env")
KERNEL_USER = E("MALUOS_KERNEL_USER", "www-data")
API_PORT = int(E("MALUOS_KERNEL_API_PORT", "8080"))
FAILED = 0

PHP = r'''
require getcwd() . "/app/bootstrap.php";
$in = json_decode((string) stream_get_contents(STDIN), true);
$pdo = db();
$email = normalize_email((string) $in["email"]);
$out = ["email" => $email];
if (($in["op"] ?? "") === "reset") {
    $m = find_member_by_email($pdo, $email);
    if ($m === null) { $out["missing"] = true; echo json_encode($out); exit(0); }
    $pdo->prepare("UPDATE members SET password_hash = :h WHERE id = :id")->execute(["h" => hash_password((string) $in["password"]), "id" => (int) $m["id"]]);
    $pdo->prepare("DELETE FROM login_attempts WHERE email = :e AND NOT successful")->execute(["e" => $email]);
    log_activity($pdo, "member.password_reset_by_operator", "member", (int) $m["id"], ["source" => "cron", "after" => ["email" => $email]]);
}
$m = find_member_by_email($pdo, $email);
$out["exists"] = $m !== null;
if ($m !== null) {
    $out += ["status" => $m["status"] ?? null, "business_role" => $m["business_role"] ?? null, "has_password" => ($m["password_hash"] ?? null) !== null,
             "totp" => ($m["totp_enabled_at"] ?? null) !== null,
             "password_matches" => ($m["password_hash"] ?? null) !== null && password_verify((string) $in["password"], (string) $m["password_hash"])];
}
$st = $pdo->prepare("SELECT count(*) FROM login_attempts WHERE email = :e AND NOT successful AND attempted_at > now() - interval '15 minutes'");
$st->execute(["e" => $email]); $out["recent_failures"] = (int) $st->fetchColumn();
$out["super_admins"] = $pdo->query("SELECT email FROM members WHERE business_role = 'super_admin' AND member_kind = 'human' AND status = 'active' ORDER BY id")->fetchAll(PDO::FETCH_COLUMN);
echo json_encode($out);
'''


def say(s=""): print(s, flush=True)
def ok(s): say(f"PASS  {s}")
def note(s): say(f"NOTE  {s}")
def bad(s):
    global FAILED
    FAILED += 1; say(f"FAIL  {s}")
def die(s, code=1):
    print(f"ERROR {s}", file=sys.stderr); sys.exit(code)


def kernel_block():
    try:
        import yaml
        cfg = yaml.safe_load(open(FIRSTBOOT_YAML)) or {}
    except Exception as e:
        die(f"cannot read {FIRSTBOOT_YAML}: {e}")
    return ((cfg.get("components") or {}).get("maludb-os-core")) or {}


def env_value(key):
    try:
        for line in open(KERNEL_ENV):
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def kernel(op, email, password):
    """The kernel's own code, as www-data: the member, the hash, the throttle. The password goes in on stdin."""
    r = subprocess.run(["runuser", "-u", KERNEL_USER, "--", "php", "-r", PHP], cwd=KERNEL, capture_output=True, text=True,
                       input=json.dumps({"op": op, "email": email, "password": password}), timeout=120)
    if r.returncode != 0 or not r.stdout.strip().startswith("{"):
        die("the kernel did not answer (is it provisioned? `sudo maluctl status`): " + (r.stderr or r.stdout).strip()[-300:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def request(method, path, host, scheme, headers=None, body=None):
    """One request to the kernel's PHP API on this host (127.0.0.1:8080), with the headers the web front end
    forwards from the browser: the office's name and, under https, the proxy's X-Forwarded-Proto."""
    h = {"Host": host, "X-Forwarded-Host": host, "Accept": "application/json"}
    if scheme == "https":
        h["X-Forwarded-Proto"] = "https"
    h.update(headers or {})
    for p in (path, path + ".php"):          # Apache rewrites /login to login.php; a bare PHP server does not
        c = http.client.HTTPConnection("127.0.0.1", API_PORT, timeout=20)
        c.request(method, p, body=body, headers=h)
        r = c.getresponse(); data = r.read().decode("utf-8", "replace")
        cookies = r.headers.get_all("Set-Cookie") or []
        c.close()
        if r.status != 404:
            break
    return r.status, data, cookies


def sign_in(email, password, domain, scheme):
    """A real sign-in: the session's CSRF token, then the form's POST. Returns (ok, text)."""
    host = f"app.{domain}"
    st, body, cookies = request("GET", "/api/v1/session", host, scheme)
    if st != 200:
        return False, f"GET /api/v1/session for {host} answered HTTP {st}"
    try:
        token = json.loads(body)["csrf_token"]
    except Exception:
        return False, "the session endpoint returned no CSRF token"
    sess = next((c for c in cookies if c.startswith("CSTSID=")), None)
    if not sess:
        return False, "the kernel set no session cookie"
    secure = "secure" in [p.strip().lower() for p in sess.split(";")]
    if scheme == "http" and secure:
        bad("the session cookie is marked Secure although the office is served over http: a browser discards it, the CSRF "
            "check then fails and no sign-in can succeed, whatever the password. Fixed in maludb-os-core 2026.11.09maluos2 "
            "(sudo apt update && sudo apt install maludb-os-core), or serve the office over https")
    elif scheme == "https" and not secure:
        bad("the session cookie is not marked Secure under https")
    else:
        ok(f"the session cookie suits {scheme} ({'Secure' if secure else 'not Secure'})")
    form = urllib.parse.urlencode({"email": email, "password": password, "csrf_token": token})
    st, body, _ = request("POST", "/login", host, scheme, body=form,
                          headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": sess.split(";")[0]})
    try:
        j = json.loads(body)
    except Exception:
        j = {}
    if st == 200 and (j.get("ok") or j.get("two_factor_required") or (j.get("data") or {}).get("two_factor_required")):
        return True, "two-factor code asked next" if "two_factor" in body else "signed in"
    err = (j.get("error") or {})
    return False, f"HTTP {st} {err.get('code') or ''} {err.get('message') or body[:120]}".strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true"); g.add_argument("--reset", action="store_true")
    ap.add_argument("--email")
    a = ap.parse_args()
    if os.geteuid() != 0:
        if subprocess.call(["sudo", "-n", "true"], stderr=subprocess.DEVNULL) == 0:
            os.execvp("sudo", ["sudo", "-n", os.path.realpath(__file__), *sys.argv[1:]])
        die(f"needs root: sudo {os.path.realpath(__file__)} {' '.join(sys.argv[1:])}", 97)
    blk = kernel_block()
    domain, scheme = str(blk.get("domain") or ""), str(blk.get("scheme") or "http")
    email = (a.email or blk.get("admin_email") or "").strip()
    if not blk.get("enabled") or not domain:
        die("the kernel is not configured (components.maludb-os-core has no domain): run the setup first")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        die("no administrator email: --email E, or admin_email in the kernel's block of firstboot.yaml")
    app_url = E("MALUOS_KERNEL_APP_URL") or env_value("APP_URL")
    say(f"## the first sign-in: {scheme}://app.{domain} as {email}")
    if app_url != f"{scheme}://app.{domain}":
        bad(f"the kernel is provisioned for '{app_url}', not {scheme}://app.{domain}: run provision.sh, then this check again")

    password = open(ADMIN_PW).read().strip() if os.path.exists(ADMIN_PW) else ""
    if a.reset:
        password = secrets.token_urlsafe(15)
        r = kernel("reset", email, password)
        if r.get("missing"):
            name = str(blk.get("admin_name") or "Administrator")
            c = subprocess.run(["runuser", "-u", KERNEL_USER, "--", "php", "bin/bootstrap_organizer.php", "--email", email, "--name", name, "--password", password],
                               cwd=KERNEL, capture_output=True, text=True)
            if c.returncode != 0:
                die("could not create the super-admin: " + (c.stderr or c.stdout).strip()[-200:])
            say(f"created the super-admin {email}")
        os.makedirs(os.path.dirname(ADMIN_PW), mode=0o700, exist_ok=True)
        with open(os.open(ADMIN_PW, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(password + "\n")
        say(f"a new password is set for {email} and stored in {ADMIN_PW} (root-only; read it with sudo cat, change it after signing in)")
    elif not password:
        bad(f"no stored password ({ADMIN_PW} is missing or empty): --reset makes one")

    r = kernel("check", email, password)
    others = [e for e in r.get("super_admins") or [] if e != r["email"]]
    if not r.get("exists"):
        bad(f"no member has the email {r['email']}" + (f"; the super-admins are: {', '.join(others)}" if others else "") + ". Sign in as one of those, or --reset creates this one")
    else:
        ok(f"member {r['email']} exists") if r.get("status") == "active" else bad(f"member {r['email']} is {r.get('status')}, not active")
        ok("it is a super-admin (os.<domain> admits it)") if r.get("business_role") == "super_admin" else bad(f"its role is {r.get('business_role')}: os.{domain} admits super-admins only")
        if not r.get("has_password"):
            bad("the member has no password (a Google-only account): --reset sets one")
        elif password and r.get("password_matches"):
            ok("the stored password is this member's password")
        elif password:
            bad("the stored password is NOT this member's password: it was changed after first boot (the file keeps the first one), or the member "
                "was made another way. Use the password you set, or --reset for a new one")
        if r.get("totp"):
            note("two-factor sign-in is on for this member: the authenticator's code is asked after the password")
    if others:
        note("other super-admins: " + ", ".join(others) + " (each has its own password)")
    n = r.get("recent_failures", 0)
    if n >= 5:
        bad(f"{n} failed sign-ins for this email in the last 15 minutes: the kernel refuses further ones for a while (--reset clears them)")
    elif n:
        note(f"{n} failed sign-in(s) for this email in the last 15 minutes (5 lock it for a while)")
    if r.get("exists") and password and r.get("password_matches"):
        try:
            good, text = sign_in(email, password, domain, scheme)
        except OSError as e:
            good, text = False, f"the kernel's API on 127.0.0.1:8080 did not answer: {e}"
        ok(f"a sign-in on this host with the stored password succeeds ({text})") if good else bad(f"a sign-in on this host with the stored password fails: {text}")
    say()
    if FAILED:
        say(f"{FAILED} check(s) failed"); return 1
    say(f"the sign-in works on the office itself. If a browser still cannot sign in at {scheme}://app.{domain}, the cause is between the "
        "browser and the office: the name's DNS, the proxy's server block, or a different scheme in the address bar than the office is configured for")
    return 0


if __name__ == "__main__":
    sys.exit(main())
