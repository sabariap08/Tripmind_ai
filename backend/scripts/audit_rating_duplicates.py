"""Report duplicate ratings before the unique index is created.

One rating per booking is the invariant the new unique index enforces. If
duplicates already exist the index cannot be built, and the per-service average
is already wrong (it averages raw documents, so a double-submitted rating is
counted twice).

Run from ``backend/``::

    python scripts/audit_rating_duplicates.py

Read-only: it reports and never deletes. Use --dedupe to remove the extras,
keeping the earliest rating per booking, after you have looked at the list.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from pymongo.errors import BulkWriteError  # noqa: E402

from services.mongodb import get_collection, ensure_unique_indexes  # noqa: E402


def find_duplicates():
    """Bookings with more than one rating, newest kept for display."""
    pipeline = [
        {"$group": {
            "_id": "$bookingId",
            "count": {"$sum": 1},
            "ratings": {"$push": {
                "_id": "$_id",
                "rating": "$rating",
                "createdAt": "$createdAt",
                "serviceType": "$serviceType",
            }},
        }},
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]
    return list(get_collection("ratings").aggregate(pipeline))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dedupe", action="store_true",
                        help="delete all but the earliest rating per booking")
    args = parser.parse_args()

    total = get_collection("ratings").count_documents({})
    orphans = get_collection("ratings").count_documents(
        {"bookingId": {"$exists": False}})
    dupes = find_duplicates()

    print(f"ratings total            : {total}")
    print(f"ratings without bookingId: {orphans}")
    print(f"bookings rated twice+    : {len(dupes)}")

    for row in dupes:
        print(f"\n  bookingId={row['_id']}  count={row['count']}")
        # Earliest first, so the keeper is obvious and matches --dedupe.
        ordered = sorted(row["ratings"],
                         key=lambda r: str(r.get("createdAt") or ""))
        for i, rating in enumerate(ordered):
            keep = "KEEP" if i == 0 else "dupe"
            print(f"    {keep}  {rating.get('_id')}  stars={rating.get('rating')}  "
                  f"{rating.get('serviceType')}  {rating.get('createdAt')}")

    if dupes and not args.dedupe:
        print("\nThe unique index on ratings.bookingId cannot be created while "
              "these exist.\nRe-run with --dedupe to keep the earliest rating "
              "per booking and drop the rest.")
        return 1

    if args.dedupe and dupes:
        doomed = []
        for row in dupes:
            ordered = sorted(row["ratings"],
                             key=lambda r: str(r.get("createdAt") or ""))
            doomed.extend(r["_id"] for r in ordered[1:])
        try:
            result = get_collection("ratings").delete_many({"_id": {"$in": doomed}})
            print(f"\ndeleted {result.deleted_count} duplicate rating(s)")
        except BulkWriteError as exc:  # pragma: no cover
            print(f"delete failed: {exc}")
            return 1

    print("\nverifying index creation...")
    errors = ensure_unique_indexes()
    if errors:
        for err in errors:
            print(f"  WARN: {err}")
        return 1
    print("  all unique indexes created")

    remaining = find_duplicates()
    if remaining:
        print(f"\n{len(remaining)} duplicate group(s) remain")
        return 1
    print("no duplicate ratings remain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
