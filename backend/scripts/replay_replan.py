"""Run the replanner over a real stored trip and report what it would change.

    python scripts/replay_replan.py
    python scripts/replay_replan.py <trip_id> 180

Read-only: builds a proposal and prints it. Nothing is written.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.mongodb import get_collection  # noqa: E402
from services import replanner  # noqa: E402


def main():
    trips = get_collection("trips")
    if len(sys.argv) > 1:
        trip = trips.find_one({"_id": sys.argv[1]})
    else:
        trip = trips.find_one({"itineraries": {"$exists": True, "$ne": []}})
    if not trip:
        print("No trip found.")
        return 1

    delay = int(sys.argv[2]) if len(sys.argv) > 2 else 180
    selected = next((i for i in trip.get("itineraries") or []
                     if i.get("status") == "SELECTED"), None)
    if not selected:
        print("No SELECTED itinerary on this trip.")
        return 1

    print("trip %s  %s -> %s  %s..%s  budget=%s" % (
        trip.get("_id"), trip.get("origin"), trip.get("destination"),
        trip.get("startDate"), trip.get("endDate"), trip.get("budget")))
    print("delay applied: %d minutes\n" % delay)

    try:
        proposal = replanner.build_proposal(trip, selected,
                                            delay_minutes=delay, reason="delay")
    except replanner.ReplanError as exc:
        print("ReplanError: %s" % exc)
        return 1

    print("SUMMARY: %s\n" % proposal["summary"])

    print("COST")
    cost = proposal["cost"]
    print("  original        %10.2f" % cost["original"])
    print("  revised         %10.2f" % cost["revised"])
    print("  additional      %10.2f" % cost["additional"])
    print("  removed value   %10.2f" % cost["removedValue"])
    print("  all verified    %10s" % cost["allCostsVerified"])

    print("\nCHANGES (%d)" % len(proposal["changes"]))
    for change in proposal["changes"]:
        print("  %-8s day %-3s %-30s %s -> %s   (%s)" % (
            change["type"], change.get("day"), (change.get("title") or "")[:30],
            (change.get("from") or "-")[11:16], (change.get("to") or "-")[11:16],
            change.get("reason")))

    print("\nDROPPED (%d)" % len(proposal["dropped"]))
    for item in proposal["dropped"]:
        print("  day %-3s %-30s %s" % (item.get("day"), (item.get("title") or "")[:30],
                                      item.get("reason")))

    print("\nWARNINGS (%d)" % len(proposal["warnings"]))
    for warning in proposal["warnings"]:
        print("  - %s" % warning)

    # A second, independent check: nothing may finish after its venue closes.
    print("\nINDEPENDENT CHECK: opening-hours violations in the proposal")
    violations = 0
    for item in proposal["items"]:
        listing = replanner.load_listing(item)
        hours = replanner._venue_hours(item, listing) if listing else None
        if not hours:
            continue
        _, close_m, _ = hours
        end = replanner.parse_dt(item.get("endTime"))
        start = replanner.parse_dt(item.get("startTime"))
        if not (start and end):
            continue
        midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
        closes = midnight + timedelta(minutes=close_m)
        if end > closes and closes.date() == midnight.date():
            violations += 1
            print("  VIOLATION %-30s ends %s, closes %s" % (
                (item.get("title") or "")[:30], end.strftime("%H:%M"),
                listing.get("closingTime")))
    print("  %d violation(s)." % violations)
    return 0


if __name__ == "__main__":
    sys.exit(main())
