import sys, os, re
sys.stdout.reconfigure(encoding='utf-8')
p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'frontend', 'pages', 'trip.html')
raw = open(p, 'rb').read()
print('file size', len(raw))
print('BOM?', raw[:3] == b'\xef\xbb\xbf')
# find the trip summary line
idx = raw.find(b'traveller')
while idx != -1 and idx < len(raw):
    seg = raw[max(0, idx-260):idx+60]
    if b'startDate' in seg:
        print('\nBYTES around summary:')
        print(repr(seg))
        break
    idx = raw.find(b'traveller', idx+1)
# check for any non-ascii byte sequences
non_ascii = [(i, raw[i]) for i in range(len(raw)) if raw[i] > 127]
print('\nnon-ascii byte count:', len(non_ascii))
print('first 40 non-ascii:', non_ascii[:40])
try:
    raw.decode('utf-8')
    print('decodes as strict UTF-8: YES')
except UnicodeDecodeError as e:
    print('decodes as strict UTF-8: NO ->', e)
