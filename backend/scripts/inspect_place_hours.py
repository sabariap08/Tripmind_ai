"""Print the opening-hour / cost fields the replanner has to respect.

    python scripts/inspect_place_hours.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.mongodb import get_collection  # noqa: E402


def main():
    for coll, label in (("tourist_spots", "SPOT"), ("hotels", "HOTEL"),
                        ("restaurants", "RESTAURANT"), ("tours", "TOUR")):
        docs = list(get_collection(coll).find())
        if not docs:
            continue
        print("\n%s (%d)" % (coll, len(docs)))
        keys = sorted({k for d in docs for k in d.keys()})
        print("  keys: %s" % keys)
        for d in docs[:4]:
            print("  %-34s open=%-6s close=%-6s fee=%-7s city=%-12s days=%s" % (
                (d.get("name") or "?")[:34], d.get("openingTime"),
                d.get("closingTime"), d.get("entryFee"),
                d.get("city"), d.get("workingDays")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
