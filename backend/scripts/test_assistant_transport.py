"""End-to-end: the live assistant changes the plan on a natural-language
transport request, proposing first and writing only on confirmation.

The visible trip assistant is ``/api/assistant/chat`` -> ``assistant.py``. It
promises "nothing is applied until you confirm them", so this test drives the
real Flask stack and the real database and asserts both halves:

  phase 1  "I don't want the train. I want a bus." -> proposal, DB unchanged
  phase 2  POST /api/assistant/action             -> leg replaced + re-flowed

It restores the itinerary it touched. Skips cleanly when the dev fixtures it
needs (an authenticatable trip with a booked-type leg and an approved transport
of a different mode) are absent, rather than reporting a false pass.

Run from ``backend/``::

    python scripts/test_assistant_transport.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app as flask_app  # noqa: E402
from services.mongodb import get_collection  # noqa: E402
from services.transport_service import available_transports  # noqa: E402

DEV_PASSWORDS = ("Demo@1234", "demo1234", "Admin@1234", "admin1234",
                 "Password@123", "test1234", "Trip@1234", "12345678")

BOOKED_TYPES = ("BUS", "TRAIN", "FLIGHT")


def selected_of(trip):
    for it in trip.get("itineraries", []):
        if it.get("status") == "SELECTED":
            return it
    return None


def find_session(client):
    """A PLANNED trip whose selected itinerary has a booked-type leg, owned by
    a user we can authenticate as."""
    for user in get_collection("users").find({}, {"email": 1, "role": 1, "_id": 1}):
        for password in DEV_PASSWORDS:
            resp = client.post("/api/auth/login",
                               json={"email": user.get("email"), "password": password})
            if resp.status_code != 200:
                continue
            user_id = (resp.get_json().get("user") or {}).get("id")
            for trip in get_collection("trips").find({"userId": user_id}):
                if trip.get("status") != "PLANNED":
                    continue
                sel = selected_of(trip)
                if not sel:
                    continue
                if any(str(i.get("type") or "").upper() in BOOKED_TYPES
                       for i in sel.get("items", [])):
                    return user, trip
    return None, None


def other_mode_with_service(trip, current_mode):
    for t in available_transports(trip.get("origin"), trip.get("destination")):
        if t.get("type") != current_mode:
            return t.get("type")
    return None


def restore(trip_id, snapshot):
    get_collection("trips").update_one(
        {"_id": trip_id},
        {"$set": {
            "itineraries.$[it].items": snapshot["items"],
            "itineraries.$[it].totalCost": snapshot["totalCost"],
            "itineraries.$[it].version": snapshot["version"],
            "totalEstimatedCost": snapshot["totalEstimatedCost"],
            "status": snapshot["status"],
        }},
        array_filters=[{"it.status": "SELECTED"}],
    )


def main() -> int:
    failures = []

    def check(name, condition, detail=""):
        print("[%s] %s%s" % ("PASS" if condition else "FAIL", name,
                             ("  -- " + detail) if (detail and not condition) else ""))
        if not condition:
            failures.append(name)

    client = flask_app.app.test_client()
    user, trip = find_session(client)
    if not trip:
        print("SKIP: no authenticatable PLANNED trip with a booked-type leg.")
        return 0

    trip_id = str(trip["_id"])
    sel = selected_of(trip)
    leg = next(i for i in sel["items"]
               if str(i.get("type") or "").upper() in BOOKED_TYPES)
    current_mode = str(leg["type"]).upper()
    want_mode = other_mode_with_service(trip, current_mode)
    if not want_mode:
        print("SKIP: corridor %s -> %s has no other approved mode."
              % (trip.get("origin"), trip.get("destination")))
        return 0

    snapshot = {
        "items": copy.deepcopy(sel.get("items") or []),
        "totalCost": sel.get("totalCost"),
        "version": sel.get("version"),
        "totalEstimatedCost": trip.get("totalEstimatedCost"),
        "status": trip.get("status"),
    }
    print("trip %s: %s -> %s, current %s, want %s\n"
          % (trip_id, trip.get("origin"), trip.get("destination"),
             current_mode, want_mode))

    def items_now():
        return (selected_of(get_collection("trips").find_one({"_id": trip_id}))
                or {}).get("items", [])

    message = ("I don't want the %s. I want a %s."
               % (current_mode.lower(), want_mode.lower()))

    # --- phase 1: propose, do not write ------------------------------------
    r1 = client.post("/api/assistant/chat", json={"message": message, "tripId": trip_id})
    check("phase 1 returns 200", r1.status_code == 200, "got %s" % r1.status_code)
    body1 = r1.get_json() or {}
    action = body1.get("action") or {}
    check("phase 1 proposes change_transport",
          action.get("type") == "change_transport", repr(action))
    transport_id = (action.get("params") or {}).get("transport_id")
    check("phase 1 names a replacement transport", bool(transport_id), repr(action))
    replaced = get_collection("transports").find_one({"_id": transport_id}) if transport_id else None
    check("replacement is a real approved service of the requested mode",
          bool(replaced) and replaced.get("type") == want_mode,
          repr((replaced or {}).get("type")))
    check("phase 1 says nothing has changed yet",
          "nothing has changed yet" in (body1.get("response") or "").lower(),
          repr(body1.get("response"))[:120])

    after1 = items_now()
    check("phase 1 wrote nothing to the database",
          [i.get("type") for i in after1] == [i.get("type") for i in snapshot["items"]],
          "%d -> %d items" % (len(snapshot["items"]), len(after1)))

    # --- phase 2: confirm, now it writes -----------------------------------
    r2 = client.post("/api/assistant/action",
                     json={"type": "change_transport", "params": action.get("params")})
    check("phase 2 returns 200", r2.status_code == 200,
          repr((r2.get_json() or {}).get("error")))
    body2 = r2.get_json() or {}
    check("phase 2 does not report a failure",
          not body2.get("error"), repr(body2.get("error")))

    doc = get_collection("trips").find_one({"_id": trip_id})
    sel2 = selected_of(doc) or {}
    leg2 = next((i for i in sel2.get("items", [])
                 if str(i.get("type") or "").upper() in BOOKED_TYPES), None)
    check("the booked leg is now the requested mode",
          leg2 is not None and str(leg2.get("type")).upper() == want_mode,
          repr((leg2 or {}).get("type")))
    check("the itinerary version was incremented",
          int(sel2.get("version") or 0) > int(snapshot["version"] or 0),
          "%s -> %s" % (snapshot["version"], sel2.get("version")))
    check("the headline estimate tracks the itinerary",
          doc.get("totalEstimatedCost") == sel2.get("totalCost"),
          "%s vs %s" % (doc.get("totalEstimatedCost"), sel2.get("totalCost")))
    check("downstream items were re-flowed, not left at stale times",
          any(i.get("replanStatus") == "MOVED" for i in sel2.get("items", [])),
          "no MOVED items")

    restore(trip_id, snapshot)
    restored = (selected_of(get_collection("trips").find_one({"_id": trip_id}))
                or {}).get("items", [])
    check("the test restored the itinerary it mutated",
          [i.get("type") for i in restored] == [i.get("type") for i in snapshot["items"]],
          "restore mismatch")

    print()
    print("%d failure(s)" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())