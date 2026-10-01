"""Live HTTP probe: encoding, endpoints, encoding of trip summary strings."""
import sys, os, json, urllib.request, urllib.error
sys.stdout.reconfigure(encoding='utf-8')
BASE = os.environ.get('TM_BASE', 'http://127.0.0.1:5055')


def req(path, method='GET', body=None, token=None, raw=False):
    url = BASE + path
    data = json.dumps(body).encode('utf-8') if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    if data:
        r.add_header('Content-Type', 'application/json; charset=utf-8')
    if token:
        r.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            b = resp.read()
            return resp.status, dict(resp.headers), b
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except Exception as e:
        return 0, {}, str(e).encode()


def main():
    print('== 1. static asset content-types ==')
    for p in ['/index.html', '/pages/trip.html', '/js/api.js', '/js/portal.js',
              '/css/theme.css', '/manifest.json', '/sw.js', '/js/pwa.js',
              '/tripmind-partner/index.html', '/tripmind-partner/css/partner.css',
              '/tripmind-partner/js/register.js']:
        st, h, b = req(p)
        print('  %-45s %s  CT=%-38s len=%s' % (p, st, h.get('Content-Type'), len(b)))

    print('\n== 2. login ==')
    st, h, b = req('/api/auth/login', 'POST', {'email': 'admin@tripmind.com', 'password': 'admin@123'})
    print('  status', st, 'CT', h.get('Content-Type'))
    print('  raw head:', b[:200])
    tok = None
    try:
        j = json.loads(b.decode('utf-8'))
        tok = j.get('token') or (j.get('user') or {}).get('token')
        print('  token?', bool(tok), 'keys', list(j.keys()))
    except Exception as e:
        print('  decode err', e)
    if not tok:
        # try passenger
        st, h, b = req('/api/auth/login', 'POST', {'email': 'passenger@tripmind.com', 'password': 'password'})
        print('  pax login', st, b[:200])
        try:
            tok = json.loads(b.decode('utf-8')).get('token')
        except Exception:
            tok = None
    print('  have token:', bool(tok))
    if not tok:
        return

    print('\n== 3. trips list -> check for mojibake in payload ==')
    st, h, b = req('/api/trips', token=tok)
    print('  status', st, 'CT', h.get('Content-Type'))
    txt = b.decode('utf-8', errors='replace')
    print('  decoded-as-utf8 len', len(txt))
    bad = [m for m in ('\u00e2\u20ac', '\u00c2\u00b7', '\u00ef\u00bf\u00bd') if m in txt]
    print('  mojibake markers when decoded as UTF-8:', bad)
    # now simulate decoding as cp1252 (the browser bug)
    try:
        cp = b.decode('cp1252')
    except Exception as e:
        cp = 'ERR ' + str(e)
    print('  if decoded as cp1252, contains a-circumflex-euro?:', '\u00e2\u20ac' in cp)
    for m in ('\u00e2\u20ac', '\u00c2\u00b7'):
        i = cp.find(m)
        if i >= 0:
            print('    sample cp1252 ->', repr(cp[max(0, i-40):i+40]))
    try:
        j = json.loads(txt)
        trips = j.get('trips') if isinstance(j, dict) else j
        print('  trips:', len(trips) if trips else 0)
        if trips:
            t = trips[0]
            print('  trip id', t.get('_id'), t.get('destination'), t.get('startDate'), t.get('endDate'))
    except Exception as e:
        print('  json err', e)

    print('\n== 4. spot / destination endpoints used by home page ==')
    for p in ['/api/tourist/list', '/api/tourist/spots', '/api/destinations', '/api/tourist/destinations',
              '/api/hotels/list', '/api/transport/list', '/api/admin/approval',
              '/api/auth/registration-fields', '/api/auth/partner-types', '/api/partner/types']:
        st, h, b = req(p, token=tok)
        print('  %-38s -> %s  %s' % (p, st, b[:160]))

    print('\n== 5. passkey endpoints ==')
    for p in ['/api/passengers', '/api/passengers/me', '/api/users/passengers',
              '/api/checklists', '/api/trips/x/checklist', '/api/ml/models',
              '/api/ratings', '/api/ml/insights', '/api/assistant/chat']:
        st, h, b = req(p, token=tok)
        print('  %-38s -> %s  %s' % (p, st, b[:140]))


if __name__ == '__main__':
    main()
