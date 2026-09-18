#!/usr/bin/env python3
"""Safe full-data reset for the TripMind tripmind development database.

Drops every application-data document across all user-facing collections while
preserving indexes, schema, and any future collection metadata. The script is
DESTRUCTIVE — only run it against the dev/test database (tripmind).

Usage:
    python scripts/reset_tripmind_dev_data.py          # drops from tripmind DB
    python scripts/reset_tripmind_dev_data.py --confirm   # must supply --confirm
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import MONGODB_URI
from services.mongodb import get_db

APP_COLLNS = [
    # user identity / accounts
    "users",
    # wallet ledger
    "wallets",
    # bookings
    "bookings",
    # trips
    "trips",
    # transport catalogue
    "transports",
    # hospitality
    "hotels",
    # dining
    "restaurants",
    "food_items",
    # tourism
    "tourist_spots",
    "tours",
    # guides
    "guides",
    "guide_availability",
    "guide_pricing",
    "guide_locations",
    # railway lounges
    "lounges",
    # ratings + reviews
    "ratings",
    # auth tokens
    "tokens",
    # AI / assistant state
    "assistant",
    # ML feature store / event logs (if any)
    "ml",
]


def _main():
    if "--confirm" not in sys.argv:
        print("This script will DELETE every document in these collections:")
        for c in APP_COLLNS:
            print("  -", c)
        print("\nRun with --confirm to proceed.")
        return 1

    db = get_db()
    total = 0
    for name in APP_COLLNS:
        coll = db[name]
        n = coll.estimated_document_count()
        if n:
            coll.delete_many({})
            print(f"[OK] {name}: deleted {n} document(s)")
            total += n
        else:
            print(f"[OK] {name}: already empty")
    print(f"\nReset complete — {total} total documents removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())