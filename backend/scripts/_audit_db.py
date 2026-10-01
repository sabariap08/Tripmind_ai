"""Read-only audit of the live TripMind database: collections, counts, sample docs."""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.mongodb import get_db, get_collection  # noqa: E402


def brief(doc, n=1200):
    try:
        s = json.dumps(doc, default=str)
    except Exception:
        s = str(doc)
    return s[:n]


def main():
    db = get_db()
    print("DB:", db.name)
    names = sorted(db.list_collection_names())
    print("COLLECTIONS (%d): %s" % (len(names), ", ".join(names)))
    for name in names:
        col = db[name]
        count = col.count_documents({})
        print("\n=== %s (%d docs) ===" % (name, count))
        if count == 0:
            continue
        doc = col.find_one()
        print("  keys: %s" % ", ".join(sorted(doc.keys())))
        print("  sample: %s" % brief(doc))


if __name__ == "__main__":
    main()
