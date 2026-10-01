"""Budget view for a trip: what was planned, what was paid, what is left.

Why this is a service and not a pile of arithmetic in the trip page
------------------------------------------------------------------
The trip page had its own inline cost arithmetic, and the server had a third,
different implementation. They disagreed. Concretely, before this module:

* ``budgetUnlimited`` was computed when a trip was created and then **never
  written to the document** (``routes.create_trip`` put it into ``data`` and the
  trip literal did not copy it). 0 of 37 trips in the live database have the
  field. ``GET /api/trips/<id>`` therefore reported ``budgetUnlimited: false``
  for trips that were created with an unlimited budget, i.e. the exact opposite
  of the truth. The page only got this right by accident, through a
  ``|| !tripData.budget`` fallback in the template.
* Three different places re-derived "is this unlimited?" and only one of them
  used the ``budget in (None, 0)`` test that ``create_trip`` uses.

So the rules now live here, once, and both the API and the page consume them.

What this module refuses to do
------------------------------
It never invents a number. If the selected itinerary carries no costs, the
estimate is ``None``, not ``0`` - "we could not price this" and "this is free"
are different facts and the traveller is entitled to know which one they are
looking at. Likewise, bookings whose ``total`` is missing or zero are excluded
from the spend figure and *counted separately*, because silently summing past
them understates what the traveller has actually committed to.
"""

from __future__ import annotations

# One category map, used by the API, the trip page, and any export. Keyed by the
# item type the itineraries actually store.
#
# The previous inline version in trip.html read ``item.type`` and silently
# bucketed anything it did not recognise into "food", which meant a spot entry
# or a guide fee landed in the dining total. Unrecognised types now fall into
# "other" and are surfaced as such rather than being quietly mislabelled.
CATEGORY_BY_TYPE = {
    "FLIGHT": "flights",
    "HOTEL": "stay",
    "STAY": "stay",
    "RESORT": "stay",
    "BUS": "transport",
    "TRAIN": "transport",
    "TRANSPORT": "transport",
    "TRANSFER": "transport",
    "CAB": "transport",
    "AUTO": "transport",
    "RENTAL": "transport",
    "ACTIVITY": "activities",
    "SPOT": "activities",
    "TOUR": "activities",
    "GUIDE": "activities",
    "TICKET": "activities",
    "MEAL": "food",
    "RESTAURANT": "food",
    "FOOD": "food",
}

CATEGORY_LABELS = {
    "flights": "Flights",
    "stay": "Stay",
    "transport": "Transport",
    "activities": "Activities",
    "food": "Food",
    "other": "Other",
}

# A category that never appeared in the itineraries we have seen. Kept explicit
# so "Other" is a real bucket in the UI, not a dumping ground.
_KNOWN_CATEGORIES = tuple(CATEGORY_LABELS)


def category_for(item_type):
    """Which budget bucket an itinerary item belongs to."""
    return CATEGORY_BY_TYPE.get(str(item_type or "").upper(), "other")


def _money(value):
    """Coerce to a non-negative number, or None when there is no number."""
    if value is None or value == "":
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount != amount or amount in (float("inf"), float("-inf")):
        # NaN and infinities come from JSON-capable clients and would poison
        # every sum downstream.
        return None
    return amount if amount > 0 else None


def selected_itinerary(trip):
    """The itinerary the traveller is actually going with."""
    itineraries = trip.get("itineraries") or []
    chosen = [i for i in itineraries if (i or {}).get("status") == "SELECTED"]
    if chosen:
        return chosen[0]
    # No explicit selection: the newest itinerary with any cost is the most
    # useful thing to price against, and the trip page does the same.
    priced = [i for i in itineraries if _plan_total(i) is not None]
    return priced[0] if priced else (itineraries[0] if itineraries else None)


def _plan_total(itin):
    """A plan's total, or None when nothing in it is priced."""
    if not itin:
        return None
    total = _money(itin.get("totalCost"))
    if total is not None:
        return total
    summed = 0.0
    seen = False
    for item in itin.get("items") or []:
        cost = _money((item or {}).get("cost"))
        if cost is not None:
            summed += cost
            seen = True
    return summed if seen else None


def breakdown_by_category(itin):
    """Per-category totals for one itinerary, plus an honest unpriced count."""
    buckets = {}
    unpriced = 0
    for item in (itin or {}).get("items") or []:
        item = item or {}
        cost = _money(item.get("cost"))
        if cost is None:
            unpriced += 1
            continue
        key = category_for(item.get("type"))
        buckets[key] = buckets.get(key, 0.0) + cost
    # Keep a stable, deliberate ordering rather than whatever dict order gives.
    ordered = [(key, buckets[key]) for key in _KNOWN_CATEGORIES if key in buckets]
    ordered += [(k, v) for k, v in sorted(buckets.items())
                if k not in _KNOWN_CATEGORIES]
    return ordered, unpriced


def is_unlimited(trip):
    """Whether the trip was created without a budget ceiling.

    Matches ``create_trip``: an explicit unlimited flag, or a budget of 0/absent.
    Both spellings have to be accepted because trips created before the flag was
    stored only carry ``budget: 0``.
    """
    if trip.get("budgetUnlimited"):
        return True
    budget = trip.get("budget")
    return budget is None or _money(budget) is None


def booked_spend(bookings):
    """Total of priced, non-cancelled bookings, plus what could not be priced."""
    total = 0.0
    priced = 0
    unpriced = 0
    cancelled = 0
    for booking in bookings or []:
        booking = booking or {}
        status = str(booking.get("status") or "").upper()
        if status in ("CANCELLED", "REJECTED"):
            cancelled += 1
            continue
        amount = _money(booking.get("total"))
        if amount is None:
            unpriced += 1
            continue
        total += amount
        priced += 1
    return total, {"priced": priced, "unpriced": unpriced, "cancelled": cancelled}


def build_budget_view(trip, bookings=None):
    """The complete budget picture for one trip.

    Returns a dict shaped for direct JSON. Every money field is either a number
    or ``None``; ``None`` always means "we do not know", never zero.
    """
    trip = trip or {}
    travelers = trip.get("travelers") or 1
    try:
        travelers = max(1, int(travelers))
    except (TypeError, ValueError):
        travelers = 1

    unlimited = is_unlimited(trip)
    per_traveller = None if unlimited else _money(trip.get("budget"))
    budget_total = None if per_traveller is None else per_traveller * travelers

    itin = selected_itinerary(trip)
    categories, unpriced_items = breakdown_by_category(itin)
    estimated = _plan_total(itin)

    spent, booking_counts = booked_spend(bookings or [])

    # Headroom is only meaningful when both sides are known.
    headroom = None
    if budget_total is not None and estimated is not None:
        headroom = budget_total - estimated
    elif budget_total is not None and spent > 0:
        headroom = budget_total - spent

    # Utilisation is measured against the estimate when there is one, because
    # that is the plan the traveller agreed to. Falling back to actual spend is
    # deliberate but labelled, so nobody reads "42% of budget used" for a trip
    # that has not been booked yet.
    basis = None
    measured = None
    if estimated is not None:
        basis, measured = "estimate", estimated
    elif spent > 0:
        basis, measured = "booked", spent

    utilisation = None
    if basis and budget_total:
        utilisation = round(measured / budget_total * 100, 1)

    if unlimited:
        status = "unlimited"
    elif utilisation is None:
        status = "unknown"
    elif utilisation > 100:
        status = "over"
    elif utilisation >= 90:
        status = "tight"
    else:
        status = "comfortable"

    return {
        "currency": trip.get("currency") or "INR",
        "travelers": travelers,
        "unlimited": unlimited,
        "budgetPerTraveller": per_traveller,
        "budgetTotal": budget_total,
        "estimatedTotal": estimated,
        "bookedTotal": spent if booking_counts["priced"] else None,
        "bookings": booking_counts,
        "utilisationPct": utilisation,
        "utilisationBasis": basis,
        "headroom": headroom,
        "perTravellerEstimated": (estimated / travelers
                                  if estimated is not None else None),
        "perTravellerBooked": (spent / travelers
                               if booking_counts["priced"] else None),
        "status": status,
        "categories": [
            {"key": key,
             "label": CATEGORY_LABELS.get(key, key.title()),
             "amount": amount,
             "shareOfSpend": (round(amount / measured * 100, 1)
                              if measured else None),
             "shareOfBudget": (round(amount / budget_total * 100, 1)
                               if budget_total else None)}
            for key, amount in categories
        ],
        # Items and bookings with no price at all. Surfaced because a total
        # that silently omits them is a total the traveller cannot trust.
        "unpricedItems": unpriced_items,
        "planType": (itin or {}).get("planType") or (itin or {}).get("title"),
        "hasItinerary": itin is not None,
    }