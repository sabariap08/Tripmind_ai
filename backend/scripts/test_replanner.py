"""Replanner behaviour checks - the cases the old `+N minutes` shift got wrong.

    python scripts/test_replanner.py

No database and no network: every listing is injected, so this runs offline and
is safe to run before the app is started.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import replanner  # noqa: E402

# --------------------------------------------------------------------- fixtures
LISTINGS = {
    "fort": {"_id": "fort", "name": "Fort St. George", "city": "Chennai",
             "openingTime": "09:00", "closingTime": "17:00", "entryFee": 20.0,
             "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday",
                             "Friday", "Saturday", "Sunday"]},
    "closed-mon": {"_id": "closed-mon", "name": "Fort Museum", "city": "Chennai",
                   "openingTime": "10:00", "closingTime": "19:00", "entryFee": 50.0,
                   "workingDays": ["Tuesday", "Wednesday", "Thursday", "Friday",
                                   "Saturday", "Sunday"]},
    "marina": {"_id": "marina", "name": "Marina Beach", "city": "Chennai",
               "openingTime": "05:00", "closingTime": "21:00", "entryFee": 0.0,
               "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday",
                               "Friday", "Saturday", "Sunday"]},
    "temple": {"_id": "temple", "name": "Kapaleeshwarar Temple", "city": "Chennai",
               "openingTime": "05:00", "closingTime": "21:00", "entryFee": 0.0,
               "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday",
                               "Friday", "Saturday", "Sunday"]},
    "night": {"_id": "night", "name": "Night Market", "city": "Chennai",
              "openingTime": "18:00", "closingTime": "01:00", "entryFee": 0.0,
              "workingDays": []},
}

_real_load = replanner.load_listing
replanner.load_listing = lambda item: LISTINGS.get(
    replanner._strip_prefix(item.get("bookableId")))


def trip(start="2026-09-17", end="2026-09-17", **extra):
    base = {"startDate": start, "endDate": end, "origin": "Coimbatore",
            "destination": "Chennai"}
    base.update(extra)
    return base


def item(title, kind, day, sh, eh, cost=0.0, ref=None, order=0):
    return {
        "_id": "%s-%s-%s" % (kind, day, order),
        "title": title, "type": kind, "day": day, "sortOrder": order,
        "startTime": "2026-09-%02dT%s:00" % (16 + day, sh),
        "endTime": "2026-09-%02dT%s:00" % (16 + day, eh),
        "cost": cost, "currency": "INR", "status": "PLANNED",
    } | ({"bookableId": ref} if ref else {})


RESULTS = []


def check(label, condition, detail=""):
    RESULTS.append((label, bool(condition), detail))
    print("  [%s] %s%s" % ("PASS" if condition else "FAIL", label,
                           ("  -- " + detail) if detail and not condition else ""))


# ------------------------------------------------------------------ test 1: close
print("\n1. A delayed stop that can no longer be reached before closing is handled")
# Train arrives 14:00. Fort closes at 17:00. A 5h delay means reaching it at
# 19:00 - impossible. The old code shifted it to 19:00 and left it there.
t = trip()
sel = {"items": [
    item("TRAIN", "TRAIN", 1, "09:00", "14:00", 355.0, order=0),
    item("Fort St. George", "ACTIVITY", 1, "16:00", "17:00", 20.0, "spot:fort", 1),
    item("Marina Beach", "ACTIVITY", 1, "18:00", "19:00", 0.0, "spot:marina", 2),
]}
p = replanner.build_proposal(t, sel, delay_minutes=300, reason="delay")
titles = [i["title"] for i in p["items"]]
check("Fort St. George removed, not left at an impossible time",
      "Fort St. George" not in titles, "still present: %s" % titles)
check("a drop is reported with a reason",
      any(d["title"] == "Fort St. George" and d["reason"] for d in p["dropped"]))
check("a warning is shown to the user",
      any("Fort St. George" in w for w in p["warnings"]))
check("Marina Beach (open until 21:00) is kept",
      "Marina Beach" in titles, "dropped: %s" % [d["title"] for d in p["dropped"]])


# ------------------------------------------------------- test 2: hours respected
print("\n2. No surviving item finishes after its venue closes")
ok = True
detail = []
for it in p["items"]:
    ref = replanner._strip_prefix(it.get("bookableId"))
    listing = LISTINGS.get(ref)
    if not listing:
        continue
    st, en = replanner.parse_dt(it["startTime"]), replanner.parse_dt(it["endTime"])
    if not (st and en):
        ok = False
        detail.append("%s missing times" % it["title"])
        continue
    date = replanner.day_date(t, it["day"])
    hours = replanner._venue_hours(it, listing)
    if not hours:
        continue
    _, close_m, _ = hours
    closes = date.replace(hour=0, minute=0) + timedelta(minutes=close_m)
    if en > closes and closes.date() == date.date():
        ok = False
        detail.append("%s ends %s after closing %s"
                      % (it["title"], en.strftime("%H:%M"), listing["closingTime"]))
check("all items finish before their venue closes", ok, "; ".join(detail))


# -------------------------------------------------------- test 3: real cost maths
print("\n3. additionalCost is computed, not asserted")
t2 = trip()
sel2 = {"items": [
    item("TRAIN", "TRAIN", 1, "09:00", "14:00", 355.0, order=0),
    # Stored cost says 500, catalogue says 40. The catalogue must win.
    item("Shore Temple", "ACTIVITY", 1, "15:00", "16:00", 500.0, "spot:marina", 1),
]}
p2 = replanner.build_proposal(t2, sel2, delay_minutes=0, reason="manual")
check("catalogue price overrides the stale stored cost",
      any(abs(i["cost"] - 0.0) < 0.01 for i in p2["items"]),
      "costs: %s" % [i["cost"] for i in p2["items"]])
expected = round(p2["cost"]["revised"] - p2["cost"]["original"], 2)
check("additionalCost equals revised - original",
      abs(p2["cost"]["additional"] - expected) < 0.01,
      "additional=%s expected=%s" % (p2["cost"]["additional"], expected))
check("the summary never claims 'no additional charges' unconditionally",
      "no additional charges" not in p2["summary"].lower())


# ------------------------------------------------------------ test 4: closed day
print("\n4. A venue closed on that weekday is dropped")
# 2026-09-21 is a Monday.
t3 = trip(start="2026-09-21", end="2026-09-21")
sel3 = {"items": [
    item("TRAIN", "TRAIN", 1, "09:00", "11:00", 100.0, order=0),
    item("Fort Museum", "ACTIVITY", 1, "12:00", "13:00", 50.0, "spot:closed-mon", 1),
]}
p3 = replanner.build_proposal(t3, sel3, delay_minutes=0, reason="manual")
check("Monday-closed venue removed",
      "Fort Museum" not in [i["title"] for i in p3["items"]])
check("the reason names the weekday",
      any("Monday" in (d.get("reason") or "") for d in p3["dropped"]),
      "reasons: %s" % [d.get("reason") for d in p3["dropped"]])


# --------------------------------------------------------- test 5: past midnight
print("\n5. A venue that runs past midnight is handled")
t4 = trip()
sel4 = {"items": [
    item("TRAIN", "TRAIN", 1, "09:00", "16:00", 100.0, order=0),
    item("Night Market", "ACTIVITY", 1, "20:00", "23:00", 0.0, "spot:night", 1),
]}
p4 = replanner.build_proposal(t4, sel4, delay_minutes=0, reason="manual")
check("the past-midnight venue survives",
      "Night Market" in [i["title"] for i in p4["items"]],
      "dropped: %s" % [d["title"] for d in p4["dropped"]])


# --------------------------------------------------------- test 6: no-change path
print("\n6. A replan with nothing wrong changes nothing")
t5 = trip()
sel5 = {"items": [
    item("TRAIN", "TRAIN", 1, "06:00", "09:00", 355.0, order=0),
    item("Marina Beach", "ACTIVITY", 1, "10:00", "12:00", 0.0, "spot:marina", 1),
    item("Kapaleeshwarar Temple", "ACTIVITY", 1, "15:00", "17:00", 0.0, "spot:temple", 2),
]}
p5 = replanner.build_proposal(t5, sel5, delay_minutes=0, reason="manual")
check("no items were moved", not p5["changes"],
      "changes: %s" % [(c["type"], c["title"]) for c in p5["changes"]])
check("nothing was dropped", not p5["dropped"])
check("item count is preserved", len(p5["items"]) == len(sel5["items"]))


# ------------------------------------------------------------- test 7: is pure
print("\n7. The proposal is a pure function of its inputs")
check("build_proposal twice on the same input gives the same cost",
      replanner.build_proposal(t5, sel5, delay_minutes=0)["cost"]
      == p5["cost"])


# ---------------------------------------------------------------------- summary
failed = [r for r in RESULTS if not r[1]]
print("\n%d/%d checks passed." % (len(RESULTS) - len(failed), len(RESULTS)))
if failed:
    for label, _, detail in failed:
        print("  FAILED: %s  %s" % (label, detail))
    sys.exit(1)
print("Replanner is behaving.")
