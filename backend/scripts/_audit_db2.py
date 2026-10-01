"""Deeper read-only audit: roles, spots with images, itinerary structure, user prefs."""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.mongodb import get_db  # noqa: E402


def main():
    db = get_db()

    print("### USERS BY ROLE")
    for r in db.users.aggregate([
        {"$group": {"_id": {"role": "$role", "approvalStatus": "$approvalStatus"}, "n": {"$sum": 1}}},
        {"$sort": {"_id.role": 1}},
    ]):
        print("  ", r["_id"], r["n"])

    print("\n### USER DOC KEYS (union)")
    keys = set()
    for u in db.users.find({}, {"passwordHash": 0}):
        keys |= set(u.keys())
    print("  ", sorted(keys))

    print("\n### PASSENGER USER SAMPLE")
    u = db.users.find_one({"role": {"$ne": "ADMIN"}}, {"passwordHash": 0})
    print("  ", json.dumps(u, default=str)[:1500])

    print("\n### TOURIST SPOTS (all)")
    for s in db.tourist_spots.find():
        loc = s.get("location") or {}
        print("  - %-34s city=%-12s dist=%-14s imgs=%d open=%s-%s" % (
            s.get("name"), s.get("city"), loc.get("district"),
            len(s.get("images") or []), s.get("openingTime"), s.get("closingTime")))
        for im in (s.get("images") or []):
            print("        img: %s" % im)

    print("\n### HOTELS")
    for h in db.hotels.find():
        print("  - %-32s city=%-12s dist=%-14s imgs=%d cat=%s" % (
            h.get("name"), h.get("city"), h.get("district"), len(h.get("images") or []), h.get("category")))

    print("\n### RESTAURANTS")
    for r in db.restaurants.find():
        print("  - %-40s city=%-12s dist=%s" % (r.get("name"), r.get("city"), r.get("district")))

    print("\n### TRANSPORT SUMMARY")
    for t in db.transports.aggregate([
        {"$group": {"_id": {"type": "$type", "b": "$boardingStation", "d": "$destinationStation"},
                    "n": {"$sum": 1}}},
        {"$sort": {"_id.type": 1}},
    ]):
        print("  ", t["_id"], t["n"])

    print("\n### TRIP: itinerary + event structure (latest trip)")
    t = db.trips.find_one(sort=[("createdAt", -1)])
    print("  trip keys:", sorted(t.keys()))
    print("  _id:", t["_id"], "origin:", t.get("origin"), "dest:", t.get("destination"))
    print("  budget:", t.get("budget"), "totalEstimatedCost:", t.get("totalEstimatedCost"))
    print("  status:", t.get("status"), "travelStyle:", t.get("travelStyle"))
    print("  transportType:", t.get("transportType"), "servicePreference:", t.get("servicePreference"))
    print("  travelers:", t.get("travelers"), "dates:", t.get("startDate"), t.get("endDate"))
    print("  recommendations keys:", sorted((t.get("recommendations") or {}).keys()) if isinstance(t.get("recommendations"), dict) else type(t.get("recommendations")))
    for i, it in enumerate(t.get("itineraries") or []):
        print("  itinerary[%d] keys: %s" % (i, sorted(it.keys())))
        print("    version=%s status=%s totalCost=%s planType=%s generatedBy=%s" % (
            it.get("version"), it.get("status"), it.get("totalCost"), it.get("planType"), it.get("generatedBy")))
        print("    items: %d" % len(it.get("items") or []))
        for it2 in (it.get("items") or [])[:40]:
            print("       %s %s-%s %s %s cost=%s" % (
                it2.get("type"), (it2.get("startTime") or "")[11:16], (it2.get("endTime") or "")[11:16],
                it2.get("title"), it2.get("location") or "", it2.get("cost")))
        break
    print("  events: %d" % len(t.get("events") or []))
    for e in (t.get("events") or [])[:5]:
        print("     ", json.dumps(e, default=str)[:300])

    print("\n### TRIP versions present")
    for t2 in db.trips.find({}, {"itineraries.version": 1, "itineraries.status": 1, "status": 1}).limit(40):
        print("  ", t2["_id"], t2.get("status"),
              [(i.get("version"), i.get("status")) for i in (t2.get("itineraries") or [])])

    print("\n### NOTIFICATIONS kinds")
    for n in db.notifications.aggregate([{"$group": {"_id": "$kind", "n": {"$sum": 1}}}]):
        print("  ", n["_id"], n["n"])

    print("\n### ML MODELS")
    for m in db.ml_models.find():
        print("  - %-38s v%-3s status=%-8s samples=%-5s metrics=%s" % (
            m.get("model"), m.get("version"), m.get("status"), m.get("samples"), m.get("metrics")))

    print("\n### RATINGS/TRIP_REVIEWS counts:", db.ratings.count_documents({}), db.trip_reviews.count_documents({}))

    print("\n### TRIP extra keys union")
    tk = set()
    for x in db.trips.find():
        tk |= set(x.keys())
    print("  ", sorted(tk))

    print("\n### CHECKLIST sample full")
    c = db.checklists.find_one()
    print(json.dumps(c, default=str, indent=1)[:2500])


if __name__ == "__main__":
    main()
