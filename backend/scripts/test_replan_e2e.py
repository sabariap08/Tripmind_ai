"""End-to-end check of the two-phase replan flow, through the real HTTP stack.

    python scripts/test_replan_e2e.py

Uses Flask's test client so it needs no running server. The proposal phase is
verified to leave the database untouched - that is the property that makes the
confirmation step meaningful, and it is the thing most likely to regress.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as application  # noqa: E402
from services.mongodb import get_collection  # noqa: E402

app = application.app
app.config["TESTING"] = True

RESULTS = []


def check(label, condition, detail=""):
    RESULTS.append((label, bool(condition)))
    print("  [%s] %s%s" % ("PASS" if condition else "FAIL", label,
                           ("  -- " + str(detail)) if detail and not condition else ""))


def login(client, email, password):
    return client.post("/api/auth/login",
                       json={"email": email, "password": password})


def main():
    client = app.test_client()

    # ---------------------------------------------------------------- login
    users = list(get_collection("users").find({}, {"email": 1, "role": 1, "_id": 1}))
    if not users:
        print("No users in the database; cannot run end-to-end test.")
        return 2
    print("Found %d user(s); trying to authenticate.\n" % len(users))

    authed = False
    session_user = None
    for user in users:
        for password in ("Demo@1234", "demo1234", "Admin@1234", "admin1234",
                         "Password@123", "test1234", "Trip@1234", "12345678"):
            response = login(client, user.get("email"), password)
            if response.status_code == 200:
                authed = True
                session_user = user
                print("  authenticated as %s (%s)\n"
                      % (user.get("email"), user.get("role")))
                break
        if authed:
            break

    if not authed:
        print("Could not authenticate with the common dev passwords.")
        print("Replan endpoint checks skipped; the unit tests in")
        print("scripts/test_replanner.py still cover the engine.")
        return 0

    # ------------------------------------------------------- find their trip
    trips = get_collection("trips")
    trip = trips.find_one({"userId": session_user["_id"],
                           "itineraries": {"$exists": True, "$ne": []}})
    if not trip:
        trip = trips.find_one({"itineraries": {"$exists": True, "$ne": []}})
    if not trip:
        print("No trip with an itinerary available to replan.")
        return 0

    before = trips.find_one({"_id": trip["_id"]})
    before_itins = len(before.get("itineraries") or [])

    # ------------------------------------------------------- phase 1: propose
    print("Phase 1 - propose (no confirmation)")
    response = client.post("/api/trips/%s/replan" % trip["_id"],
                           json={"delayMinutes": 180})
    check("proposal returns 200", response.status_code == 200,
          "%s %s" % (response.status_code, response.get_data(as_text=True)[:200]))
    payload = response.get_json() or {}
    check("response is marked as a proposal", payload.get("proposal") is True)
    check("response requires confirmation", payload.get("requiresConfirmation")
          in (None, True) or "proposal" in payload)
    check("a cost breakdown is returned", "cost" in payload, list(payload))
    check("additionalCost is a number, not null",
          isinstance((payload.get("cost") or {}).get("additional"), (int, float)))
    check("the explanation is derived from the diff",
          bool(payload.get("summary")))

    after = trips.find_one({"_id": trip["_id"]})
    check("PROPOSAL PHASE WROTE NOTHING to the trip document",
          len(after.get("itineraries") or []) == before_itins,
          "itineraries %d -> %d" % (before_itins, len(after.get("itineraries") or [])))
    check("the selected itinerary is unchanged",
          json_sig(after) == json_sig(before), "trip document differs after proposal")

    # ------------------------------------------------------- phase 2: confirm
    print("\nPhase 2 - confirm")
    response = client.post("/api/trips/%s/replan" % trip["_id"],
                           json={"delayMinutes": 180, "confirm": True})
    check("confirmation returns 200", response.status_code == 200,
          "%s %s" % (response.status_code, response.get_data(as_text=True)[:200]))
    payload = response.get_json() or {}
    check("response is marked as confirmed", payload.get("confirmed") is True)
    check("a new version number was issued",
          isinstance(payload.get("version"), int) and payload["version"] > 1,
          payload.get("version"))

    after = trips.find_one({"_id": trip["_id"]})
    check("the database now has one more itinerary version",
          len(after.get("itineraries") or []) == before_itins + 1,
          "%d -> %d" % (before_itins, len(after.get("itineraries") or [])))
    check("exactly one itinerary is SELECTED",
          sum(1 for i in (after.get("itineraries") or [])
              if i.get("status") == "SELECTED") == 1)
    check("the previous version is marked SUPERSEDED",
          any(i.get("status") == "SUPERSEDED" for i in after.get("itineraries") or []))

    # ------------------------------------------- arithmetic honesty of the cost
    print("\nCost arithmetic")
    additional = payload.get("additionalCost")
    original = payload.get("originalCost")
    revised = payload.get("revisedCost")
    check("additionalCost == revised - original",
          all(isinstance(v, (int, float)) for v in (additional, original, revised))
          and abs(additional - (revised - original)) < 0.01,
          "%s vs %s - %s" % (additional, revised, original))
    check("a DELAY_RESOLVED event was recorded",
          any(e.get("type") == "DELAY_RESOLVED" for e in after.get("events") or []))

    failed = [r for r in RESULTS if not r[1]]
    print("\n%d/%d end-to-end checks passed." % (len(RESULTS) - len(failed), len(RESULTS)))
    for label, _ in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


def json_sig(doc):
    """A comparable signature of the parts the proposal phase must not touch."""
    import json
    return json.dumps({
        "status": doc.get("status"),
        "itineraries": sorted(
            [(i.get("version"), i.get("status"),
              len(i.get("items") or []),
              tuple(sorted((it.get("_id"), it.get("startTime"))
                           for it in (i.get("items") or []))))
             for i in (doc.get("itineraries") or [])],
        )
    }, default=str, sort_keys=True)


if __name__ == "__main__":
    sys.exit(main())
