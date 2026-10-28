#!/usr/bin/python3
"""Unit test of the delegation envelope (Phase 13 slice 2): canonical form, keys, signing, verification, forwarding,
the accept policy. Runs without a kernel or a vault:  python3 tests/envelope-test.py"""
import os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "packages", "maluos-estate", "lib"))
import maluos_estate.envelope as E

fails = 0
def ok(c, label):
    global fails
    fails += 0 if c else 1
    print(("  ok   " if c else "  FAIL ") + label)

sample = {"v": 1, "z": {"b": 2, "a": [3, 1.5, "x/y", "é"], "empty": [], "nil": None}, "id": "env_abc", "sig": {"value": "drop"}, "budget": {"usd": 0.5, "calls": 20}}
ok(E.canonical(sample).decode() == '{"budget":{"calls":20,"usd":0.5},"id":"env_abc","v":1,"z":{"a":[3,1.5,"x/y","é"],"b":2}}', "canonical: sig and empty members dropped, keys sorted, no whitespace, unicode and slashes kept")
priv, pub = E.genkey("desk:42")
ok(pub.startswith("ssh-ed25519 ") and pub.endswith(" desk:42") and len(E.raw_public(pub)) == 32, "genkey: an OpenSSH private key and an ssh-ed25519 line")
ok(E.public_of_private(priv, "desk:42") == pub, "the public line follows from the private key")
ok(E.raw_public("ssh-rsa AAAA") is None and E.raw_public("nope") is None, "raw_public refuses other keys")
mk = lambda **kw: E.make({"principal": "user:ed", "kind": "human", "node": "desk:42"}, {"principal": "user:ed", "node": "desk:42"}, {"agent": "helper", "node": "server:57"}, "ping", **kw)
env = E.sign(mk(), "desk:42", priv)
ok(env["sig"]["alg"] == "ed25519" and env["sig"]["key"] == "desk:42" and env["sender"]["node"] == "desk:42", "sign: alg, key, the sender's node set")
n = E.Nonces()
ok(E.verify(env, {"desk:42": pub}, "desk:42", n) == (True, None, None), "verify: a valid envelope")
ok(E.verify(env, {"desk:42": pub}, "desk:42", n)[1] == "replay", "the same nonce again: replay")
ok(E.verify(dict(env, purpose="x"), {"desk:42": pub})[1] == "bad_signature", "tampered: bad_signature")
ok(E.verify(env, {"desk:42": E.genkey()[1]})[1] == "bad_signature", "another key: bad_signature")
ok(E.verify(env, {})[1] == "bad_signature", "no key known: bad_signature")
ok(E.verify(env, {"desk:42": pub}, "server:57")[1] == "bad_signature", "the wrong expected signer: bad_signature")
old = mk(); old["issued_at"] = E.utc(time.time() - 7200); old["expires_at"] = E.utc(time.time() - 3600)
ok(E.verify(E.sign(old, "desk:42", priv), {"desk:42": pub})[1] == "expired", "expired")
lng = mk(); lng["expires_at"] = E.utc(time.time() + 7200)
ok(E.verify(E.sign(lng, "desk:42", priv), {"desk:42": pub})[1] == "bad_envelope", "a life over an hour: bad_envelope")
bad = mk(); bad["chain"] = [{"principal": "agent:x", "node": "desk:42", "ts": E.utc(), "task_id": None}]
ok(E.verify(E.sign(bad, "desk:42", priv), {"desk:42": pub})[1] == "bad_envelope", "the chain's last hop is not the sender: bad_envelope")
cls = mk(authority={"scopes": [], "classification": "secret", "budget": {}})
ok(E.verify(E.sign(cls, "desk:42", priv), {"desk:42": pub})[1] == "bad_envelope", "an unknown classification: bad_envelope")
ok(E.verify({"v": 2}, {})[1] == "bad_envelope" and E.verify("x", {})[1] == "bad_envelope", "not an envelope: bad_envelope")
# an ssh-keygen key (slice 1's node key) signs and verifies
d = tempfile.mkdtemp(); kp = os.path.join(d, "k")
subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "host:x", "-f", kp], check=True)
ptext = open(kp).read(); pline = open(kp + ".pub").read().strip()
ok(E.public_of_private(ptext, "host:x") == pline, "an ssh-keygen key loads; its public line matches")
fwd = E.sign(E.forward(env, {"principal": "agent:helper", "node": "server:57"}, {"agent": "demo", "node": "server:57"}, "t_1"), "server:57", ptext)
ok(E.verify(fwd, {"server:57": pline, "desk:42": pub}, "server:57", E.Nonces()) == (True, None, None) and fwd["id"] == env["id"] and fwd["chain"][-1]["principal"] == "agent:helper" and fwd["originator"] == env["originator"], "forward: the same id and originator, the chain extended, the parent verified")
fwdbad = dict(fwd, parent=dict(fwd["parent"], purpose="tampered")); fwdbad = E.sign(fwdbad, "server:57", ptext)
ok(E.verify(fwdbad, {"server:57": pline, "desk:42": pub})[1] == "bad_signature", "a forwarded envelope whose parent was tampered: bad_signature")
fwdid = dict(fwd, id="env_" + "0" * 24); fwdid = E.sign(fwdid, "server:57", ptext)
ok(E.verify(fwdid, {"server:57": pline, "desk:42": pub})[1] == "bad_envelope", "a forwarded envelope with another id: bad_envelope")
# the keys cache
kp2 = os.path.join(d, "keys.json")
K = E.Keys(kp2); K.save({"fetched_at": E.utc(), "coordinator": {"public_key": pline}, "keys": [{"node": "desk:42", "public_key": pub}]})
ok(E.Keys(kp2).table() == {"desk:42": pub, "coordinator": pline} and E.Keys(kp2).load() and E.Keys(kp2).age() < 5, "the keys cache round-trips, the coordinator included")
# the policy
ok(E.accepts(["org"], None, {"principal": "user:ed"}) and not E.accepts(["org"], None, {}), "accept_from org: any originator with a principal")
ok(E.accepts([], "user:ed", {"principal": "user:ed"}) and not E.accepts([], "user:ed", {"principal": "user:x"}), "accept_from empty: the owner only")
ok(E.accepts(["node:desk"], None, {"principal": "u", "node": "desk:1"}) and not E.accepts(["node:server"], None, {"principal": "u", "node": "desk:1"}), "accept_from node:KIND")
ok(E.accepts(["dept:3"], None, {"principal": "u", "departments": [3]}) and not E.accepts(["dept:3"], None, {"principal": "u"}), "accept_from dept:N needs the originator's departments")
ok(E.accepts(["agent:me"], None, {"principal": "agent:me"}) and E.accepts(["user:ed"], None, {"principal": "user:ed"}), "accept_from a principal")
ok(E.classification_within("internal", "internal") and not E.classification_within("restricted", "internal") and E.classification_within("restricted", None) and E.classification_within("prohibited", "prohibited"), "the classification ceiling")
ok(E.needs_approval(["restricted"], {"authority": {"classification": "restricted"}}) and not E.needs_approval(["restricted"], {"authority": {"classification": "internal"}}) and E.needs_approval(["user:stranger"], {"originator": {"principal": "user:stranger"}}) and not E.needs_approval([], {}), "approve: by classification or originator")
print("\n" + ("PASS" if fails == 0 else f"FAIL ({fails})"))
sys.exit(0 if fails == 0 else 1)
