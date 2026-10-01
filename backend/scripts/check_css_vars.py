"""Find CSS custom properties that are referenced but never defined.

An undefined custom property is not a visible error. Per the CSS cascade,
``color: var(--tm-nope)`` makes the *entire declaration* invalid at
computed-value time, so the property silently falls back to whatever it would
have been - usually inherited, i.e. the parent's value or the initial value. A
card that meant to have a white background gets its parent's tint; a border that
meant to be rounded gets sharp corners. Nothing errors and nothing logs.

That is exactly what happened to the partner hub: ``partner.css`` referenced
``--tm-surface``, ``--tm-bg-soft``, ``--tm-r-1`` and ``--tm-r-2``, none of which
the theme ever defined (the theme ships ``--tm-r-xs/sm/md/lg``), so those cards
lost their background and their radius with no diagnostic anywhere.

Every ``var()`` in every sheet is resolved against the union of all custom
property definitions found in the project (a custom property is global once
declared, so order does not matter here). Names used only inside a
``var(--x, fallback)`` second argument are exempt, because the author supplied a
usable default.

Run from ``backend/``::

    python scripts/check_css_vars.py

Exit code 0 when every reference resolves, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FRONTEND = (Path(__file__).resolve().parents[2] / "frontend").resolve()

SHEETS = sorted(FRONTEND.rglob("*.css"))
STYLE_TAGS = sorted(FRONTEND.rglob("*.html"))

# --name : value   (declaration)
DEFINE_RE = re.compile(r"(--[A-Za-z0-9_-]+)\s*:")
# var(--name) or var(--name, fallback) or nested var(--a, var(--b))
VAR_RE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*([,)])")


def collect_definitions() -> set[str]:
    """Every custom property declared anywhere: CSS sheets and inline <style>."""
    defined: set[str] = set()
    sources: list[Path] = list(SHEETS)
    for page in STYLE_TAGS:
        text = page.read_text(encoding="utf-8", errors="replace")
        for block in re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I):
            defined.update(DEFINE_RE.findall(block))
    for sheet in sources:
        text = sheet.read_text(encoding="utf-8", errors="replace")
        # Strip comments so a name mentioned in prose is not a definition.
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        defined.update(DEFINE_RE.findall(text))
    return defined


def used_names_with_fallback(text: str) -> list[tuple[str, bool]]:
    """Return (name, has_fallback) for every var() reference in order."""
    found: list[tuple[str, bool]] = []
    for match in re.finditer(r"var\(", text):
        # Walk to this var()'s own argument list rather than trusting a regex
        # over the whole file, so nesting and multi-line fallbacks work.
        #
        # match.end() is the index just past "var(", i.e. the first character
        # of the argument itself. Starting at match.start() + 3 would point at
        # the "(" and immediately raise depth, so the matching ")" would look
        # like a nested close and the scan would run to end-of-file.
        depth = 0
        index = match.end()
        arg: list[str] = []
        saw_top_level_comma = False
        while index < len(text):
            char = text[index]
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
            elif char == "," and depth == 0:
                saw_top_level_comma = True
                break
            arg.append(char)
            index += 1
        raw = "".join(arg)
        name_match = re.match(r"\s*(--[A-Za-z0-9_-]+)", raw)
        if name_match:
            found.append((name_match.group(1), saw_top_level_comma))
    return found


def main() -> int:
    defined = collect_definitions()
    problems: list[str] = []
    checked = 0

    targets: list[tuple[str, str]] = []
    for sheet in SHEETS:
        text = sheet.read_text(encoding="utf-8", errors="replace")
        targets.append((sheet.relative_to(FRONTEND).as_posix(),
                        re.sub(r"/\*.*?\*/", "", text, flags=re.S)))
    for page in STYLE_TAGS:
        text = page.read_text(encoding="utf-8", errors="replace")
        for index, block in enumerate(
            re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I)
        ):
            rel = f"{page.relative_to(FRONTEND).as_posix()} <style #{index + 1}>"
            targets.append((rel, block))

    for label, text in targets:
        for name, has_fallback in used_names_with_fallback(text):
            if has_fallback:
                continue
            checked += 1
            if name not in defined:
                line = text[: text.find(name)].count("\n") + 1
                problems.append(f"{label}:{line}  var({name}) is never defined")

    print(f"sheets scanned     : {len(SHEETS)} + inline <style> blocks")
    print(f"custom props known : {len(defined)}")
    print(f"refs checked       : {checked} (fallback-bearing refs skipped)")
    print(f"undefined refs     : {len(problems)}")
    for problem in sorted(set(problems)):
        print("  UNDEFINED  " + problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
