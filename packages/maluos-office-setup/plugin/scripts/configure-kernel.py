#!/usr/bin/env python3
"""configure-kernel.py: set the Business OS kernel's keys in /etc/maluos/firstboot.yaml, structurally.

  configure-kernel.py --domain example.com --scheme https --proxy-address 192.168.100.1 \
                      --admin-email you@example.com --admin-name "Your Name" [--apps hr,projects,helpdesk,spaces[,doccloud] | --apps none | --apps keep] \
                      --preview            show the resulting block and a diff; change nothing
  configure-kernel.py ... --apply           back the file up, write it, print the block
  configure-kernel.py --show                print the current block (secrets masked)

Edits only the `maludb-os-core:` block under `components:`, line by line, so the file's comments survive;
replaces a key that exists (and removes any duplicate of it), uncomments a commented placeholder when
there is one, inserts otherwise. Sets enabled: true. Under https the four kernel names must resolve to the
proxy on the office, so --proxy-address is required unless --no-proxy-address is given; under http a
proxy_address is removed. Never touches admin_password or the *_api_key keys (set keys with
set-provider-key.sh, after provisioning). Validates the result with PyYAML before writing.
"""
import argparse, difflib, json, os, re, shutil, sys, time

PATH = "/etc/maluos/firstboot.yaml"
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ADDR_RE = re.compile(r"^(\d{1,3}(\.\d{1,3}){3}|[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*)$")
APP_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")
SECRET_KEYS = ("admin_password", "anthropic_api_key", "openrouter_api_key", "malumail_api_key")
IND = "    "   # keys of the block
SUB = "      " # keys inside apps:


def die(msg, code=1):
    print(f"ERROR {msg}", file=sys.stderr); sys.exit(code)


def find_block(lines):
    """(components_idx, start, end): start = index of '  maludb-os-core:' line, end = first index after the
    block (a line with indent <= 2 that is not blank). None, None, None when absent."""
    comp = next((i for i, l in enumerate(lines) if re.match(r"^components:\s*(#.*)?$", l)), None)
    if comp is None:
        return None, None, None
    start = None
    for i in range(comp + 1, len(lines)):
        l = lines[i]
        if l.strip() == "":
            continue
        if re.match(r"^\S", l):          # next top-level key: components ended
            break
        if re.match(r"^  maludb-os-core:\s*(#.*)?$", l):
            start = i; break
    if start is None:
        return comp, None, None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        l = lines[i]
        if l.strip() == "":
            continue
        if re.match(r"^ {0,2}\S", l):
            end = i; break
    return comp, start, end


def block_end_trim(lines, start, end):
    """The block's last meaningful line index + 1 (blank lines at the end stay outside)."""
    e = end
    while e > start + 1 and lines[e - 1].strip() == "":
        e -= 1
    return e


def key_lines(lines, start, end, key):
    return [i for i in range(start + 1, end) if re.match(rf"^{IND}{re.escape(key)}:(\s|$)", lines[i])]


def commented_key_line(lines, start, end, key):
    return next((i for i in range(start + 1, end) if re.match(rf"^{IND}#\s*{re.escape(key)}:(\s|$)", lines[i])), None)


def nested_extent(lines, i, end):
    """For a block key at index i (indent 4), the index after its nested lines (indent > 4, or blank inside)."""
    j = i + 1
    while j < end and (lines[j].strip() == "" or re.match(r"^ {5,}", lines[j])):
        j += 1
    while j > i + 1 and lines[j - 1].strip() == "":
        j -= 1
    return j


def yaml_scalar(v):
    if isinstance(v, list):                      # a flow list of plain items (addresses, networks)
        return "[" + ", ".join(yaml_scalar(x) for x in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    if re.match(r"^[A-Za-z0-9][A-Za-z0-9._@-]*$", s) and s.lower() not in ("true", "false", "null", "yes", "no", "on", "off", "~"):
        return s
    return json.dumps(s)


def set_key(lines, start, end, key, value):
    """Replace, uncomment or insert '    key: value'. Returns the new end."""
    line = f"{IND}{key}: {yaml_scalar(value)}"
    hits = key_lines(lines, start, end, key)
    if hits:
        lines[hits[0]] = line
        for i in reversed(hits[1:]):                  # a duplicate key: drop it and whatever nests under it
            j = nested_extent(lines, i, end)
            del lines[i:j]; end -= (j - i)
        return end
    c = commented_key_line(lines, start, end, key)
    if c is not None:
        lines[c] = line
        return end
    # insert after the last scalar key of the block (before any trailing comments), else right after the header
    last = start
    for i in range(start + 1, end):
        if re.match(rf"^{IND}[a-z_]+:", lines[i]):
            last = nested_extent(lines, i, end) - 1
    lines.insert(last + 1, line)
    return end + 1


def remove_key(lines, start, end, key):
    for i in reversed(key_lines(lines, start, end, key)):
        j = nested_extent(lines, i, end)
        del lines[i:j]; end -= (j - i)
    return end


def set_apps(lines, start, end, install):
    end = remove_key(lines, start, end, "apps")
    hits = key_lines(lines, start, end, "apps")
    assert not hits
    c = commented_key_line(lines, start, end, "apps")
    body = [f"{IND}apps:", f"{SUB}install: [{', '.join(install)}]"]
    if c is not None:
        # drop the commented placeholder lines of the apps block (indent 4 '#   install:' etc. that follow it)
        j = c + 1
        while j < end and re.match(rf"^{IND}#\s{{2,}}\S", lines[j]):
            j += 1
        lines[c:j] = body
        return end - (j - c) + len(body)
    last = start
    for i in range(start + 1, end):
        if re.match(rf"^{IND}[a-z_]+:", lines[i]):
            last = nested_extent(lines, i, end) - 1
    lines[last + 1:last + 1] = body
    return end + len(body)


def show_block(lines, start, end):
    out = []
    for l in lines[start:end]:
        m = re.match(rf"^({IND}({'|'.join(SECRET_KEYS)}):\s*)(.+)$", l)
        out.append(m.group(1) + "<set>" if m else l)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=PATH)
    ap.add_argument("--domain"); ap.add_argument("--scheme", choices=["http", "https"])
    ap.add_argument("--admin-email"); ap.add_argument("--admin-name")
    ap.add_argument("--proxy-address"); ap.add_argument("--no-proxy-address", action="store_true")
    ap.add_argument("--apps", help="comma-separated keys, 'none', or 'keep' (default keep)", default="keep")
    ap.add_argument("--application-servers", default="keep",
                    help="the addresses or networks of the application servers that may use this kernel's applications' door "
                         "(comma-separated), 'none', or 'keep' (default keep): docs/phase14-application-servers.md")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--preview", action="store_true"); g.add_argument("--apply", action="store_true"); g.add_argument("--show", action="store_true")
    a = ap.parse_args()

    try:
        text = open(a.file).read()
    except OSError as e:
        die(f"cannot read {a.file}: {e}")
    lines = text.split("\n")
    comp, start, end = find_block(lines)

    if a.show:
        if start is None:
            print("(no maludb-os-core block)"); return 0
        print(show_block(lines, start, end)); return 0
    if not (a.preview or a.apply):
        die("say --preview, --apply or --show")

    # ---- validate the inputs
    missing = [n for n, v in (("--domain", a.domain), ("--scheme", a.scheme), ("--admin-email", a.admin_email), ("--admin-name", a.admin_name)) if not v]
    if missing:
        die("required: " + ", ".join(missing))
    domain = a.domain.strip().lower().rstrip(".")
    if not DOMAIN_RE.match(domain):
        die(f"'{a.domain}' is not a usable domain (lowercase labels, at least one dot, no scheme or path)")
    if not EMAIL_RE.match(a.admin_email.strip()):
        die(f"'{a.admin_email}' is not an email address")
    name = a.admin_name.strip()
    if not (1 <= len(name) <= 120) or "\n" in name:
        die("--admin-name must be one line, 1 to 120 characters")
    proxy = (a.proxy_address or "").strip().lower() or None
    if a.scheme == "https":
        if not proxy and not a.no_proxy_address:
            die("scheme https: give --proxy-address <the TLS proxy's address as the office reaches it>, or --no-proxy-address if the office can reach its own names some other way")
        if proxy and not ADDR_RE.match(proxy):
            die(f"'{a.proxy_address}' is not an IPv4 address or hostname")
        if proxy and proxy.startswith("127."):
            die("the proxy address cannot be loopback: nothing on the office answers :443")
    else:
        if proxy:
            die("scheme http has no TLS proxy; drop --proxy-address (or choose https)")
    apps = None
    if a.apps.strip().lower() == "none":
        apps = []
    elif a.apps.strip().lower() != "keep":
        apps = [k.strip() for k in a.apps.split(",") if k.strip()]
        bad = [k for k in apps if not APP_KEY_RE.match(k)]
        if bad:
            die("not application keys: " + ", ".join(bad))

    appservers = None
    if a.application_servers.strip().lower() == "none":
        appservers = []
    elif a.application_servers.strip().lower() != "keep":
        appservers = [x.strip() for x in a.application_servers.split(",") if x.strip()]
        bad = [x for x in appservers if not re.fullmatch(r"[0-9A-Fa-f:.]+(/\d{1,3})?", x)]
        if bad:
            die("not addresses or networks (like 192.168.100.21 or 192.168.100.0/24): " + ", ".join(bad))

    # ---- edit
    if comp is None:
        lines = [l for l in lines]
        if lines and lines[-1] == "":
            lines.pop()
        lines += ["components:", "  maludb-os-core:", ""]
        comp, start, end = find_block(lines)
    if start is None:
        # components exists without the kernel's block: append the block at the end of the components mapping
        e = comp + 1
        while e < len(lines) and (lines[e].strip() == "" or re.match(r"^\s", lines[e])):
            e += 1
        while e > comp + 1 and lines[e - 1].strip() == "":
            e -= 1
        lines.insert(e, "  maludb-os-core:")
        comp, start, end = find_block(lines)
    end = block_end_trim(lines, start, end)
    end = set_key(lines, start, end, "enabled", True)
    end = set_key(lines, start, end, "domain", domain)
    end = set_key(lines, start, end, "scheme", a.scheme)
    end = set_key(lines, start, end, "admin_email", a.admin_email.strip())
    end = set_key(lines, start, end, "admin_name", name)
    if a.scheme == "https" and proxy:
        end = set_key(lines, start, end, "proxy_address", proxy)
    else:
        end = remove_key(lines, start, end, "proxy_address")
    if apps is not None:
        end = set_apps(lines, start, end, apps)
    if appservers is not None:
        end = set_key(lines, start, end, "application_servers", appservers) if appservers else remove_key(lines, start, end, "application_servers")
    new_text = "\n".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"

    # ---- validate the result
    try:
        import yaml
        cfg = yaml.safe_load(new_text)
    except Exception as e:
        die(f"the edited file is not valid YAML; nothing written: {e}")
    blk = ((cfg or {}).get("components") or {}).get("maludb-os-core") or {}
    expect = {"enabled": True, "domain": domain, "scheme": a.scheme, "admin_email": a.admin_email.strip(), "admin_name": name}
    wrong = {k: blk.get(k) for k, v in expect.items() if blk.get(k) != v}
    if wrong:
        die(f"the edited block does not read back as intended ({wrong}); nothing written")
    if a.scheme == "https" and proxy and blk.get("proxy_address") != proxy:
        die("proxy_address did not read back; nothing written")
    if a.scheme == "http" and "proxy_address" in blk:
        die("proxy_address still present under http; nothing written")
    if apps is not None and (blk.get("apps") or {}).get("install") != apps:
        die("apps.install did not read back; nothing written")

    comp, start, end = find_block(lines)
    print("# resulting components.maludb-os-core block:")
    print(show_block(lines, start, end))
    diff = list(difflib.unified_diff(text.split("\n"), new_text.split("\n"), fromfile=a.file, tofile=a.file + " (new)", lineterm="", n=2))
    diff = [l for l in diff if not any(l.lstrip("+- ").startswith(k + ":") for k in SECRET_KEYS)]
    print("\n# diff:")
    print("\n".join(diff) if diff else "(no change)")
    if a.preview:
        return 0
    if os.geteuid() != 0 and a.file == PATH:
        die("--apply needs root (sudo)", 97)
    st = os.stat(a.file)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = f"{a.file}.before-office-setup-{stamp}"
    shutil.copy2(a.file, backup); os.chmod(backup, 0o600)
    tmp = a.file + ".office-setup.tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, st.st_mode & 0o777), "w") as fh:
        fh.write(new_text)
    os.chown(tmp, st.st_uid, st.st_gid)
    os.replace(tmp, a.file)
    print(f"\n# written: {a.file}; backup (mode 600): {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
