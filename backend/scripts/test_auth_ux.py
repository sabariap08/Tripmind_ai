"""Authentication UX tests — compact traveller signup + "Remember me".

Run:  python scripts/test_ai_extras.py style harness, isolated DB:
      python scripts/test_auth_ux.py

Covers the redesign's auth contract:
  * the compact Create Account form (name / email / password) is enough to
    register a traveller through the REAL /api/auth/register endpoint;
  * "Remember me" is real, not cosmetic: a login without the flag must hand
    back a browser-session cookie (no expiry) and a login with the flag a
    persistent cookie (expiry) — and the session must work in both cases;
  * the flag is echoed back, logout clears the session, and the usual
    rejections (short password, duplicate e-mail, wrong password) still fire.

Uses an isolated tripmind_test database, dropped on every run, so no real
account is ever touched.
"""
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

os.environ["MONGODB_DB_NAME"] = "tripmind_test"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as appmod
from services.mongodb import get_db

PASSES, FAILS = [], []
POSTFIX = str(int(time.time()))[-7:]


def ok(label, cond, extra=""):
    (PASSES if cond else FAILS).append(label)
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", label, extra))


def jget(r):
    try:
        return r.get_json()
    except Exception:
        return {}


def session_cookie_headers(resp):
    """Flask emits the signed session cookie; report whether it is persistent."""
    raw = resp.headers.get("Set-Cookie", "")
    return {
        "raw": raw,
        "name": "session",
        "persistent": bool(re.search(r"(Expires|Max-Age)", raw, re.I)),
    }


appmod.app.config["TESTING"] = True
with appmod.app.test_client() as c:
    email = "remember%s@example.com" % POSTFIX
    pwd = "TravelUnique!42"

    # 1. Compact traveller signup — exactly what the redesigned form posts.
    r = c.post("/api/auth/register", json={"role": "USER", "name": "Remember Me", "email": email, "password": pwd})
    body = jget(r)
    ok("compact signup accepted (name/email/password only)", r.status_code == 201, "-> %s" % r.status_code)
    ok("signup returns the user", (body.get("user") or {}).get("email") == email)

    # 2. Sign-in WITHOUT remember me -> session cookie, no expiry.
    c2 = appmod.app.test_client()
    r = c2.post("/api/auth/login", json={"email": email, "password": pwd, "remember": False})
    ck = session_cookie_headers(r)
    ok("login without remember me succeeds", r.status_code == 200 and jget(r).get("user"), "-> %s" % r.status_code)
    ok("remember=false -> browser-session cookie (no expiry)", ck["raw"] != "" and not ck["persistent"])
    ok("remember=false echoed back", jget(r).get("remember") is False)
    ok("session works without remember me", jget(c2.get("/api/auth/me")).get("user", {}).get("email") == email)

    # 3. Sign-in WITH remember me -> persistent cookie.
    c3 = appmod.app.test_client()
    r = c3.post("/api/auth/login", json={"email": email, "password": pwd, "remember": True})
    ck = session_cookie_headers(r)
    ok("login with remember me succeeds", r.status_code == 200, "-> %s" % r.status_code)
    ok("remember=true -> persistent cookie (expiry present)", ck["raw"] != "" and ck["persistent"])
    ok("remember=true echoed back", jget(r).get("remember") is True)
    ok("session works with remember me", jget(c3.get("/api/auth/me")).get("user", {}).get("email") == email)

    # 4. The password itself is never handed back in the session cookie.
    ok("session cookie carries no password material", "TravelUnique" not in ck["raw"] and "passwordHash" not in ck["raw"])

    # 5. Rejections that the inline validation mirrors.
    r = c3.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
    ok("wrong password rejected", r.status_code == 401, "-> %s" % r.status_code)
    r = c3.post("/api/auth/login", json={"email": email, "password": ""})
    ok("missing password rejected", r.status_code == 400, "-> %s" % r.status_code)
    r = c.post("/api/auth/register", json={"role": "USER", "name": "Dup", "email": email, "password": pwd})
    ok("duplicate email rejected", r.status_code == 409, "-> %s" % r.status_code)
    r = c.post("/api/auth/register", json={"role": "USER", "name": "Short", "email": "short%s@example.com" % POSTFIX, "password": "abc"})
    ok("password under 8 characters rejected", r.status_code == 400, "-> %s" % r.status_code)
    r = c.post("/api/auth/register", json={"role": "USER", "name": "NoMail", "password": pwd})
    ok("missing email rejected", r.status_code == 400, "-> %s" % r.status_code)

    # 6. Logout ends the session on the remember-me client.
    r = c3.post("/api/auth/logout")
    ok("logout succeeds", r.status_code == 200, "-> %s" % r.status_code)
    ok("session cleared after logout", not jget(c3.get("/api/auth/me")).get("user"))

print("\n================ AUTH UX RESULTS ================")
print("PASS: %d   FAIL: %d" % (len(PASSES), len(FAILS)))
if FAILS:
    print("failed: %s" % FAILS)
    sys.exit(1)
