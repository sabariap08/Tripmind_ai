"""Add the PWA tags and the pwa.js loader to every page (idempotent).

Run:  python scripts/add_pwa_tags.py   (from the backend directory)
Inserts into <head>:  theme-color, manifest link, icons, web-app metas.
Inserts before </body>: the pwa.js loader (service worker + install banner).
Absolute paths (/js/pwa.js, /manifest.json) so it works from both the
frontend root and /pages/.
"""
import io
import os
import re

# A deferred ui.js tag from an earlier run (any relative or absolute spelling).
RE_DEFERRED_UI = re.compile(r'[ \t]*<script src="(?:\.\./|/|\.)?js/ui\.js"[^>]*defer[^>]*>\s*</script>\s*\n?', re.I)

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(BACKEND, "..", "frontend")

HEAD_BLOCK = """    <meta name="theme-color" content="#06202b">
    <link rel="manifest" href="/manifest.json">
    <link rel="icon" type="image/png" sizes="32x32" href="/img/favicon-32.png">
    <link rel="apple-touch-icon" href="/img/apple-touch-icon.png">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="TripMind AI">
    <link rel="apple-touch-startup-image" href="/img/splash/splash-1290x2796.jpg">
    <link rel="apple-touch-startup-image" href="/img/splash/splash-1170x2532.jpg">
    <link rel="apple-touch-startup-image" href="/img/splash/splash-828x1792.jpg">
"""

BODY_TAG = '    <script src="/js/pwa.js" defer></script>\n'

HEAD_SPLASH = """    <link rel="apple-touch-startup-image" href="/img/splash/splash-1290x2796.jpg">
    <link rel="apple-touch-startup-image" href="/img/splash/splash-1170x2532.jpg">
    <link rel="apple-touch-startup-image" href="/img/splash/splash-828x1792.jpg">
"""

pages = []
# (folder, asset prefix from that folder back to the frontend root)
folders = [
    (FRONTEND, ""),
    (os.path.join(FRONTEND, "pages"), "../"),
    (os.path.join(FRONTEND, "tripmind-partner"), "../"),
]
for folder, _prefix in folders:
    if not os.path.isdir(folder):
        continue
    for name in sorted(os.listdir(folder)):
        if name.endswith(".html"):
            pages.append((os.path.join(folder, name), _prefix))

for path, prefix in pages:
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
    else:
        # Upgrade pages tagged by an earlier run: rebrand theme colour, dark
        # status bar and add the branded iOS launch images.
        if 'content="#f59e0b"' in src:
            src = src.replace('content="#f59e0b"', 'content="#06202b"')
            changed.append("theme-color")
        if 'apple-mobile-web-app-status-bar-style" content="default"' in src:
            src = src.replace('apple-mobile-web-app-status-bar-style" content="default"',
                              'apple-mobile-web-app-status-bar-style" content="black-translucent"')
            changed.append("status-bar")
        if "apple-touch-startup-image" not in src:
            anchor = '    <meta name="apple-mobile-web-app-title" content="TripMind AI">\n'
            if anchor in src:
                src = src.replace(anchor, anchor + HEAD_SPLASH, 1)
                changed.append("splash")

    if "/js/pwa.js" not in src:
        if "</body>" not in src:
            print("SKIP (no </body>): %s" % path)
            continue
        src = src.replace("</body>", BODY_TAG + "</body>", 1)
        changed.append("body")

    # Brand: the design system layer + the shared UI runtime.
    # portal.html owns its own dense console styles and uses none of the
    # tm-* components, so the traveller design system is not injected there.
    own_design_system = os.path.basename(path) == "portal.html"
    if "css/theme.css" not in src and not own_design_system:
        src = src.replace("</head>", '    <link rel="stylesheet" href="%scss/theme.css">\n</head>' % prefix, 1)
        changed.append("theme")

    # The shared runtime must be available to the page's own inline scripts, so
    # it is loaded synchronously in <head> (ui.js is an IIFE that defers its
    # DOM hooks to DOMContentLoaded).  Earlier runs added it with `defer` at the
    # end of <body>, which left TM undefined for inline page scripts.
    ui_src = "%sjs/ui.js" % prefix
    src, n_removed = RE_DEFERRED_UI.subn("", src)
    if n_removed:
        changed.append("ui.js->head")
    if "js/ui.js" not in src:
        src = src.replace("</head>", '    <script src="%s"></script>\n</head>' % ui_src, 1)
        changed.append("ui.js")

    if src != original:
        with io.open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(src)
    rel = os.path.relpath(path, FRONTEND)
    print("%-28s %s" % (rel, ", ".join(changed) if changed else "already had tags"))
