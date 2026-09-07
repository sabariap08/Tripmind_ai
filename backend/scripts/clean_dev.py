"""Remove test-generated user data and legacy test accounts.

Deletes: bookings, trips, guide availability, guide profile side-effects.
Resets: transport bookedSeats, hotel room bookedRooms, tour bookedParticipants.
Purges legacy test/demo accounts (@tripmind.test, demo identity) and the demo
catalogue owned by them, so the database only holds real accounts.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.mongodb import get_collection

COLLECTIONS_TO_PURGE = ("bookings", "trips", "guide_availability")

# Emails / identities created by the old dev seed — never legitimate accounts.
LEGACY_TEST_EMAILS = {
    "admin@tripmind.test", "transport@tripmind.test", "tourist@tripmind.test",
    "hotel@tripmind.test", "guide@tripmind.test", "user@tripmind.test",
    "pendingtransport@tripmind.test", "pendingtourist@tripmind.test",
    "pendinghotel@tripmind.test", "pendingguide@tripmind.test",
    "demo@tripmind.ai", "admin@tripmind.com",
}


def clean():
    total = 0
    for name in COLLECTIONS_TO_PURGE:
        r = get_collection(name).delete_many({})
        print(f"purged {name}: {r.deleted_count}")
        total += r.deleted_count

    tr = get_collection("transports").update_many({}, {"$set": {"bookedSeats": 0}})
    print(f"reset bookedSeats on transports: {tr.modified_count}")

    get_collection("hotels").update_many(
        {}, [{"$set": {
            "roomTypes": {
                "$map": {
                    "input": "$roomTypes",
                    "as": "rt",
                    "in": {"$mergeObjects": ["$$rt",
                                             {"bookedRooms": 0,
                                              "blockedRooms": {"$min": ["$$rt.blockedRooms", "$$rt.totalRooms"]}}]},
                }
            }
        }}])
    print("reset bookedRooms on hotels: done")

    tours = get_collection("tours").update_many({}, {"$set": {"bookedParticipants": 0}})
    print(f"reset tour capacity: {tours.modified_count}")

    # Legacy test accounts (their resources are demo data too).
    legacy = [u["_id"] for u in get_collection("users").find(
        {"$or": [{"email": {"$in": list(LEGACY_TEST_EMAILS)}},
                 {"_id": "demo-user-1"},
                 {"demoIdentifier": "demo"}]})]
    if legacy:
        users_gone = get_collection("users").delete_many({"_id": {"$in": legacy}})
        print(f"removed {users_gone.deleted_count} legacy test accounts")
        for coll in ("transports", "tourist_spots", "hotels", "tours",
                     "guide_locations", "guide_pricing", "restaurants",
                     "food_items"):
            r = get_collection(coll).delete_many({"ownerId": {"$in": legacy}})
            if r.deleted_count:
                print(f"  removed {r.deleted_count} orphaned rows in {coll}")

    print("Cleanup done.")
    return total


if __name__ == "__main__":
    clean()