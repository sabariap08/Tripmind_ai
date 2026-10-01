"""Repair mojibake that is stored *encoded* in the source.

The first hardening pass (ascii_harden.py) only catches raw non-ASCII bytes.
That was not enough, and it is worth being precise about why.

Some mojibake in TripMind is not stored as raw bytes. A previous "encoding fix"
pass ran over the files and escaped whatever bytes it found, which preserved the
corruption perfectly while making it look clean:

    JS     ' \\u00c2\\u00b7 '   -> renders as " Â· "
    HTML   '&#226;&#8364;&#8221;' -> renders as " â€" "

Every character in those literals is plain ASCII, so a non-ASCII scan finds
nothing, `node --check` passes, and the page still shows garbage. This pass
decodes the escapes first, repairs the text, and re-escapes it.

Repair is provably safe
-----------------------
A run of mojibake is by definition UTF-8 bytes that were decoded as
Windows-1252. So re-encoding the run with cp1252 and decoding it as UTF-8
recovers the original text. A *correct* character (a real middle dot, a real
en dash) is a lone code point whose cp1252 byte is not a valid UTF-8 sequence,
so the decode raises and the run is left alone. As a second guard a run is only
accepted when the repaired text no longer contains a mojibake lead character.

Run:  python scripts/fix_encoded_mojibake.py [--check]
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

# Characters that begin a run of double-encoded UTF-8 (the first byte of a
# multi-byte sequence mis-decoded as cp1252). Present => likely mojibake.
LEAD = set('\u00c2\u00c3\u00e0\u00e1\u00e2\u00e3\u00e4\u00e5'
           '\u00f0\u00f1\u00f2\u00f3\u00f4\u00f5'
           '\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192')

RUN_RE = re.compile('[^\x00-\x7f]+')
JS_ESCAPE_RE = re.compile(r'\\u([0-9a-fA-F]{4})')
HTML_DEC_RE = re.compile(r'&#(?:[xX]([0-9a-fA-F]+)|([0-9]+));')


def _repair_once(text):
    """Undo one round of UTF-8-read-as-cp1252 over every non-ASCII run."""
    out = []
    last = 0
    hits = 0
    for m in RUN_RE.finditer(text):
        run = m.group(0)
        if not (set(run) & LEAD):
            continue
        try:
            fixed = run.encode('cp1252').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if fixed == run or (set(fixed) & LEAD):
            continue
        out.append(text[last:m.start()])
        out.append(fixed)
        last = m.end()
        hits += 1
    out.append(text[last:])
    return ''.join(out), hits


def repair(text, rounds=3):
    total = 0
    for _ in range(rounds):
        text, hits = _repair_once(text)
        if not hits:
            break
        total += hits
    return text, total


def process_js_like(text):
    """Decode \\uXXXX escapes, repair, re-escape. Net result stays ASCII."""
    decoded = JS_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), text)
    fixed, hits = repair(decoded)
    if not hits:
        return text, 0
    # Re-escape only what actually changed region plus any raw non-ASCII, so
    # the file is ASCII again and immune to a later mis-decode.
    out = ''.join(c if ord(c) < 0x80 else '\\u%04x' % ord(c) for c in fixed)
    return out, hits


def process_html(text):
    """Decode numeric character references, repair, re-encode."""
    decoded = HTML_DEC_RE.sub(
        lambda m: chr(int(m.group(1), 16) if m.group(1) else int(m.group(2))), text)
    fixed, hits = repair(decoded)
    if not hits:
        return text, 0
    out = ''.join(c if ord(c) < 0x80 else '&#%d;' % ord(c) for c in fixed)
    return out, hits


def strip_bom(text):
    """Remove a real U+FEFF and a literal '\\ufeff' escape left at the head.

    A leading BOM is stripped by every HTML/JS loader, but a *literal* escape
    sequence at file scope is a syntax error the moment the file is parsed, so
    both forms have to go.
    """
    if text.startswith('\ufeff'):
        text = text[1:]
    while text.startswith('\\ufeff'):
        text = text[6:]
    return text


def files():
    for dirpath, dirnames, filenames in os.walk(FRONTEND):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name.lower().endswith(EXTS):
                yield os.path.join(dirpath, name)


def main():
    check = '--check' in sys.argv
    changed = []
    for path in files():
        raw = open(path, 'rb').read()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            print('!! not valid UTF-8: %s (%s)' % (path, exc))
            continue
        had_bom = raw[:3] == b'\xef\xbb\xbf'
        low = path.lower()
        if low.endswith('.html'):
            new, hits = process_html(text)
        else:
            new, hits = process_js_like(text)
        # Decoding escapes can turn a literal '\\ufeff' at the head into a real
        # BOM (or vice versa); neither belongs at file scope.
        cleaned = strip_bom(new)
        if cleaned != new:
            hits += 1
            new = cleaned
        if new == text and not had_bom:
            continue
        rel = os.path.relpath(path, ROOT)
        changed.append((rel, hits, ' +BOM' if had_bom else ''))
        if not check:
            with io.open(path, 'w', encoding='utf-8', newline='') as fh:
                fh.write(new)
    if changed:
        print('repaired %d file(s):' % len(changed))
        for rel, hits, extra in changed:
            print('  %-58s %d run(s)%s%s' % (rel, hits, extra, '  (check only)' if check else ''))
    else:
        print('no encoded mojibake found')
    return 0


if __name__ == '__main__':
    sys.exit(main())
