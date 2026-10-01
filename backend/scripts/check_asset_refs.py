"""Verify every local asset reference and internal link in the frontend.

Two different kinds of reference get checked, and conflating them is how the
original version of this script reported 34 false positives:

1. **Subresources** - ``<script src>``, ``<link href>``, ``<img src>`` with a
   file extension. These must exist on disk under ``frontend/``. A reference
   that does not exist is a 404 at runtime that static review misses, which is
   how the partner hub's ``js/maps.js`` survived: it looks right next to
   ``js/partner.js`` but resolves into a directory that has no such file.

2. **Extensionless internal links** - ``/tripmind-partner/dashboard`` and
   friends are Flask routes, not files, so "is there a file at this path" is the
   wrong question. These are checked against the app's real ``url_map`` instead.

Run from ``backend/``::

    python scripts/check_asset_refs.py

Exit code 0 when every reference resolves, 1 otherwise.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

FRONTEND = (Path(__file__).resolve().parents[2] / "frontend").resolve()

# Attributes that can point at a subresource we must be able to serve.
ATTR_RE = re.compile(
    r"""(?P<attr>\b(?:src|href)\s*=\s*)(?P<quote>["'])(?P<url>[^"']*)(?P=quote)""",
    re.I,
)

# Schemes / forms that are not local files.
SKIP_PREFIXES = (
    "http://",
    "https://",
    "//",
    "data:",
    "mailto:",
    "tel:",
    "javascript:",
    "blob:",
    "about:",
)

# A path that ends in a dot-something is a file, not a route. Anything else
# without an extension is a route. Note the optional leading slash: relative
# references such as "dashboard.html" have no slash but are still files.
HAS_EXTENSION_RE = re.compile(r"(?:^|/)[^/]+\.[A-Za-z0-9]{1,8}$")


def is_local(url: str) -> bool:
    if not url:
        return False
    lowered = url.strip().lower()
    if lowered.startswith(SKIP_PREFIXES):
        return False
    if lowered.startswith("#") or lowered.startswith("?"):
        return False
    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc:
        return False
    return True


def resolve(page: Path, url: str) -> Path:
    path_part = unquote(url.split("#", 1)[0].split("?", 1)[0])
    if not path_part:
        return page
    if path_part.startswith("/"):
        return FRONTEND / path_part.lstrip("/")
    return (page.parent / path_part).resolve()


def load_routes() -> list[re.Pattern[str]]:
    """Compile the app's real ``url_map`` into matchers for internal links.

    Converter rules are kept. An earlier version of this script dropped every
    rule containing a "{", which silently threw away
    ``/tripmind-partner/<path:page>`` - the catch-all that serves the entire
    partner hub - and then reported all 34 partner links as broken. A rule the
    app genuinely does not have is exactly what this check exists to find, so
    the app's own routing table is the only authority we should consult.

    Imported here rather than at module scope so the script still does its
    file-level job when the app cannot be imported (missing credentials, an
    unreachable database at import time, and so on).
    """
    backend = FRONTEND.parent / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    try:
        import app as flask_app  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"note: could not import the app ({exc}); "
              f"extensionless links will be skipped")
        return []

    matchers: list[re.Pattern[str]] = []
    for rule in flask_app.app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        matchers.append(_compile_rule(str(rule.rule)))
    return matchers


def _compile_rule(rule: str) -> re.Pattern[str]:
    """Turn a Werkzeug rule into a regex that matches a concrete request path.

    ``/tripmind-partner/<path:page>`` -> ``^/tripmind-partner(?:/(?P<page>.*))?$``
    ``/api/trips/<trip_id>``         -> ``^/api/trips/(?P<trip_id>[^/]+)$``
    """
    pattern = "^"
    index = 0
    while index < len(rule):
        char = rule[index]
        if char == "<":
            close = rule.find(">", index)
            if close == -1:
                pattern += re.escape(char)
                index += 1
                continue
            converter = rule[index + 1 : close]
            name, _, conv = converter.partition(":")
            if conv.startswith("path:"):
                conv = "path"
            inner = r".+" if conv == "path" else r"[^/]+"
            pattern += f"(?P<{re.sub(r'[^0-9a-zA-Z_]', '', name)}>{inner})"
            index = close + 1
            continue
        if char == "/":
            # A trailing slash is optional when the rule has nothing after it,
            # which is how Flask's strict_slashes behaviour actually behaves.
            if index == len(rule) - 1:
                pattern += "/?"
            else:
                pattern += "/"
            index += 1
            continue
        pattern += re.escape(char)
        index += 1
    pattern += "/?$"
    return re.compile(pattern)


def route_matches(path: str, routes: list[re.Pattern[str]]) -> bool:
    return any(matcher.match(path) for matcher in routes)


def main() -> int:
    pages = sorted(FRONTEND.rglob("*.html"))
    routes = load_routes()
    problems: list[str] = []
    file_refs = 0
    route_refs = 0

    for page in pages:
        text = page.read_text(encoding="utf-8", errors="replace")
        for match in ATTR_RE.finditer(text):
            url = match.group("url")
            if not is_local(url):
                continue
            line = text[: match.start()].count("\n") + 1
            rel_page = page.relative_to(FRONTEND).as_posix()
            path_only = unquote(url.split("#", 1)[0].split("?", 1)[0])

            if not HAS_EXTENSION_RE.search(path_only) and not path_only.endswith("/"):
                # Extensionless: must be a real route, not a file.
                route_refs += 1
                if routes and not route_matches(path_only, routes):
                    problems.append(
                        f"{rel_page}:{line}  link -> {url}  "
                        f"(no route matches {path_only})"
                    )
                continue

            target = resolve(page, url)
            file_refs += 1
            if not target.exists():
                problems.append(
                    f"{rel_page}:{line}  {match.group('attr').strip()} -> {url}"
                    f"  (resolves to {target.relative_to(FRONTEND).as_posix()})"
                )

    print(f"pages scanned  : {len(pages)}")
    print(f"file refs      : {file_refs}")
    print(f"route refs     : {route_refs} (checked against {len(routes)} routes)")
    print(f"broken refs    : {len(problems)}")
    for problem in problems:
        print("  BROKEN  " + problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
