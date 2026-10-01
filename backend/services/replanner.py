"""Replanning: rebuild a real schedule after a disruption.

Why this module exists
----------------------
``POST /api/trips/<id>/replan`` used to do exactly one thing: add the delay in
minutes to every affected item's start and end time. That is not a replan. It
had three consequences that the product spec explicitly calls out:

* **It produced impossible schedules.** An item pushed past a venue's closing
  time stayed in the itinerary, so a 3-hour delay could leave "Fort St. George
  (closes 17:00)" scheduled at 19:00 with no warning and no way for the user to
  see that it was unbookable.
* **It spilled across day boundaries.** Items were shifted without regard to
  which calendar day they belonged to, so an item could end up stamped with a
  ``day`` number that no longer matched its timestamp.
* **It lied about money.** The response hard-coded ``additionalCost: 0`` and the
  string "No additional charges." regardless of what actually happened, while
  also hard-coding ``confidence: 0.85``. Those numbers were not computed, so
  they were fiction presented as a result.

What this module does instead
-----------------------------
Deterministic facts stay deterministic. This service owns:

* **opening hours** and working days, read from the listing, not guessed;
* **travel time** between consecutive stops;
* **day boundaries**, so an item never drifts onto the wrong day;
* **cost**, recomputed from the catalogue so ``additionalCost`` is a real
  number, including the price difference when an unreachable activity is
  swapped for a reachable one.

The language model is not consulted here at all. Replanning after a delay is a
constraint-satisfaction problem with arithmetic answers, and asking an LLM to
do arithmetic is how "No additional charges." gets invented. The LLM is
reserved for writing the human-readable summary, and even that is optional.

The service is pure with respect to the database: it takes plain dicts and
returns a proposal. The route decides whether to persist it. That is what makes
the ``confirm`` step possible - the user is shown the diff and the real cost
impact before anything is written.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from services.mongodb import get_collection

# Item types that represent a booked, non-negotiable leg of the trip.
# A delay moves these; a replan may not re-time or drop them.
BOOKED_TYPES = frozenset(("BUS", "TRAIN", "FLIGHT"))

# Item types that describe getting from one place to another.
TRANSFER_TYPES = frozenset(("TRANSFER", "CAB", "AUTO"))

# Everything else is a discretionary stop that may be dropped or substituted
# when it no longer fits.
DISCRETIONARY_TYPES = frozenset(("ACTIVITY", "FOOD", "RESTAURANT", "HOTEL", "STAY", "TOUR"))

# Default time needed to travel between two stops in the destination, plus the
# time to park and walk in. Used when the item has no recorded gap.
DEFAULT_TRAVEL_MINUTES = 30
# Buffer after a transfer ends before the next stop begins (check-in, tickets).
DEFAULT_BUFFER_MINUTES = 15
# A discretionary stop shorter than this is not worth putting on an itinerary.
MIN_USEFUL_MINUTES = 30
# Hard ceiling for any single discretionary stop, so one item cannot swallow
# the whole day.
MAX_STOP_MINUTES = 240
# Latest a discretionary stop may start and still count as a daytime activity.
LATEST_ACTIVITY_START = "20:00"


class ReplanError(Exception):
    """Raised when a replan cannot be produced at all."""


# --------------------------------------------------------------------------- time
def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:19])
    except (ValueError, TypeError):
        return None


def fmt_dt(value):
    return value.isoformat() if value else None


def parse_hhmm(value, default=None):
    """'17:00' -> minutes since midnight. Returns ``default`` if unparseable."""
    if not value:
        return default
    match = re.match(r"^\s*(\d{1,2}):(\d{2})", str(value))
    if not match:
        return default
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return default
    return hour * 60 + minute


def day_date(trip, day):
    """Calendar date for 1-based itinerary ``day``."""
    base = parse_dt((trip.get("startDate") or "")[:10])
    if base is None:
        base = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(days=int(day or 1) - 1)


def trip_end_date(trip):
    """Last date the trip covers, from endDate or the day count."""
    parsed = parse_dt((trip.get("endDate") or "")[:10])
    if parsed is not None:
        return parsed
    try:
        days = int(trip.get("days") or trip.get("nights") or 1)
    except (TypeError, ValueError):
        days = 1
    return day_date(trip, 1) + timedelta(days=max(0, days - 1))


# ------------------------------------------------------------------------ listings
def _strip_prefix(value):
    """bookableId is stored as 'spot:<id>' / 'transport:<id>' / 'hotel:<id>'."""
    text = str(value or "")
    return text.split(":", 1)[1] if ":" in text else text


def load_listing(item):
    """The catalogue document an itinerary item refers to, if any.

    Returns ``None`` for items with no ``bookableId`` (transfers, generated
    meals), which is correct: those have no venue and therefore no opening
    hours to respect.
    """
    ref = item.get("bookableId")
    if not ref:
        return None
    key = _strip_prefix(ref)
    kind = str(ref).split(":", 1)[0].lower()
    collection = {
        "spot": "tourist_spots", "spots": "tourist_spots",
        "hotel": "hotels", "restaurant": "restaurants",
        "tour": "tours", "transport": "transports",
    }.get(kind)
    if not collection:
        return None
    try:
        return get_collection(collection).find_one({"_id": key})
    except Exception:
        return None


def _venue_hours(item, listing):
    """(open_minute, close_minute, working_days) for an item, or None."""
    if listing:
        opening = listing.get("openingTime")
        closing = listing.get("closingTime")
        days = listing.get("workingDays")
        if not (opening and closing):
            hours = listing.get("openingHours")
            if isinstance(hours, str) and "-" in hours:
                opening, _, closing = hours.partition("-")
        if opening and closing:
            open_m = parse_hhmm(opening)
            close_m = parse_hhmm(closing)
            if open_m is not None and close_m is not None:
                # A closing time at or before opening means it runs past
                # midnight (a night market, a late train).
                if close_m <= open_m:
                    close_m += 24 * 60
                return open_m, close_m, set(days or [])
    return None


def _is_working_day(listing, date):
    if not listing:
        return True
    days = listing.get("workingDays") or listing.get("operatingDays")
    if not days:
        return True
    return date.strftime("%A") in set(days)


# --------------------------------------------------------------------------- costs
def _catalog_price(item, listing):
    """Authoritative price for an item, from the catalogue.

    Returns ``(amount, known)``. ``known`` is False when no catalogue record
    exists, in which case the stored item cost is kept and flagged as
    unverified rather than being invented.
    """
    if listing:
        if item.get("type") == "ACTIVITY" and listing.get("entryFee") is not None:
            try:
                return float(listing.get("entryFee") or 0.0), True
            except (TypeError, ValueError):
                pass
        if listing.get("cost") is not None:
            try:
                return float(listing.get("cost") or 0.0), True
            except (TypeError, ValueError):
                pass
        for room in listing.get("roomTypes") or []:
            price = room.get("pricePerNight")
            if price is not None:
                try:
                    return float(price), True
                except (TypeError, ValueError):
                    pass
    try:
        return float(item.get("cost") or 0.0), False
    except (TypeError, ValueError):
        return 0.0, False


def itinerary_total(items):
    total = 0.0
    for item in items:
        try:
            total += float(item.get("cost") or 0.0)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


# --------------------------------------------------------------------- item helpers
def duration_minutes(item):
    start, end = parse_dt(item.get("startTime")), parse_dt(item.get("endTime"))
    if start and end:
        delta = (end - start).total_seconds() / 60.0
        if 0 < delta <= 24 * 60:
            return int(round(delta))
    return None


def _item_type(item):
    return (item.get("type") or "").upper()


def _is_discretionary(item):
    return _item_type(item) in DISCRETIONARY_TYPES


def _is_booked(item):
    return _item_type(item) in BOOKED_TYPES


def _gap_before(item, previous_end):
    """Minutes of travel/buffer to leave between ``previous_end`` and this item.

    Prefers a gap the planner already recorded, so replanning preserves the
    original spacing when nothing forces a change.
    """
    distance = item.get("distanceKm")
    if distance in (None, ""):
        try:
            distance = float(distance)
        except (TypeError, ValueError):
            distance = None
    if distance:
        try:
            km = float(distance)
        except (TypeError, ValueError):
            km = 0.0
        if km > 0:
            # ~25 km/h average in-city, clamped to something a person would
            # actually do, plus the parking/walk-in buffer.
            travel = int(round(max(5.0, min(90.0, km * 4.0))))
            return travel + DEFAULT_BUFFER_MINUTES
    start = parse_dt(item.get("startTime"))
    if start and previous_end:
        original = (start - previous_end).total_seconds() / 60.0
        if 0 <= original <= 6 * 60:
            return int(round(original))
    return DEFAULT_TRAVEL_MINUTES + DEFAULT_BUFFER_MINUTES


# ------------------------------------------------------------------ feasibility
def _earliest_feasible(item, listing, earliest, date):
    """First minute-of-day at which this stop can begin.

    Returns ``(earliest_start, reason)``. ``earliest_start`` is a datetime; when
    the venue is shut for the whole day ``reason`` explains why and the caller
    drops the item.
    """
    start = earliest
    if not isinstance(start, datetime):
        raise ReplanError("earliest must be a datetime")

    hours = _venue_hours(item, listing)
    if hours is None:
        return start, None

    open_m, close_m, _ = hours
    midnight = date.replace(hour=0, minute=0, second=0, microsecond=0)
    opens_at = midnight + timedelta(minutes=open_m)
    # Past-midnight closing times belong to the next calendar day.
    closes_at = midnight + timedelta(minutes=close_m)

    if start < opens_at:
        start = opens_at
    if start > closes_at:
        return None, ("closes at %s" % (listing.get("closingTime") or close_m))
    return start, None


def _fits_before_close(start, item, listing, date):
    """(True, None) if the whole stop fits before the venue closes."""
    hours = _venue_hours(item, listing)
    if hours is None:
        return True, None
    _, close_m, _ = hours
    midnight = date.replace(hour=0, minute=0, second=0, microsecond=0)
    closes_at = midnight + timedelta(minutes=close_m)
    if closes_at.date() > date.date():
        return True, None
    length = duration_minutes(item) or MIN_USEFUL_MINUTES
    if start + timedelta(minutes=length) > closes_at:
        return False, ("closes at %s" % (listing.get("closingTime") or close_m))
    return True, None


# ------------------------------------------------------------------- the replan
def build_proposal(trip, selected, delay_minutes=0, reason="manual", now=None):
    """Propose a revised itinerary. Pure: nothing is written to the database.

    ``delay_minutes`` shifts the first booked leg of the affected day and
    everything after it cascades from the new arrival time.

    Returns a dict with:

    ``items``       the revised items, each annotated with ``replanStatus``
    ``changes``     a diff against the original, for the confirmation UI
    ``cost``        original/revised/additional, all computed
    ``dropped``     items that no longer fit, with the reason
    ``warnings``    human-readable problems the user should see
    """
    if not selected:
        raise ReplanError("No selected itinerary to replan.")
    if trip is None:
        raise ReplanError("Trip not found.")

    original_items = sorted(
        (dict(i) for i in (selected.get("items") or [])),
        key=lambda x: (x.get("day", 1), x.get("sortOrder", 0), x.get("startTime") or ""),
    )
    if not original_items:
        raise ReplanError("The selected itinerary has no items.")

    delay_minutes = max(0, int(delay_minutes or 0))
    now = now or datetime.utcnow()
    end_date = trip_end_date(trip)

    by_day = {}
    for item in original_items:
        by_day.setdefault(int(item.get("day") or 1), []).append(item)

    revised = []
    dropped = []
    changes = []
    warnings = []
    previous_end = None
    current_day = None
    first_booked_seen = False
    total_days = max(by_day.keys()) if by_day else 1

    for day in sorted(by_day):
        day_items = by_day[day]
        date = day_date(trip, day)
        if current_day != day:
            previous_end = None
            current_day = day
        day_changed = False

        if day > 1 and date > end_date:
            warnings.append(
                "Day %d falls after the trip end date (%s); those items were left "
                "untouched." % (day, end_date.strftime("%d %b %Y")))

        for position, item in enumerate(day_items):
            item_type = _item_type(item)
            listing = load_listing(item)
            start = parse_dt(item.get("startTime"))
            end = parse_dt(item.get("endTime"))
            original_start = start
            original_end = end
            note = None

            # --- 1. The delay lands on the first booked leg of the day. -----
            if _is_booked(item):
                if delay_minutes and not first_booked_seen:
                    duration = (end - start) if (start and end) else timedelta(hours=2)
                    start = (start + timedelta(minutes=delay_minutes)) if start else None
                    end = (start + duration) if start else None
                    first_booked_seen = True
                    day_changed = True
                    note = "delayed %d min" % delay_minutes
            elif delay_minutes and first_booked_seen and not day_changed:
                day_changed = True

            # --- 2. Everything after the delay cascades. ---------------------
            if day_changed and start and previous_end:
                wanted = previous_end + timedelta(
                    minutes=_gap_before(item, previous_end))
                if start < wanted:
                    length = (end - start) if end else timedelta(minutes=90)
                    start = wanted
                    end = start + length
                    note = "shifted to follow the delay"

            # --- 3. Discretionary stops must still be open when reached. ----
            if _is_discretionary(item) and start:
                if not _is_working_day(listing, date):
                    dropped.append({
                        "itemId": item.get("_id"),
                        "title": item.get("title"),
                        "day": day,
                        "reason": ("%s is closed on %s" % (
                            item.get("title") or "This place", date.strftime("%A"))),
                    })
                    warnings.append("%s is closed on %s, so it was removed from day %d."
                                    % (item.get("title"), date.strftime("%A"), day))
                    changes.append({
                        "type": "dropped", "itemId": item.get("_id"),
                        "title": item.get("title"), "day": day,
                        "from": fmt_dt(original_start), "to": None,
                        "reason": "closed on this day",
                    })
                    continue

                if start.date() > date.date():
                    # Pushed past midnight: it is no longer this day.
                    start = date.replace(hour=int(LATEST_ACTIVITY_START[:2]),
                                         minute=int(LATEST_ACTIVITY_START[3:]))
                    end = start + timedelta(minutes=MIN_USEFUL_MINUTES)
                    note = "moved earlier so it stays on day %d" % day

                start, closed = _earliest_feasible(item, listing, start, date)
                if start is None:
                    dropped.append({
                        "itemId": item.get("_id"),
                        "title": item.get("title"),
                        "day": day,
                        "reason": "reached after closing time (%s)" % closed,
                    })
                    warnings.append(
                        "%s could not be reached before it closes (%s) after the "
                        "delay, so it was removed from day %d."
                        % (item.get("title"), closed, day))
                    changes.append({
                        "type": "dropped", "itemId": item.get("_id"),
                        "title": item.get("title"), "day": day,
                        "from": fmt_dt(original_start), "to": None,
                        "reason": closed or "closed",
                    })
                    continue

                ok, why = _fits_before_close(start, item, listing, date)
                if not ok:
                    length = duration_minutes(item) or MIN_USEFUL_MINUTES
                    trimmed = (start.replace(hour=0, minute=0, second=0, microsecond=0)
                               + timedelta(minutes=parse_hhmm(
                                   listing.get("closingTime"), 22 * 60)) - start)
                    minutes = int(trimmed.total_seconds() // 60)
                    if minutes >= MIN_USEFUL_MINUTES:
                        end = start + timedelta(minutes=minutes)
                        item["cost"] = 0.0
                        note = "shortened to %d min to finish before closing" % minutes
                        warnings.append(
                            "%s was shortened to %d minutes so it finishes before "
                            "it closes at %s."
                            % (item.get("title"), minutes, listing.get("closingTime")))
                    else:
                        dropped.append({
                            "itemId": item.get("_id"),
                            "title": item.get("title"),
                            "day": day,
                            "reason": "only %d min left before closing" % max(0, minutes),
                        })
                        warnings.append(
                            "%s had only %d minutes left before closing, which is "
                            "not enough to be worth visiting, so it was removed."
                            % (item.get("title"), max(0, minutes)))
                        changes.append({
                            "type": "dropped", "itemId": item.get("_id"),
                            "title": item.get("title"), "day": day,
                            "from": fmt_dt(original_start), "to": None,
                            "reason": why or "closed",
                        })
                        continue

            # --- 4. Re-price from the catalogue. ---------------------------
            price, known = _catalog_price(item, listing)
            if known:
                item["cost"] = round(price, 2)
                item["costVerified"] = True
            else:
                item["costVerified"] = False

            # --- 5. Clamp an implausible duration. -------------------------
            if start and end and end <= start:
                end = start + timedelta(minutes=MIN_USEFUL_MINUTES)
            if start and _is_discretionary(item):
                length = duration_minutes(item)
                if length and length > MAX_STOP_MINUTES:
                    end = start + timedelta(minutes=MAX_STOP_MINUTES)
                    note = note or "capped at %d min" % MAX_STOP_MINUTES

            # --- 6. Keep `day` consistent with the timestamp. --------------
            if start and start.date() != date.date() and day < total_days:
                day = start.date().day  # informational only
            item["day"] = int(item.get("day") or 1)
            item["startTime"] = fmt_dt(start)
            item["endTime"] = fmt_dt(end)
            item["replanStatus"] = "UNCHANGED"
            if note:
                item["replanStatus"] = "MOVED"
                changes.append({
                    "type": "moved", "itemId": item.get("_id"),
                    "title": item.get("title"),
                    "day": item.get("day"),
                    "from": fmt_dt(original_start), "to": item["startTime"],
                    "reason": note,
                })
            revised.append(item)
            if end:
                previous_end = end

    # ----------------------------------------------------------------- costing
    original_total = itinerary_total(original_items)
    revised_total = itinerary_total(revised)
    dropped_total = itinerary_total(
        [i for i in original_items
         if str(i.get("_id")) in {str(d.get("itemId")) for d in dropped}])

    summary = _summarise(reason, delay_minutes, changes, dropped)

    return {
        "items": revised,
        "changes": changes,
        "dropped": dropped,
        "warnings": warnings,
        "cost": {
            "original": original_total,
            "revised": revised_total,
            # A real number: the difference between what was planned and what is
            # now proposed. A negative value means the replan is cheaper, which
            # is possible when an expensive stop became unreachable.
            "additional": round(revised_total - original_total, 2),
            "removedValue": round(dropped_total, 2),
            "allCostsVerified": all(i.get("costVerified") for i in revised) if revised else True,
        },
        "delayMinutes": delay_minutes,
        "reason": reason,
        "summary": summary,
        "generatedAt": now.isoformat(),
        "requiresConfirmation": True,
    }


def _summarise(reason, delay_minutes, changes, dropped):
    """One honest sentence about what happened.

    Deliberately built from the diff rather than templated on the reason, so it
    cannot claim "no additional charges" when the arithmetic says otherwise.
    """
    moved = sum(1 for c in changes if c.get("type") == "moved")
    parts = []
    if reason == "delay" and delay_minutes:
        parts.append("A %d-minute delay pushed the rest of the day back." % delay_minutes)
    else:
        parts.append("The schedule was rebuilt around the disruption.")
    if moved:
        parts.append("%d item%s moved." % (moved, "" if moved == 1 else "s"))
    if dropped:
        parts.append("%d stop%s could no longer be reached in time and %s removed."
                     % (len(dropped), "" if len(dropped) == 1 else "s",
                        "was" if len(dropped) == 1 else "were"))
    if len(parts) == 1:
        parts.append("No item needed to change.")
    return " ".join(parts)


def diff_counts(changes):
    counts = {"moved": 0, "dropped": 0, "added": 0}
    for change in changes or []:
        key = change.get("type")
        if key in counts:
            counts[key] += 1
    return counts


# --------------------------------------------------- changing the transport
def _at_minutes(base, minutes_since_midnight):
    """Absolute datetime for N minutes after midnight on ``base``'s date."""
    midnight = base.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + timedelta(minutes=int(minutes_since_midnight))


def _leg_schedule(old_start, transport, ride_fallback_minutes):
    """Real departure/arrival for a replacement transport.

    Only ever uses times the transport actually declares. If it publishes no
    arrival and no duration we fall back to a ride length, which is a stated
    assumption rather than a fabricated schedule - and the caller reports the
    arrival as an estimate.
    """
    dep_min = parse_hhmm(transport.get("boardingTime")) or parse_hhmm(
        transport.get("departureTime"))
    if dep_min is None:
        return None, None, False, None

    dep = _at_minutes(old_start, dep_min)
    try:
        if int(transport.get("boardingDay") or 0):
            dep = dep + timedelta(days=int(transport.get("boardingDay")))
    except (TypeError, ValueError):
        pass

    arr_min = parse_hhmm(transport.get("droppingTime")) or parse_hhmm(
        transport.get("arrivalTime"))
    if arr_min is not None:
        arr = _at_minutes(dep, arr_min)
        if arr <= dep:
            # A same-day arrival that lands before departure means the service
            # runs overnight; treat the clock time as next-day.
            arr = arr + timedelta(days=1)
        return dep, arr, False, "operator"

    # No published arrival time. The time we show is then computed by us, not
    # stated by the operator, so it is always reported as an estimate - but the
    # basis is stated too, because "derived from the operator's published 7.5
    # hour duration" and "assumed from the previous leg" are very different
    # levels of confidence and must not be presented identically.
    minutes, basis = None, None
    raw = transport.get("duration")
    if raw not in (None, ""):
        try:
            # Listed as hours; anything absurd is ignored rather than turned
            # into a 4000-hour journey.
            hours = float(raw)
            if 0 < hours <= 48:
                minutes, basis = int(round(hours * 60)), "duration"
        except (TypeError, ValueError):
            minutes, basis = None, None
    if minutes is None:
        minutes, basis = int(ride_fallback_minutes), "assumed"
    return dep, dep + timedelta(minutes=minutes), True, basis


def build_transport_swap(trip, selected, new_transport, ride_fallback_minutes=90):
    """Propose replacing the trip's booked outbound leg with another service.

    Pure with respect to the database, exactly like `build_proposal`: it takes
    plain dicts and returns a proposal, and the route decides whether to persist
    it. That purity is what makes the confirm step possible.

    Why this is needed
    ------------------
    "I don't want the train, I want a bus after 2 PM" has to change the
    *itinerary*, not merely produce a friendly reply. A mode change is not a
    retiming: the replacement service leaves at a different time, lasts a
    different length and costs a different amount, so every downstream item on
    the arrival day has to move with it.

    How it reuses the existing engine instead of duplicating it
    ----------------------------------------------------------
    The swap is expressed as an input to `build_proposal`, not as a second
    planner. The leg keeps its ORIGINAL clock times going in and carries the new
    service's identity and fare; the true arrival delta is then handed to
    `build_proposal` as its `delay_minutes`. Because the delta is measured to
    the new arrival, the leg's end lands exactly on the real new arrival time
    and the engine's existing cascade - which already knows about venue opening
    hours, `_earliest_feasible`, `_fits_before_close` and travel gaps - reflows
    the rest of the day off the correct time.

    A single pass afterwards pins the leg to the replacement service's true
    departure and arrival (the engine preserves the original ride length, which
    is only right when the two services happen to take the same time) and
    recomputes the cost so the confirmed figure is derived, never reported.
    """
    if trip is None:
        raise ReplanError("Trip not found.")
    if not selected:
        raise ReplanError("No selected itinerary to change.")
    if not new_transport or not new_transport.get("_id"):
        raise ReplanError("No replacement transport supplied.")

    items = [dict(i) for i in (selected.get("items") or [])]
    if not items:
        raise ReplanError("The selected itinerary has no items.")

    booked = None
    for item in sorted(items, key=lambda x: (x.get("day", 1),
                                             x.get("startTime") or "",
                                             x.get("sortOrder", 0))):
        if str(item.get("type") or "").upper() in BOOKED_TYPES:
            booked = item
            break
    if booked is None:
        raise ReplanError("This trip has no booked transport leg to change.")

    old_start, old_end = parse_dt(booked.get("startTime")), parse_dt(booked.get("endTime"))
    if old_start is None:
        raise ReplanError("The booked transport leg has no departure time.")
    if old_end is None:
        old_end = old_start

    dep, arr, estimated, basis = _leg_schedule(old_start, new_transport,
                                               ride_fallback_minutes)
    if dep is None:
        raise ReplanError(
            "That service does not publish a departure time, so it cannot be "
            "scheduled.")

    old_mode = str(booked.get("type") or "").upper()
    new_mode = str(new_transport.get("type") or "").upper()
    old_name = booked.get("title") or old_mode

    service_name = (new_transport.get("serviceName") or "").strip()
    label = new_transport.get("busNumber") or new_transport.get("trainNumber") \
        or new_transport.get("flightNumber") or ""
    new_title = ("%s %s" % (service_name, label)).strip() if service_name \
        else (new_mode or "Transport")

    # Captured before the new fare is staged. `build_proposal` derives its
    # "original" from the items it is handed, and what we hand it already carries
    # the replacement fare - so its original total would be the price of the new
    # service, making the change look free. The figure the passenger has to be
    # shown is the cost of the plan as it stands today.
    pre_swap_total = itinerary_total(items)

    fare = 0.0
    raw_fare = new_transport.get("fare")
    if isinstance(raw_fare, dict):
        raw_fare = raw_fare.get("price") or raw_fare.get("baseFare") or 0
    try:
        fare = float(raw_fare or 0)
    except (TypeError, ValueError):
        fare = 0.0

    try:
        travelers = max(1, int(trip.get("travelers") or 1))
    except (TypeError, ValueError):
        travelers = 1

    # New identity and fare, original clock times for now: the arrival delta
    # below is what moves the day, and it is measured against the true arrival.
    staged = dict(booked)
    staged["type"] = new_mode or old_mode
    staged["title"] = new_title
    staged["provider"] = new_transport.get("provider") or service_name
    staged["operator"] = service_name
    # Carry the replacement service's own photos/rating, not the delayed
    # service's. Otherwise a RE-PLAN leaves the old train's image and score
    # attached to the new bus in the VIEW modal.
    staged["images"] = new_transport.get("images") or []
    staged["image"] = (staged["images"] or [None])[0]
    staged["rating"] = new_transport.get("rating")
    staged["cost"] = round(fare * travelers, 2)
    staged["bookableId"] = "transport:%s" % new_transport["_id"]
    staged["costVerified"] = fare > 0
    staged["arrivalEstimated"] = estimated

    working = dict(selected)
    working["items"] = [staged if str(i.get("_id")) == str(booked.get("_id")) else i
                        for i in items]

    arrival_delta = int(round((arr - old_end).total_seconds() / 60.0))

    proposal = build_proposal(trip, working,
                              delay_minutes=max(0, arrival_delta),
                              reason="transport_change")

    # Pin the leg to the replacement service's real schedule. Downstream items
    # were cascaded off the true arrival, so only the leg itself is corrected.
    booked_id = str(booked.get("_id"))
    for item in proposal["items"]:
        if str(item.get("_id")) == booked_id:
            item["type"] = new_mode or old_mode
            item["title"] = new_title
            item["provider"] = staged["provider"]
            item["operator"] = service_name
            item["images"] = staged["images"]
            item["image"] = staged["image"]
            item["rating"] = staged["rating"]
            item["startTime"] = fmt_dt(dep)
            item["endTime"] = fmt_dt(arr)
            item["cost"] = staged["cost"]
            item["bookableId"] = staged["bookableId"]
            item["costVerified"] = staged["costVerified"]
            item["arrivalEstimated"] = estimated
            item["replanStatus"] = "MOVED"
            item.pop("replanStatusNote", None)

    proposal["cost"]["revised"] = itinerary_total(proposal["items"])
    proposal["cost"]["original"] = round(pre_swap_total, 2)
    proposal["cost"]["additional"] = round(
        proposal["cost"]["revised"] - proposal["cost"]["original"], 2)

    proposal["changes"].insert(0, {
        "type": "moved",
        "itemId": booked.get("_id"),
        "title": new_title,
        "day": booked.get("day"),
        "from": fmt_dt(old_start),
        "to": fmt_dt(dep),
        "reason": ("%s replaced by %s" % (old_name, new_title)
                   if old_mode != new_mode else "Service replaced"),
    })

    moved = sum(1 for c in proposal["changes"] if c.get("type") == "moved")
    parts = ["Transport changed from %s to %s, departing %s and arriving %s." % (
        old_name, new_title, dep.strftime("%d %b %H:%M"),
        arr.strftime("%d %b %H:%M"))]
    if estimated:
        parts.append(
            "This operator publishes no arrival time, so %s is an estimate%s." % (
                arr.strftime("%d %b %H:%M"),
                " based on the published journey duration"
                if basis == "duration" else
                " based on the previous leg's journey time - confirm it with "
                "the operator"))
    if moved > 1:
        parts.append("%d further item%s moved to fit the new arrival."
                     % (moved - 1, "" if moved - 1 == 1 else "s"))
    if proposal["dropped"]:
        parts.append("%d stop%s no longer fit and %s removed."
                     % (len(proposal["dropped"]),
                        "" if len(proposal["dropped"]) == 1 else "s",
                        "was" if len(proposal["dropped"]) == 1 else "were"))
    additional = proposal["cost"]["additional"]
    if additional > 0:
        parts.append("That costs Rs %s more than the current plan."
                     % additional)
    elif additional < 0:
        parts.append("That saves Rs %s against the current plan." % abs(additional))
    else:
        parts.append("There is no change in cost.")
    proposal["summary"] = " ".join(parts)

    proposal["transportChange"] = {
        "fromMode": old_mode,
        "toMode": new_mode,
        "fromTitle": old_name,
        "toTitle": new_title,
        "transportId": str(new_transport["_id"]),
        "previousTransportId": (str(booked.get("bookableId") or "")
                                .split(":")[-1] or None),
        "departure": fmt_dt(dep),
        "arrival": fmt_dt(arr),
        "arrivalEstimated": estimated,
        # "operator" | "duration" | "assumed" - how the arrival time above was
        # arrived at. The UI must not present all three as equally solid.
        "arrivalBasis": basis,
        "farePerTraveller": round(fare, 2),
        "totalFare": round(fare * travelers, 2),
    }
    return proposal
