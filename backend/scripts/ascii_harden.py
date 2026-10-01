"""Rewrite non-ASCII characters in frontend sources as \\uXXXX escapes.

Why: every mojibake report in TripMind came from a non-ASCII byte in an HTML/JS
source file being decoded with the wrong charset somewhere in the delivery
chain (proxy, disk, editor, SW cache). A JS string escape is pure ASCII in the
file, so it is immune to that entire failure class: the character can only be
mis-decoded *after* the JS engine has already produced the right code point.

Run:  python scripts/ascii_harden.py [--check]
"""
from __future__ import print_function

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND = os.path.join(ROOT, 'frontend')
EXTS = ('.html', '.js', '.css', '.json', '.webmanifest')

SKIP_DIRS = {'node_modules', '.git', '__pycache__', 'img', 'splash'}

# Characters we intentionally keep in the tree: none. Everything becomes an
# escape so the sources are pure 7-bit ASCII.
CTRL_MAP = {
    '\u00a0': '\\u00a0',   # nbsp
}


def files():
    for dirpath, dirnames, filenames in os.walk(FRONTEND):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name.lower().endswith(EXTS):
                yield os.path.join(dirpath, name)


def escape_char(ch):
    return '\\u%04x' % ord(ch)


def convert(text):
    """Replace every non-ASCII char with a \\uXXXX escape.

    Inside a CSS/HTML text node an escape is NOT interpreted, so those files are
    converted to numeric HTML entities / CSS escapes instead.
    """
    return ''.join(escape_char(c) if ord(c) > 127 else c for c in text)


def convert_html(text):
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ord(ch) < 128:
            out.append(ch)
            i += 1
            continue
        # Inside a <script> block a \uXXXX escape is understood by the JS engine.
        script = text.rfind('<script', 0, i)
        script_end = text.rfind('</script>', 0, i)
        in_script = script > script_end
        if in_script:
            out.append(escape_char(ch))
        else:
            # HTML text node / attribute: numeric character reference.
            out.append('&#%d;' % ord(ch))
        i += 1
    return ''.join(out)


def convert_css(text):
    out = []
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
        elif ch in CTRL_MAP:
            out.append(CTRL_MAP[ch])
        else:
            out.append('\\%04x ' % ord(ch))
    return ''.join(out)


def main():
    check = '--check' in sys.argv
    total = 0
    changed = []
    for path in files():
        raw = open(path, 'rb').read()
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            print('!! not valid UTF-8: %s (%s)' % (path, exc))
            continue
        if all(ord(c) < 128 for c in text):
            continue
        total += 1
        low = path.lower()
        if low.endswith('.html'):
            new = convert_html(text)
        elif low.endswith('.css'):
            new = convert_css(text)
        else:
            new = convert(text)
        if new == text:
            continue
        rel = os.path.relpath(path, ROOT)
        changed.append((rel, sum(1 for c in text if ord(c) > 127)))
        if not check:
            with io.open(path, 'w', encoding='utf-8', newline='') as fh:
                fh.write(new)
    print('files with non-ASCII: %d' % total)
    for rel, count in changed:
        print('  %-60s %d chars%s' % (rel, count, '  (check only)' if check else ''))
    if not check and changed:
        print('\nrewrote %d files' % len(changed))
    return 0


if __name__ == '__main__':
    sys.exit(main())
