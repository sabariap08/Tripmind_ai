"""Add the PWA tags and the pwa.js loader to every page (idempotent).

Run:  python scripts/add_pwa_tags.py   (from the backend directory)
Inserts into <head>:  theme-color, manifest link, icons, web-app metas.
Inserts before </body>: the pwa.js loader (service worker + install banner).
Absolute paths (/js/pwa.js, /manifest.json) so it works from both the
frontend root and /pages/.
"""
import io
import os

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(BACKEND, "..", "frontend")

HEAD_BLOCK = """    <meta name="theme-color" content="#f59e0b">
    <link rel="manifest" href="/manifest.json">
    <link rel="icon" type="image/png" sizes="32x32" href="/img/favicon-32.png">
    <link rel="apple-touch-icon" href="/img/apple-touch-icon.png">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="default">
    <meta name="apple-mobile-web-app-title" content="TripMind AI">
"""

BODY_TAG = '    <script src="/js/pwa.js" defer></script>\n'

pages = []
for folder in (FRONTEND, os.path.join(FRONTEND, "pages")):
    for name in sorted(os.listdir(folder)):
        if name.endswith(".html"):
            pages.append(os.path.join(folder, name))

for path in pages:
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        src = fh.read()
    original = src
    changed = []

    if 'rel="manifest"' not in src:
        if "</head>" not in src:
            print("SKIP (no </head>): %s" % path)
            continue
        src = src.replace("</head>", HEAD_BLOCK + "</head>", 1)
        changed.append("head")

    if "/js/pwa.js" not in src:
        if "</body>" not in src:
            print("SKIP (no </body>): %s" % path)
            continue
        src = src.replace("</body>", BODY_TAG + "</body>", 1)
        changed.append("body")

    if src != original:
        with io.open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(src)
    rel = os.path.relpath(path, FRONTEND)
    print("%-28s %s" % (rel, ", ".join(changed) if changed else "already had tags"))
