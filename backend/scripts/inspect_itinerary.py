"""Dump the shape of a real stored itinerary, for building against real data.

    python scripts/inspect_itinerary.py
    python scripts/inspect_itinerary.py <trip_id>
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.mongodb import get_collection  # noqa: E402


def main():
    trips = get_collection("trips")
    query = {"itineraries": {"$exists": True, "$ne": []}}
    if len(sys.argv) > 1:
        trip = trips.find_one({"_id": sys.argv[1]})
    else:
        trip = trips.find_one(query, {"itineraries": 1, "origin": 1, "destination": 1,
                                      "startDate": 1, "endDate": 1, "travelers": 1,
                                      "budget": 1, "travelStyle": 1})
    if not trip:
        print("No trip with an itinerary found.")
        return 1

    print("trip %s | %s -> %s | %s .. %s | travellers=%s budget=%s" % (
        trip.get("_id"), trip.get("origin"), trip.get("destination"),
        trip.get("startDate"), trip.get("endDate"),
        trip.get("travelers"), trip.get("budget")))

    for itin in trip.get("itineraries") or []:
        print("  version=%-3s status=%-10s planType=%-10s totalCost=%-10s items=%s" % (
            itin.get("version"), itin.get("status"), itin.get("planType"),
            itin.get("totalCost"), len(itin.get("items") or [])))

    sel = next((i for i in trip.get("itineraries") or []
                if i.get("status") == "SELECTED"), None)
    if not sel:
        print("\nNo SELECTED itinerary.")
        return 0

    items = sel.get("items") or []
    print("\nItinerary keys: %s" % sorted(sel.keys()))
    print("Day values: %s" % sorted({str(i.get("day")) for i in items}))
    print("Item types: %s" % dict(Counter(i.get("type") for i in items)))
    print("\nEvery distinct item key: %s"
          % sorted({k for i in items for k in i.keys()}))

    print("\n--- first 4 items in full ---")
    for item in items[:4]:
        print(json.dumps(item, indent=1, default=str))

    print("\n--- transport items in full ---")
    transports = [i for i in items if i.get("type") in
                  ("TRANSPORT", "BUS", "TRAIN", "FLIGHT", "CAB", "AUTO")]
    for item in transports[:2]:
        print(json.dumps(item, indent=1, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
