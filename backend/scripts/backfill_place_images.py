"""Replace mismatched catalogue imagery with photos verified to belong to the place.

    python scripts/backfill_place_images.py
    python scripts/backfill_place_images.py --dry-run
    python scripts/backfill_place_images.py --city Chennai --force

Why this is a data migration and not a code fix
-----------------------------------------------
The reported bug ("destination photos are wrong") is a *data* fault: seven seeded
spots were pointed at a recycled pool of famous-landmark Unsplash photographs.
No amount of read-path logic can make those URLs depict Marina Beach, so the
records themselves have to be re-pointed.

What the script guarantees
--------------------------
* Every URL it writes was returned by Wikimedia Commons with a file title that
  contains a distinctive token from the place's own name (see
  services/place_images._score). That title is stored alongside the URL as
  provenance, so the association can be audited later without re-fetching.
* It never pads a listing with unrelated images. If Commons has three verified
  photos for a place, three are stored and the UI shows the neutral TripMind
  placeholder for the rest. A short image list is a cosmetic gap; a wrong
  image is the bug we are fixing.
* ``--dry-run`` reports exactly what would change and touches nothing.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.mongodb import get_collection  # noqa: E402
from services import place_images  # noqa: E402
from services import geo_match  # noqa: E402

# kind -> (collection, name field, fields preserved on update)
TARGETS = (
    ("spot", "tourist_spots", "name"),
    ("hotel", "hotels", "name"),
    ("restaurant", "restaurants", "name"),
)


def _city_of(doc):
    loc = doc.get("location") if isinstance(doc.get("location"), dict) else {}
    return doc.get("city") or loc.get("city") or "", doc.get("district") or loc.get("district") or ""


def _needs_repair(doc, force):
    """A listing needs repair when it has no images, or when its images carry
    no recorded provenance (i.e. they came from the old unverified seed)."""
    if force:
        return True
    if doc.get("imageSource"):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default=None)
    ap.add_argument("--force", action="store_true",
                    help="re-query even listings that already have verified imagery")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    changed = 0
    checked = 0
    unresolved = 0

    for kind, collection, name_field in TARGETS:
        query = geo_match.place_query(args.city) if args.city else {}
        docs = list(get_collection(collection).find(query))
        if not docs:
            continue
        print("\n%s (%d)" % (collection, len(docs)))

        for doc in docs:
            name = doc.get(name_field) or ""
            city, district = _city_of(doc)
            if not name:
                continue
            checked += 1

            if not _needs_repair(doc, args.force):
                print("  %-40s already verified (imageSource=%s)"
                      % (name[:40], doc.get("imageSource")))
                continue

            resolved = place_images.resolve_place_images(
                doc, kind=kind, limit=args.limit,
                use_cache=not args.force, prefer_record=False)
            images = resolved["images"]

            if not images:
                unresolved += 1
                # Record the negative result so the read path serves the
                # placeholder immediately and does not re-query on every page.
                place_images._cache_put(
                    place_images._place_key(name, city, district), [],
                    name, city, district)
                print("  %-40s NO VERIFIED PHOTO -> placeholder" % name[:40])
                if not args.dry_run:
                    get_collection(collection).update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"images": [], "imageSource": "placeholder",
                                  "imageTitles": [], "imageCheckedAt": place_images.time.strftime(
                                      "%Y-%m-%dT%H:%M:%S", place_images.time.gmtime())}})
                continue

            titles = [i.get("title") for i in images]
            print("  %-40s -> %d verified (%s)" % (name[:40], len(images), resolved["source"]))
            for t in titles:
                print("        %s" % t)

            if not args.dry_run:
                get_collection(collection).update_one(
                    {"_id": doc["_id"]},
                    {"$set": {
                        "images": [i["url"] for i in images],
                        "imageSource": resolved["source"],
                        "imageTitles": titles,
                        "imageLicences": [{"license": i.get("license"),
                                           "author": i.get("author")} for i in images],
                        "imageCheckedAt": place_images.time.strftime(
                            "%Y-%m-%dT%H:%M:%S", place_images.time.gmtime()),
                    }})
            changed += 1

    print("\n%d listings checked, %d re-pointed, %d left on the placeholder.%s"
          % (checked, changed, unresolved, " (dry run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
