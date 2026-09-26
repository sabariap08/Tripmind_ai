"""Verify the PWA + mobile assets are actually served by the Flask app.

Run:  python scripts/check_pwa_serving.py
Uses the Flask test client (same routing as production) and fails loudly if a
page, the manifest, the service worker, an icon or the install script is
missing or served with the wrong content type.
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("MONGODB_DB_NAME", "tripmind_test")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as appmod

FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "..", "frontend")

PAGES = ["/", "/index.html", "/login.html", "/register.html", "/portal.html",
         "/pages/dashboard.html", "/pages/planner.html", "/pages/trip.html",
         "/pages/mindmap.html", "/pages/verify.html"]

ASSETS = [
    ("/manifest.json", "application/json"),
    ("/sw.js", "javascript"),
    ("/js/pwa.js", "javascript"),
    ("/css/style.css", "text/css"),
    ("/img/icon-192.png", "image/png"),
    ("/img/icon-512.png", "image/png"),
    ("/img/icon-maskable-512.png", "image/png"),
    ("/img/apple-touch-icon.png", "image/png"),
    ("/img/favicon-32.png", "image/png"),
]

fails = []


def check(label, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def main():
    c = appmod.app.test_client()

    for path in PAGES:
        r = c.get(path)
        body = r.get_data(as_text=True)
        check("page %s" % path, r.status_code == 200 and "</html>" in body,
              "status=%s" % r.status_code)
        check("  %s has manifest link" % path, 'rel="manifest"' in body, "")
        check("  %s loads pwa.js" % path, "/js/pwa.js" in body, "")
        check("  %s has theme-color" % path, 'name="theme-color"' in body, "")
        check("  %s has apple-touch-icon" % path, "apple-touch-icon" in body, "")

    for path, ctype in ASSETS:
        r = c.get(path)
        got = (r.headers.get("Content-Type") or "").split(";")[0]
        check("asset %s" % path,
              r.status_code == 200 and ctype in got,
              "status=%s type=%s" % (r.status_code, got))

    # The manifest must be valid JSON and every icon it names must be served.
    m = json.loads(c.get("/manifest.json").get_data(as_text=True))
    for icon in m.get("icons", []):
        r = c.get(icon["src"])
        check("manifest icon %s" % icon["src"], r.status_code == 200,
              "status=%s" % r.status_code)
    for sc in m.get("shortcuts", []):
        r = c.get(sc["url"])
        check("manifest shortcut %s" % sc["url"], r.status_code == 200,
              "status=%s" % r.status_code)

    # The service worker must never cache the live API.
    sw = c.get("/sw.js").get_data(as_text=True)
    check("sw.js skips /api/", "'/api/'" in sw, "")
    check("sw.js precaches the shell", "CACHE_VERSION" in sw and "SHELL" in sw, "")

    # The install UI must exist and only show where it can actually work.
    pwa = c.get("/js/pwa.js").get_data(as_text=True)
    for token in ("beforeinstallprompt", "appinstalled", "isStandalone",
                  "Add to Home Screen", "/sw.js"):
        check("pwa.js handles %s" % token, token in pwa, "")

    # Mobile stylesheet must contain the guards that matter.
    css = c.get("/css/style.css").get_data(as_text=True)
    for token in ("@media (pointer: coarse)", "env(safe-area-inset-bottom)",
                  "overflow-x: hidden", "font-size: 16px", ".pwa-install",
                  "max-width: 480px"):
        check("css has %r" % token, token in css, "")
    check("css braces balanced",
          css.count("{") == css.count("}"),
          "%d/%d" % (css.count("{"), css.count("}")))

    # Every page must declare a mobile viewport.
    for path in PAGES:
        body = c.get(path).get_data(as_text=True)
        check("viewport meta on %s" % path, 'name="viewport"' in body, "")

    print("\n%d checks failed" % len(fails))
    for f in fails:
        print("  FAILED: %s" % f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
