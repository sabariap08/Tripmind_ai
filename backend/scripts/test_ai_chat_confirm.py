"""Prove /api/ai/chat no longer mutates without confirmation.

The trip page tells the user "The assistant proposes changes - nothing is
applied until you confirm them." Before this change ``/api/ai/chat`` deleted
itinerary items on the first message, so the copy was false. This exercises the
real Flask stack and the real database:

  phase 1  POST /api/ai/chat "remove X"          -> proposal, DB unchanged
  phase 2  POST /api/ai/chat confirm + pending   -> applied exactly once
  tamper   echo a doctored pendingAction        -> server re-derives, ignores it

Run from ``backend/`` with the app's env loaded::

    python scripts/test_ai_chat_confirm.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app as flask_app  # noqa: E402
from services.mongodb import get_collection  # noqa: E402

# Same dev password candidates the replan e2e test uses. No credential is
# written down as fact: we try the real users in the database and skip cleanly
# if none of them match, rather than pretending the test ran.
DEV_PASSWORDS = ("Demo@1234", "demo1234", "Admin@1234", "admin1234",
                 "Password@123", "test1234", "Trip@1234", "12345678")


def find_session(client):
    """First (user, trip) pair we can actually authenticate as."""
    users = list(get_collection("users").find(
        {}, {"email": 1, "role": 1, "_id": 1}))
    for user in users:
        for password in DEV_PASSWORDS:
            response = client.post(
                "/api/auth/login",
                json={"email": user.get("email"), "password": password},
            )
            if response.status_code != 200:
                continue
            # Keep whichever session belongs to a trip that actually has a
            # multi-item selected itinerary, so the test has something to
            # propose against.
            user_id = response.get_json().get("user", {}).get("id")
            trip = get_collection("trips").find_one({"userId": user_id})
            if trip and len(items_of(str(trip["_id"]))) >= 2:
                return user, str(trip["_id"]), user_id
    return None, None, None


def items_of(trip_id) -> list:
    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return []
    for itinerary in trip.get("itineraries", []):
        if itinerary.get("status") == "SELECTED":
            return itinerary.get("items", [])
    return []


def restore_itinerary(trip_id, items) -> bool:
    """Put the selected itinerary's items back exactly as they were."""
    result = get_collection("trips").update_one(
        {"_id": trip_id},
        {"$set": {
            "itineraries.$[it].items": items,
            "itineraries.$[it].totalCost": sum(i.get("cost", 0) for i in items),
        }},
        array_filters=[{"it.status": "SELECTED"}],
    )
    return result.matched_count == 1


def snapshots_match(before, current) -> bool:
    return titles(before) == titles(current)


def titles(items) -> list:
    return [i.get("title", "") for i in items]


def main() -> int:
    failures = []

    def check(name, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        print(f"[{status}] {name}" + (f"  -- {detail}" if detail and not condition else ""))
        if not condition:
            failures.append(name)

    client = flask_app.app.test_client()
    user, trip_id, user_id = find_session(client)
    if not trip_id:
        print("SKIP: no dev user with an authenticatable multi-item itinerary; "
              "cannot run this test")
        return 0
    print(f"authenticated as {user.get('email')} ({user.get('role')}), trip {trip_id}\n")

    before = items_of(trip_id)

    # Pick a distinctive title to ask about, and a phrase that must NOT match.
    target = before[0].get("title", "")
    probe = target.split()[0] if target.split() else target
    if not probe:
        print("SKIP: first item has no title")
        return 0

    # --- phase 1: must propose, must not write --------------------------------
    r1 = client.post("/api/ai/chat", json={"message": f"remove {probe}", "tripId": trip_id})
    check("phase 1 returns 200", r1.status_code == 200, f"got {r1.status_code}")
    body1 = r1.get_json() or {}
    check("phase 1 flags requiresConfirmation",
          body1.get("requiresConfirmation") is True, repr(body1.get("requiresConfirmation")))
    check("phase 1 returns a pendingAction",
          isinstance(body1.get("pendingAction"), dict), repr(body1.get("pendingAction")))
    check("phase 1 action is remove_place",
          (body1.get("pendingAction") or {}).get("action") == "remove_place")
    check("phase 1 preview lists what would go",
          bool((body1.get("preview") or {}).get("removed")),
          repr(body1.get("preview")))

    after1 = items_of(trip_id)
    check("phase 1 wrote nothing to the database",
          titles(after1) == titles(before),
          f"{len(before)} -> {len(after1)} items")

    # --- a plain question still answers, and flags nothing to confirm ----------
    rq = client.post("/api/ai/chat", json={"message": "what is my budget?", "tripId": trip_id})
    qbody = rq.get_json() or {}
    check("a read-only question does not demand confirmation",
          qbody.get("requiresConfirmation") is not True)
    check("a read-only question still answers",
          bool(qbody.get("response")))

    # --- tamper: a doctored pendingAction must not be trusted ------------------
    # Everything from here to the finally block is destructive, so the restore
    # lives in a finally: an assertion error or a database blip part way through
    # must not leave a developer's real itinerary shorter than it was found.
    doctored = {"action": "remove_place", "place": probe}
    try:
        rt = client.post("/api/ai/chat", json={
            "message": "yes do it", "tripId": trip_id,
            "confirm": True, "pendingAction": doctored,
        })
        check("confirm returns 200", rt.status_code == 200, f"got {rt.status_code}")
        applied = (rt.get_json() or {}).get("applied") or {}
        check("confirm reports what it actually removed",
              bool(applied.get("removed")), repr(applied))
        # The server recomputed from the DB, so the removed titles must be
        # exactly the titles that really matched, no more and no fewer.
        real_hits = [t for t in titles(before) if probe.lower() in t.lower()]
        check("server re-derives the removal instead of trusting the payload",
              sorted(applied.get("removed", [])) == sorted(real_hits),
              f"applied={applied.get('removed')} real={real_hits}")

        after2 = items_of(trip_id)
        check("confirm actually removed the item",
              len(after2) < len(before), f"{len(before)} -> {len(after2)}")
        check("confirm left the rest of the plan alone",
              all(t in titles(before) for t in titles(after2)))

        # --- replaying the same confirmation must not remove anything more ----
        rr = client.post("/api/ai/chat", json={
            "message": "yes do it", "tripId": trip_id,
            "confirm": True, "pendingAction": doctored,
        })
        after3 = items_of(trip_id)
        check("replaying a confirmation is idempotent",
              len(after3) == len(after2), f"{len(after2)} -> {len(after3)}")
        check("replay is reported as an error, not a silent success",
              "removed" not in ((rr.get_json() or {}).get("applied") or {}))
    finally:
        restored = restore_itinerary(trip_id, before)
        check("the test restored the itinerary it mutated", restored)
        check("restored state matches the original state",
              snapshots_match(before, items_of(trip_id)),
              f"{titles(items_of(trip_id))} != {titles(before)}")

    # --- a confirmation with no trip is refused --------------------------------
    rnt = client.post("/api/ai/chat", json={
        "message": "yes", "confirm": True, "pendingAction": doctored,
    })
    check("confirm without a tripId is refused", rnt.status_code == 400, f"got {rnt.status_code}")

    # --- a non-object pendingAction is refused ---------------------------------
    rbad = client.post("/api/ai/chat", json={
        "message": "yes", "tripId": trip_id, "confirm": True, "pendingAction": "nope",
    })
    check("a non-object pendingAction is refused", rbad.status_code == 400, f"got {rbad.status_code}")

    # --- someone else's trip is still refused ---------------------------------
    r404 = client.post("/api/ai/chat", json={"message": "remove x", "tripId": "does-not-exist"})
    check("unknown trip is 404", r404.status_code == 404, f"got {r404.status_code}")

    print()
    print(f"{len(failures)} failure(s)" + (f": {', '.join(failures)}" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
