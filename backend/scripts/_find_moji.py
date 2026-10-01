import sys, glob, os
sys.stdout.reconfigure(encoding='utf-8')
pats = ['\u00e2\u20ac', '\u00c2\u00b7', '\u00c2\u00a0', '\u00ef\u00bf\u00bd', '\u00c3\u00a2', '\u00e2\u0080', '\u00e2\u2019', '\u00e2\u201c']
base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
roots = [os.path.join(base, 'frontend'), os.path.join(base, 'backend')]
exts = ('.html', '.js', '.css', '.py', '.json')
n = 0
for root in roots:
    for dp, dn, fn in os.walk(root):
        if 'node_modules' in dp or '__pycache__' in dp:
            continue
        for f in fn:
            if not f.endswith(exts):
                continue
            p = os.path.join(dp, f)
            try:
                s = open(p, encoding='utf-8', errors='replace').read()
            except Exception:
                continue
            for i, line in enumerate(s.split('\n'), 1):
                if any(x in line for x in pats):
                    n += 1
                    print('%s:%d: %s' % (os.path.relpath(p, base), i, line.strip()[:170]))
                    break
print('TOTAL MOJIBAKE LINES:', n)
