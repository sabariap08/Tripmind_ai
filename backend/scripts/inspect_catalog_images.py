"""Show what imagery the catalogue is currently pointing at.

Run before/after ``backfill_place_images.py`` to see what actually changed:

    python scripts/inspect_catalog_images.py
    python scripts/inspect_catalog_images.py --city Chennai
    python scripts/inspect_catalog_images.py --check-links

``--check-links`` issues a real HEAD request per image. A cached Commons URL
that has since been renamed returns 404, and a 404 in an <img> is a broken
card, so this is worth running after a backfill.
"""
import argparse
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.mongodb import get_collection  # noqa: E402
from services import geo_match  # noqa: E402

COLLECTIONS = ("tourist_spots", "hotels", "restaurants", "tours", "guide_locations")
HEADERS = {"User-Agent": "TripMindAI/1.0 (link check)"}


def _images(doc):
    return [i for i in (doc.get("images") or []) if isinstance(i, str) and i.strip()]


def _check(url):
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read(1)
            return resp.status, resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, str(exc)


def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default=None, help="limit to one city")
    ap.add_argument("--full", action="store_true", help="print every image URL")
    ap.add_argument("--check-links", action="store_true", help="HTTP GET each image")
    args = ap.parse_args()

    total = 0
    links = 0
    bad = []
    for name in COLLECTIONS:
        query = geo_match.place_query(args.city) if args.city else {}
        docs = list(get_collection(name).find(query))
        if not docs:
            continue
        print("\n%s (%d)" % (name, len(docs)))
        for doc in docs:
            imgs = _images(doc)
            total += 1
            print("  %-40s images=%d  imageSource=%s" % (
                (doc.get("name") or "?")[:40], len(imgs),
                doc.get("imageSource") or "-"))
            shown = imgs if args.full else imgs[:2]
            for url in shown:
                if args.check_links:
                    links += 1
                    status, ctype = _check(url)
                    flag = "ok " if status == 200 else "BAD"
                    if status != 200:
                        bad.append((doc.get("name"), url, status, ctype))
                    print("      [%s %s %s] %s" % (flag, status, ctype[:24], url[:100]))
                else:
                    print("      %s" % url[:110])
            if len(shown) < len(imgs):
                print("      ... +%d more" % (len(imgs) - len(shown)))

    if args.check_links:
        print("\n%d links checked, %d failed." % (links, len(bad)))
        for name, url, status, ctype in bad:
            print("  %-40s %s %s" % (name, status, ctype))
            print("      %s" % url)
    print("\n%d listings inspected." % total)
    return 1 if bad else 0


if __name__ == "__main__":
    _main()
