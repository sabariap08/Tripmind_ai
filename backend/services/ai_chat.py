from datetime import datetime, timedelta
import re
from services.mongodb import get_collection
from services.route_mindmap import get_journey_flow
from services.transport_service import available_transports

REMOVE_KEYWORDS = ["remove", "delete", "drop", "take out"]
TRANSPORT_KEYWORDS = ["transport", "train", "bus", "flight", "cab", "auto", "alternate", "alternative", "another way"]

# Time slots the item editor understands (local time-of-day words).
SLOT_TIMES = {
    "early morning": (6, 0),
    "morning": (9, 0),
    "late morning": (10, 30),
    "noon": (12, 0),
    "afternoon": (13, 0),
    "late afternoon": (16, 0),
    "evening": (18, 0),
    "night": (20, 0),
}


def _selected_itinerary(trip):
    """Return the SELECTED itinerary of a trip (items referenced by name)."""
    for it in trip.get("itineraries", []):
        if it.get("status") == "SELECTED":
            return it
    return (trip.get("itineraries") or [None])[0]


def _day_date(trip, day):
    """The calendar date a given itinerary `day` (1-based) falls on. Falls back
    to the trip start date when the day is unparseable."""
    try:
        base = datetime.strptime((trip.get("startDate") or "")[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        base = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(days=int(day or 1) - 1)


def _day_label(trip, day):
    try:
        return _day_date(trip, day).strftime("%a %d %b")
    except Exception:
        return "day %d" % (day or 1)


def _match_item(items, term, day=None):
    """Find the first itinerary item matching a place/name term, optionally
    restricted to a day. 'food activity' style terms also match by type, and
    fuzzy token overlap rescues terms polluted by extra words ('fort st george
    visit make it' still finds 'Fort St. George')."""
    term = (term or "").strip().lower()
    if not term:
        return None
    if day is not None:
        items = [i for i in items if i.get("day") == day]
    term_tokens = [t for t in re.findall(r"[a-z]{2,}", term)
                   if t not in ("make", "it", "the", "be", "have", "on", "in",
                                "for", "with", "from", "to")]
    for item in items:
        title = (item.get("title") or "").lower()
        itype = (item.get("type") or "").lower()
        if term in title or term in itype:
            return item
        for kw in ("food activity", "lunch", "dinner", "breakfast", "restaurant", "meal"):
            if term == kw and itype in ("food", "restaurant"):
                return item
        for kw in ("food activity", "lunch", "dinner", "breakfast", "restaurant", "meal"):
            if kw in term and (kw in title or itype in ("food", "restaurant")):
                return item
        if term_tokens:
            title_tokens = set(re.findall(r"[a-z]{2,}", title))
            hits = [t for t in term_tokens if t in title_tokens]
            if len(hits) >= max(1, len(term_tokens) - 2) and len(hits) >= 2:
                return item
    if not term_tokens:
        return None
    # Weak single-token fallback (only when the strong pass missed everything).
    for item in items:
        title = (item.get("title") or "").lower()
        if any(len(t) >= 5 and t in title for t in term_tokens):
            return item
    return None


def _duration_minutes(item):
    try:
        st = datetime.fromisoformat((item.get("startTime") or "")[:19])
        et = datetime.fromisoformat((item.get("endTime") or "")[:19])
        diff = (et - st).total_seconds() / 60
        if 15 <= diff <= 360:
            return int(diff)
    except (TypeError, ValueError):
        pass
    return 0


def _set_day_time(item, trip, day, hh, mm, keep_duration=True):
    date = _day_date(trip, day)
    dur = _duration_minutes(item) if keep_duration else 0
    st = date.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    et = st + timedelta(minutes=dur) if dur else st + timedelta(minutes=90)
    item["day"] = int(day)
    item["startTime"] = st.isoformat()
    item["endTime"] = et.isoformat()
    item.pop("status", None)
    item["status"] = "PLANNED"
    return item


def _reflow(itinerary):
    """Renumber sortOrder by day, and recompute the itinerary's total cost."""
    items = sorted(itinerary.get("items") or [],
                   key=lambda x: (x.get("day", 1), x.get("startTime") or "", x.get("sortOrder", 0)))
    order = {}
    for item in items:
        d = item.get("day", 1)
        order[d] = order.get(d, 0) + 1
        item["sortOrder"] = order[d] - 1
    itinerary["items"] = items
    itinerary["totalCost"] = round(sum(float(i.get("cost") or 0) for i in items), 2)
    return itinerary


def _save_selected_items(trip_id, itinerary):
    get_collection("trips").update_one(
        {"_id": trip_id},
        {"$set": {
            "itineraries.$[it].items": itinerary.get("items"),
            "itineraries.$[it].totalCost": round(itinerary.get("totalCost") or
                                                 sum(float(i.get("cost") or 0) for i in itinerary.get("items") or []), 2),
            "updatedAt": datetime.utcnow().isoformat(),
        }},
        array_filters=[{"it.status": "SELECTED"}],
    )


def edit_itinerary_items(trip_id, command, user_id=None):
    """Apply a STRUCTURED item-level edit to the selected itinerary.

    Supported commands (each is re-validated before it runs):
      {"op": "move",   "item": "St. George Fort", "from_day": 1, "to_day": 2}
      {"op": "move",   "item": "Kapaleeshwarar Temple", "to_time": "morning"}
      {"op": "remove", "item": "food activity", "from_day": 1}
      {"op": "add",    "item": "Marina Beach", "to_day": 2, "to_time": "morning"}

    Nothing is ever executed blindly: every op is parsed, matched against the
    live itinerary, and only then persisted.
    """
    trips = get_collection("trips")
    trip = trips.find_one({"_id": trip_id})
    if not trip:
        return None, "Trip not found."
    if user_id and str(trip.get("userId")) != str(user_id):
        return None, "Trip not found."
    if trip.get("status") in ("BOOKED", "COMPLETED"):
        return None, "This trip is already booked. Edit before confirming and paying."

    itinerary = _selected_itinerary(trip)
    if not itinerary or not itinerary.get("items"):
        return None, "This trip has no itinerary to edit yet. Generate a plan first."

    op = str(command.get("op") or "").lower()
    term = str(command.get("item") or "")
    if op not in ("move", "remove", "add"):
        return None, "Edit op must be move, remove or add."

    if op == "remove":
        from_day = None
        fd = command.get("from_day")
        if fd is not None:
            try:
                from_day = int(fd)
            except (TypeError, ValueError):
                from_day = None
        target = None
        keep = []
        removed = []
        for item in itinerary.get("items") or []:
            title = (item.get("title") or "")
            itype = (item.get("type") or "").lower()
            hit_day = from_day is None or item.get("day") == from_day
            name_hit = term.lower() in title.lower() or term.lower() in itype
            for kw in ("food activity", "lunch", "dinner", "breakfast", "restaurant", "meal"):
                if term.lower() == kw and itype in ("food", "restaurant"):
                    name_hit = True
            if hit_day and name_hit:
                removed.append({"title": title, "day": item.get("day")})
            else:
                keep.append(item)
        if not removed and from_day is not None:
            # Demo-friendly fallback: retry the term across every day when the
            # named source day has no match (e.g. 'remove food from Day 1'
            # while food is scheduled on Day 2).
            from_day = None
            hit_day = True
            removed = []
            keep = []
            for item in itinerary.get("items") or []:
                title = (item.get("title") or "")
                itype = (item.get("type") or "").lower()
                name_hit = term.lower() in title.lower() or term.lower() in itype
                for kw in ("food activity", "lunch", "dinner", "breakfast", "restaurant", "meal"):
                    if term.lower() == kw and itype in ("food", "restaurant"):
                        name_hit = True
                if name_hit:
                    removed.append({"title": title, "day": item.get("day")})
                else:
                    keep.append(item)
        if not removed:
            hint = " on day %d" % from_day if from_day else ""
            return None, "No itinerary item named '%s'%s was found in the plan." % (term, hint)
        itinerary["items"] = keep
        _reflow(itinerary)
        _save_selected_items(trip_id, itinerary)
        return {
            "op": "remove",
            "message": "Removed %d item(s): %s." % (len(removed),
                          ", ".join("%s (day %s)" % (r["title"], r["day"]) for r in removed)),
            "removed": removed,
            "totalCost": round(itinerary["totalCost"], 2),
        }, None

    if op == "move":
        to_day = command.get("to_day")
        if to_day is not None:
            try:
                to_day = int(to_day)
            except (TypeError, ValueError):
                return None, "to_day must be a number."
        slot = str(command.get("to_time") or "").strip().lower()
        if to_day is None and not slot:
            return None, "A move needs a target day or time slot."

        from_day = None
        fd = command.get("from_day")
        if fd is not None:
            try:
                from_day = int(fd)
            except (TypeError, ValueError):
                from_day = None
        item = _match_item(itinerary.get("items") or [], term, day=from_day)
        matched_everywhere = False
        if not item:
            # Demo-friendly fallback: the traveller may name the source day
            # from an older narration ("Day 1") while the live plan schedules
            # it elsewhere. Search all days before giving up.
            item = _match_item(itinerary.get("items") or [], term)
            matched_everywhere = item is not None
        if not item:
            hint = " on day %d" % from_day if from_day else ""
            return None, "No itinerary item named '%s'%s was found in the plan." % (term, hint)

        orig_day = item.get("day")
        orig_time = (item.get("startTime") or "")[11:16] or "09:00"
        if slot:
            if slot not in SLOT_TIMES:
                return None, "Unknown time slot '%s' (try morning, afternoon or evening)." % slot
            hh, mm = SLOT_TIMES[slot]
            day = to_day if to_day is not None else orig_day
            _set_day_time(item, trip, day, hh, mm)
        else:
            hh, mm = (int(orig_time[:2]), int(orig_time[3:5]))
            _set_day_time(item, trip, to_day, hh, mm)
        _reflow(itinerary)
        _save_selected_items(trip_id, itinerary)
        return {
            "op": "move",
            "message": ("Moved \"%s\" from day %d (%s) to day %d (%s) at %s."
                        % (item.get("title"), orig_day, _day_label(trip, orig_day),
                           item.get("day"), _day_label(trip, item.get("day")),
                           (item.get("startTime") or "")[11:16])),
            "item": item.get("title"),
            "from_day": orig_day,
            "to_day": item.get("day"),
            "totalCost": round(itinerary["totalCost"], 2),
        }, None

    # add
    to_day = command.get("to_day")
    if to_day is None:
        return None, "An add needs a target day."
    try:
        to_day = int(to_day)
    except (TypeError, ValueError):
        return None, "to_day must be a number."
    slot = str(command.get("to_time") or "").strip().lower()
    if slot and slot not in SLOT_TIMES:
        return None, "Unknown time slot '%s' (try morning, afternoon or evening)." % slot
    hh, mm = SLOT_TIMES[slot] if slot else (10, 0)

    def _find_spot(term):
        """Catalogue lookup that keeps working when the traveller writes
        "marina beach activity" instead of exactly "Marina Beach": strip
        descriptor words and token-overlap the remainder against spot names.

        The term is escaped before it becomes a pattern. It used to be
        interpolated raw into ".*%s.*", so a user typing regex metacharacters
        got a pattern error (or a catastrophic backtrack) instead of a search,
        and a one-word term matched almost every record in the collection."""
        from services import geo_match
        cleaned = [(term or "").replace(w, " ").strip() for w in
                   ("the", "activity", "tour", "visit", "attraction",
                    "spot", "place", "sightseeing")]
        tried = []
        for try_term in (term,) + tuple(cleaned):
            try_term = (try_term or "").strip()
            if not try_term or try_term in tried:
                continue
            tried.append(try_term)
            # Escaped, unanchored substring match - substring is deliberate
            # here (the traveller may omit part of the name) but it must be a
            # literal pattern, never a user-supplied regex.
            pattern = re.escape(try_term)
            queries = [{"name": {"$regex": pattern, "$options": "i"}}]
            dest = trip.get("destination")
            if dest:
                queries.append(dict(geo_match.place_query(dest),
                                    name={"$regex": pattern, "$options": "i"}))
            for q in queries:
                spot = get_collection("tourist_spots").find_one(q)
                if spot:
                    return spot
        tokens = [t for t in re.findall(r"[a-z]{3,}", (term or "").lower())
                  if t not in ("the", "activity", "tour", "visit", "attraction", "spot", "place")]
        if tokens:
            best, best_score = None, 0
            for s in get_collection("tourist_spots").find(
                    {"city": {"$in": [trip.get("destination"), ""]}}):
                name = (s.get("name") or "").lower()
                score = sum(1 for t in tokens if t in name)
                if score > best_score:
                    best, best_score = s, score
            if best_score >= 1:
                return best
        return None

    spot = _find_spot(term)
    if not spot:
        return None, ("No tourist spot named '%s' found in the catalogue to add. "
                      "Try Marina Beach, Fort St. George, Kapaleeshwarar Temple or Mahabalipuram." % term)

    import uuid
    new_item = {
        "_id": str(uuid.uuid4()),
        "day": to_day,
        "title": spot.get("name"),
        "type": "ACTIVITY",
        "cost": round(float(spot.get("entryFee") or 0), 2),
        "bookableId": "spot:%s" % str(spot["_id"]),
        "provider": spot.get("ownerName") or "",
        "status": "PLANNED",
    }
    _set_day_time(new_item, trip, to_day, hh, mm)
    itinerary["items"].append(new_item)
    _reflow(itinerary)
    _save_selected_items(trip_id, itinerary)
    return {
        "op": "add",
        "message": ("Added \"%s\" to day %d (%s) at %s."
                    % (spot.get("name"), to_day, _day_label(trip, to_day),
                       (new_item.get("startTime") or "")[11:16])),
        "item": spot.get("name"),
        "to_day": to_day,
        "totalCost": round(itinerary["totalCost"], 2),
    }, None


def _flow_response(origin="Coimbatore", destination="Chennai"):
    """Mind-map output rule: return ONLY the connected travel journey flow."""
    flow = get_journey_flow(origin, destination)
    lines = [
        "TRAVEL JOURNEY FLOW",
        "",
        "START: %s" % flow["start"],
        "  |",
    ]
    for i, stage in enumerate(flow["stages"], start=1):
        if stage["type"] == "info":
            lines.append("%d. %s" % (i, stage["title"]))
        elif stage["type"] == "group":
            lines.append("%d. %s" % (i, stage["title"]))
            for o in stage["options"]:
                opt_names = [c["name"] for c in o.get("classes", [])] if o.get("classes") else [o["name"]]
                if opt_names:
                    lines.append("   %s -> %s" % (o["name"], " | ".join(opt_names)))
        elif stage["type"] == "branch":
            lines.append("%d. %s" % (i, stage["title"]))
            lines.append("   " + "  |  ".join(o["name"] for o in stage.get("options", [])))
        elif stage["type"] == "hotels":
            lines.append("%d. Hotels in %s" % (i, destination))
            lines.append("   " + "  |  ".join(c["name"] for c in stage.get("categories", [])))
        elif stage["type"] == "spots":
            lines.append("%d. Tourist spots in %s" % (i, destination))
            lines.append("   " + "  |  ".join(s["name"] for s in stage.get("spots", [])))
        elif stage["type"] == "return":
            lines.append("%d. %s" % (i, stage["title"]))
        else:
            lines.append("%d. %s" % (i, stage["title"]))
        lines.append("  |")
    lines.append("Your planned journey shows the same steps day by day on the trip page.")
    return "\n".join(lines)


def _transport_suggestion(trip):
    """Return a list of alternate transport options for the trip's origin/destination."""
    origin = trip.get("origin", "")
    destination = trip.get("destination", "")
    out = []
    for t in available_transports(origin, destination)[:6]:
        ttype = t.get("type", "")
        fare = t.get("fare")
        if isinstance(fare, dict):
            price = (fare.get("price") or fare.get("baseFare") or 0)
            # For cabs/autos the per-km rate is the key pricing dimension.
            if not price and fare.get("pricePerKm"):
                price = fare.get("pricePerKm")
        else:
            price = fare or 0
        name = t.get("serviceName") or ttype
        if ttype == "BUS":
            name = "%s %s" % (name, t.get("busNumber") or "")
        elif ttype == "TRAIN":
            name = "%s %s" % (name, t.get("trainNumber") or "")
        elif ttype == "FLIGHT":
            name = "%s %s" % (name, t.get("flightNumber") or "")
        out.append({"mode": ttype, "name": name.strip(), "cost": price})
    return out


# ------------------------------------------- changing the transport (replan)
# The bug this fixes: "I don't want the train, I want a bus after 2 PM" used to
# fall through to `_transport_suggestion`, which returns a READ-ONLY list of
# alternates. The assistant would then say "here are your options" and the
# itinerary stayed exactly as it was - because the only mutation this module
# could perform was `remove_place`. The user got a chat reply and an unchanged
# trip.
#
# Changing the mode is not a retiming: the replacement service leaves at a
# different time, lasts a different length and costs a different amount, so
# the whole arrival day has to move with it. The actual re-flow lives in
# `services.replanner.build_transport_swap`, which reuses that module's existing
# opening-hours and feasibility cascade. This file only does the two things a
# chatbot is good at: understanding the request, and presenting a diff the
# passenger has to confirm.
#
# Nothing is written until confirmation, and the cost figures the client echoes
# back are never trusted - the proposal is re-derived server-side on confirm.

TRANSPORT_CHANGE_KEYWORDS = [
    "instead of", "rather than", "change to", "switch to", "switch from",
    "change from", "don't want the", "dont want the", "do not want the",
    "no longer want", "not the train", "not the bus", "not the flight",
    "make it a", "change transport", "switch transport", "change the train",
    "change the bus", "change the flight", "switch the train", "switch the bus",
    "switch the flight", "switch the transport", "change the transport",
    "book a bus", "book a train",
    "book a flight", "take a bus", "take a train", "take a flight",
]

_MODE_WORDS = {
    "bus": "BUS", "buses": "BUS", "coach": "BUS",
    "train": "TRAIN", "trains": "TRAIN", "rail": "TRAIN",
    "flight": "FLIGHT", "flights": "FLIGHT", "plane": "FLIGHT",
    "cab": "CAB", "taxi": "CAB",
    "auto": "AUTO", "rickshaw": "AUTO",
}

_MODE_ALT = "|".join(sorted(_MODE_WORDS, key=len, reverse=True))

# The lookbehinds matter: without them "don't want the train" would match the
# positive pattern at "want the train" and the assistant would try to book the
# very service the traveller rejected.
# The positive verbs, kept as a separate list from the regex so the regexes stay
# readable and so the negation handling below is explicit rather than implied by
# a lookbehind.
_WANT_VERBS = r"want|book|take|prefer|switch to|switching to|change to|changing to|make it|give me"
_REJECT_VERBS = (r"don'?t want|do not want|no longer want|avoid|instead of|"
                 r"rather than|change from|switch from|drop|not")

# A negating phrase always wins over a positive one in the same sentence, so
# "I don't want the train. I want a bus." resolves to want=BUS, reject=TRAIN.
# `_wanted_mode`/`_rejected_mode` enforce that by discarding a positive match
# that sits inside a negation.
_WANT = re.compile(
    r"\b(?:" + _WANT_VERBS + r")\s+(?:a\s+|an\s+|the\s+)?"
    r"(" + _MODE_ALT + r")\b")
_REJECT = re.compile(
    r"\b(?:" + _REJECT_VERBS + r")\s+(?:a\s+|an\s+|the\s+)?"
    r"(" + _MODE_ALT + r")\b")

# "change the train to a flight" / "switch from the bus to a cab": the mode
# being moved away from sits in the middle, so it needs its own shape.
_SWITCH_FROM_TO = re.compile(
    r"\b(?:change|switch|swap|replace)\s+(?:the\s+|a\s+|an\s+|my\s+)?"
    r"(" + _MODE_ALT + r")\s+(?:in)?to\s+(?:a\s+|an\s+|the\s+)?("
    + _MODE_ALT + r")\b")
_CHANGE_VERB = re.compile(
    r"(?<!n't )\b(?:change|switch|swap|replace|book|take)\b", re.IGNORECASE)

_CLOCK_AMPM = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?\b")
_CLOCK_24H = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_TIME_QUALIFIER = re.compile(r"\b(after|before|from|at|around)\b")


def _negated_spans(message):
    """Character ranges covered by a negation phrase."""
    return [m.span() for m in _REJECT.finditer(message)]


def _wanted_mode(message):
    """The mode the traveller is asking FOR, or None.

    A positive match that falls inside a negation ("I don't want the train")
    is discarded, so the explicit later request in "I don't want the train, I
    want a bus" is what wins.
    """
    low = message.lower()
    negated = _negated_spans(low)
    m = _SWITCH_FROM_TO.search(low)
    if m:
        return _MODE_WORDS[m.group(2)]
    for m in _WANT.finditer(low):
        if not any(start <= m.start() < stop for start, stop in negated):
            return _MODE_WORDS[m.group(1)]
    return None


def _rejected_mode(message):
    """The mode the traveller said they do NOT want, or None."""
    low = message.lower()
    m = _SWITCH_FROM_TO.search(low)
    if m:
        return _MODE_WORDS[m.group(1)]
    m = _REJECT.search(low)
    return _MODE_WORDS[m.group(1)] if m else None


def _time_preference(message):
    """(minutes since midnight, qualifier) for "after 2 PM" style requests."""
    low = message.lower()
    qualifier = ""
    m = _TIME_QUALIFIER.search(low)
    if m:
        qualifier = m.group(1)
    t = _CLOCK_AMPM.search(low)
    if t:
        hour = int(t.group(1)) % 12
        minute = int(t.group(2) or 0)
        if t.group(3) == "p":
            hour += 12
        return hour * 60 + minute, qualifier
    t = _CLOCK_24H.search(low)
    if t:
        hour, minute = int(t.group(1)), int(t.group(2))
        if hour <= 23 and minute <= 59:
            return hour * 60 + minute, qualifier
    return None


def _wants_transport_change(message):
    """True when the message asks to CHANGE the transport, not browse options.

    A false positive is harmless: the result is a proposal the passenger has to
    confirm, never a silent change.
    """
    low = message.lower()
    if not any(w in low for w in TRANSPORT_CHANGE_KEYWORDS):
        return False
    return bool(_WANT.search(low) or _REJECT.search(low) or _CHANGE_VERB.search(low))


def _fare_of(transport):
    fare = transport.get("fare")
    if isinstance(fare, dict):
        fare = fare.get("price") or fare.get("baseFare") or 0
    try:
        return float(fare or 0)
    except (TypeError, ValueError):
        return 0.0


def _departure_minutes(transport):
    value = transport.get("boardingTime") or transport.get("departureTime") or ""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(value))
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _transport_candidates(trip, want_mode, reject_mode, not_before=None):
    """Approved transports on this corridor that satisfy the request."""
    out = []
    for t in available_transports(trip.get("origin") or "",
                                 trip.get("destination") or "") or []:
        mode = str(t.get("type") or "").upper()
        if want_mode and mode != want_mode:
            continue
        if reject_mode and mode == reject_mode:
            continue
        if str(t.get("status") or "APPROVED").upper() not in ("APPROVED", ""):
            continue
        if not t.get("_id"):
            continue
        if not_before is not None:
            dep = _departure_minutes(t)
            if dep is None or dep < not_before:
                continue
        out.append(t)
    # Cheapest first: the passenger set a budget, so among equally valid
    # services the affordable one is the better default to propose.
    out.sort(key=lambda t: (_fare_of(t) or 0,
                            _departure_minutes(t) if _departure_minutes(t) is not None else 10 ** 6))
    return out


def _propose_transport_change(trip, message):
    """Build a confirmable transport-change proposal. Writes nothing.

    Returns ``(proposal, transport, err)``.
    """
    selected = _selected_itinerary(trip)
    if not selected:
        return None, None, ("This trip has no selected plan yet, so there is "
                            "nothing to change. Generate a plan first.")

    want, reject = _wanted_mode(message), _rejected_mode(message)
    if want and reject and want == reject:
        want, reject = None, None
    if not want and not reject:
        return None, None, ("Tell me which transport you would like instead - "
                            "bus, train or flight - and I will check what is "
                            "actually available and what it costs.")

    preference = _time_preference(message)
    not_before = None
    if preference and preference[1] in ("after", "from", "at", "around"):
        not_before = preference[0]

    candidates = _transport_candidates(trip, want, reject, not_before)
    if not candidates and not_before is not None:
        # Never silently drop the time constraint and offer something the
        # traveller did not ask for.
        return None, None, (
            "There is no %s%s departing after %s on this route. Tell me a "
            "different time, or I can show you every %s that runs."
            % (reject and reject.lower() or "approved service",
               want and " " + want.lower() or "",
               "%02d:%02d" % divmod(not_before, 60),
               want and want.lower() or "option"))

    if not candidates:
        return None, None, ("No approved %s is currently available for %s to %s."
                            % ((want or "transport").lower(),
                               trip.get("origin") or "your origin",
                               trip.get("destination") or "your destination"))

    # Never offer the service already on the plan as its own replacement.
    current_ids = set()
    for it in (selected.get("items") or []):
        bid = str(it.get("bookableId") or "")
        if bid.startswith("transport:"):
            current_ids.add(bid.split(":", 1)[1])
    candidates = [c for c in candidates
                  if str(c.get("_id")) not in current_ids]
    if not candidates:
        return None, None, (
            "There is no other approved %s service on this route, so there is "
            "nothing to switch to." % (want or "transport").lower())

    chosen = candidates[0]
    try:
        from services import replanner
        proposal = replanner.build_transport_swap(trip, selected, chosen)
    except replanner.ReplanError as exc:
        return None, None, str(exc)
    except Exception as exc:  # a proposal must never 500 into the chat
        return None, None, ("I could not build that change safely (%s). Nothing "
                            "has been modified." % exc)
    return proposal, chosen, None


def _extract_place_name(message):
    """Extract a destination/place name to remove from the plan."""
    msg_lower = message.lower()
    for kw in REMOVE_KEYWORDS:
        msg_lower = msg_lower.replace(kw, " ")
    words = [w for w in msg_lower.split() if w.strip()]
    if not words:
        return None
    title = " ".join(words).strip(" .,;:!?") or None
    return title


def _plan_removal(trip_id, place):
    """Work out what removing `place` would do, WITHOUT writing anything.

    Pure apart from the one read: the trip document is fetched and the same
    item matching / day renumbering / cost arithmetic that _remove_place_from_trip
    performs is carried out in memory, so the preview and the committed result
    cannot disagree. `_commit_removal` re-runs the identical computation rather
    than trusting a number the client sent back, so a tampered proposal cannot
    change what is actually removed.
    """
    trips = get_collection("trips")
    trip = trips.find_one({"_id": trip_id})
    if not trip:
        return None, "Trip not found."
    itinerary = _selected_itinerary(trip)
    if not itinerary:
        return None, "This trip has no itinerary to modify yet."
    items = itinerary.get("items", [])

    keep, removed = [], []
    for item in items:
        title = (item.get("title") or "")
        if place and place.lower() in title.lower():
            removed.append(title)
        else:
            keep.append(item)
    if not removed:
        return None, "No itinerary item named '%s' was found." % place

    new_items = _renumber(keep)
    return {
        "place": place,
        "removed": removed,
        "removedCount": len(removed),
        "remainingItems": len(new_items),
        "currentTotalCost": sum(i.get("cost", 0) for i in items),
        "newTotalCost": sum(i.get("cost", 0) for i in new_items),
    }, None


def _renumber(keep):
    """Rebuild the item list with sortOrder made dense and days ascending."""
    new_items = []
    for day in sorted({i.get("day") for i in keep}):
        day_items = [i for i in keep if i.get("day") == day]
        for idx, i in enumerate(day_items):
            i["sortOrder"] = idx
            new_items.append(i)
    return new_items


def _remove_place_from_trip(trip_id, place):
    """Remove all itinerary items whose title contains the given place name.

    This writes. Callers must have obtained the user's confirmation first - see
    handle_ai_chat, which now proposes and only commits on an explicit confirm.
    """
    preview, err = _plan_removal(trip_id, place)
    if err:
        return None, err

    trips = get_collection("trips")
    trip = trips.find_one({"_id": trip_id})
    itinerary = _selected_itinerary(trip)
    new_items = _renumber([
        i for i in itinerary.get("items", [])
        if not (place and place.lower() in (i.get("title") or "").lower())
    ])

    trips.update_one(
        {"_id": trip_id},
        {"$set": {
            "itineraries.$[it].items": new_items,
            "itineraries.$[it].totalCost": preview["newTotalCost"],
            "updatedAt": datetime.utcnow().isoformat(),
        }},
        array_filters=[{"it.status": "SELECTED"}],
    )
    return {
        "removed": preview["removed"],
        "remainingItems": preview["remainingItems"],
        "newTotalCost": preview["newTotalCost"],
    }, None


def _apply_transport_change(trip_id, transport_id):
    """Commit a confirmed transport change. Writes.

    The proposal is re-derived here from the database rather than trusting the
    `pendingAction` payload the client echoed back, so a tampered or stale
    payload cannot install an arbitrary transport or a falsified cost.

    A snapshot of the previous itinerary is pushed onto `trip.itineraryHistory`
    before the write, so a wrong replan can be inspected and rolled back rather
    than being lost. That is the trip versioning the replan flow needs: v1
    original, v2 train->bus, v3 later delay fix.
    """
    trips = get_collection("trips")
    trip = trips.find_one({"_id": trip_id})
    if not trip:
        return None, "That trip no longer exists."
    selected = _selected_itinerary(trip)
    if not selected:
        return None, "This trip has no selected plan to change."

    transport = get_collection("transports").find_one(
        {"_id": str(transport_id or ""), "status": "APPROVED"})
    if not transport:
        return None, "That transport is no longer available, so nothing was changed."

    from services import replanner
    try:
        proposal = replanner.build_transport_swap(trip, selected, transport)
    except replanner.ReplanError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, ("I could not apply that change safely (%s). Nothing was "
                      "modified." % exc)

    changed = proposal.get("transportChange") or {}
    version = int(selected.get("version") or 1)
    new_total = proposal["cost"]["revised"]
    now = datetime.utcnow().isoformat()

    snapshot = {
        "version": version,
        "savedAt": now,
        "reason": "transport_change",
        "summary": "Previous itinerary, before switching to %s."
                   % changed.get("toTitle"),
        "items": selected.get("items") or [],
        "totalCost": selected.get("totalCost"),
    }

    # The trip's headline estimate must track the itinerary, or the budget view
    # keeps reporting the pre-change total.
    budget_total = float(trip.get("budget") or 0) * int(trip.get("travelers") or 1)
    set_fields = {
        "itineraries.$[it].items": proposal["items"],
        "itineraries.$[it].totalCost": new_total,
        "itineraries.$[it].version": version + 1,
        "totalEstimatedCost": new_total,
        "updatedAt": now,
        "transportMode": changed.get("toMode"),
    }
    if budget_total > 0:
        set_fields["budgetUtilization"] = round(min(1.0, new_total / budget_total), 4)

    trips.update_one(
        {"_id": trip_id},
        {"$set": set_fields,
         "$push": {"itineraryHistory": snapshot}},
        array_filters=[{"it.status": "SELECTED"}],
    )

    if trip.get("status") in ("BOOKED", "COMPLETED"):
        _flag_booking_change_needed(trip, changed)

    return {"proposal": proposal, "changed": changed,
            "newTotalCost": new_total, "version": version + 1}, None


def _flag_booking_change_needed(trip, changed):
    """Record that the itinerary moved but the real booking has not.

    A confirmed external booking is never silently rewritten: TripMind has no
    change API for a partner's ticket, so the trip is marked `change_pending`
    and the passenger is told to confirm with the provider. The alternative -
    reporting a transport as "changed" when only the plan was - is exactly the
    kind of false success this system must not produce.
    """
    trips = get_collection("trips")
    trips.update_one(
        {"_id": trip["_id"]},
        {"$set": {
            "status": "change_pending",
            "pendingChange": {
                "type": "transport_change",
                "toTitle": changed.get("toTitle"),
                "toMode": changed.get("toMode"),
                "raisedAt": datetime.utcnow().isoformat(),
                "note": ("Itinerary updated. The confirmed booking still needs "
                         "to be changed with the provider - TripMind has not "
                         "altered the ticket."),
            },
        }},
    )


def _chat_error(message, suggestions=None):
    """A chat turn that could not be satisfied.

    Always says requiresConfirmation=False: there is nothing outstanding to
    approve, and a client that shows a confirm button on an error would let the
    user "confirm" a change that was never described.
    """
    return {
        "response": message,
        "suggestions": suggestions or ["Show me the updated plan", "Help me plan"],
        "pendingAction": None,
        "requiresConfirmation": False,
        "timestamp": datetime.utcnow().isoformat(),
    }


def handle_ai_chat(trip_id, message, confirm=False, pending_action=None):
    """Answer a chat message. Mutations PROPOSE first and only write on confirm.

    `pending_action` is the dict the previous turn handed back to the client.
    When it comes back with confirm=True we re-derive the effect server-side
    (never trusting the cost figures in the echoed payload) and apply it. This
    is the same two-phase shape as POST /api/trips/<id>/replan, and it is what
    the trip page has always claimed in its own copy: "The assistant proposes
    changes - nothing is applied until you confirm them."
    """
    msg_lower = message.lower()
    trip = None
    if trip_id:
        trip = get_collection("trips").find_one({"_id": trip_id})

    # ---- phase 2: an explicitly confirmed, previously proposed action --------
    if confirm and pending_action:
        action = pending_action.get("action")
        if action == "remove_place":
            place = pending_action.get("place")
            if not place:
                return _chat_error("That confirmation did not say what to remove.")
            result, err = _remove_place_from_trip(trip_id, place)
            if err:
                return _chat_error(err)
            return {
                "response": "Removed from the plan: %s. The itinerary now has %d items. "
                            "Updated total cost is Rs %s." % (
                                ", ".join(result["removed"]), result["remainingItems"],
                                result["newTotalCost"]),
                "suggestions": ["Show me the updated plan", "Remove hotel", "Suggest transport"],
                "applied": {"action": "remove_place", "removed": result["removed"],
                            "remainingItems": result["remainingItems"],
                            "newTotalCost": result["newTotalCost"]},
                "pendingAction": None,
                "requiresConfirmation": False,
                "timestamp": datetime.utcnow().isoformat(),
            }

        if action == "switch_transport":
            transport_id = pending_action.get("transportId")
            if not transport_id:
                return _chat_error("That confirmation did not say which transport "
                                   "to switch to.")
            result, err = _apply_transport_change(trip_id, transport_id)
            if err:
                return _chat_error(err)
            proposal, changed = result["proposal"], result["changed"]
            extra = proposal["cost"]["additional"]
            cost_line = ("That adds Rs %s to the trip."
                         % extra if extra > 0 else
                         "That saves Rs %s." % abs(extra) if extra < 0 else
                         "There is no change in cost.")
            dropped = proposal.get("dropped") or []
            dropped_line = (" %d stop(s) no longer fit and were removed."
                            % len(dropped)) if dropped else ""
            booking_note = ""
            if trip and trip.get("status") in ("BOOKED", "COMPLETED"):
                booking_note = (" Your itinerary is updated, but the confirmed "
                                "booking still has to be changed with the "
                                "provider - TripMind has not touched the ticket.")
            return {
                "response": "%s %s%s Your itinerary is now on version %d and the "
                            "estimated total is Rs %s." % (
                                proposal["summary"], cost_line, dropped_line,
                                result["version"], result["newTotalCost"])
                           + booking_note,
                "suggestions": ["Show me the updated plan", "View cost breakdown",
                                "What time does everything start now?"],
                "applied": {
                    "action": "switch_transport",
                    "version": result["version"],
                    "newTotalCost": result["newTotalCost"],
                    "transportChange": changed,
                    "moved": sum(1 for c in proposal["changes"]
                                 if c.get("type") == "moved"),
                    "dropped": dropped,
                },
                "pendingAction": None,
                "requiresConfirmation": False,
                "timestamp": datetime.utcnow().isoformat(),
            }

        return _chat_error("That confirmation did not name a change TripMind can apply.")

    flow_keywords = [
        "travel flow", "transport flow", "route map", "journey map",
        "mind map", "travel route", "journey flow", "how to reach",
        "show flow", "journey", "roadmap", "route to", "route from",
    ]
    if any(kw in msg_lower for kw in flow_keywords):
        origin = (trip or {}).get("origin") or ""
        destination = (trip or {}).get("destination") or ""
        if not origin or not destination:
            # Never answer with a made-up route: ask for the real endpoints.
            return {
                "response": "Tell me where you are travelling from and to, and I will lay out "
                            "the connected journey step by step — transport, where you arrive, "
                            "local travel, a place to stay and the spots along the way.",
                "suggestions": [
                    "Plan a new trip",
                    "Show me transport options",
                    "Which hotels are available?",
                ],
                "timestamp": datetime.utcnow().isoformat(),
            }
        return {
            "response": _flow_response(origin, destination),
            "suggestions": [
                "Show me transport options",
                "Which hotels are available?",
                "List the tourist spots",
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Plan modification: propose removing a place. Nothing is written here.
    remove_match = any(kw in msg_lower for kw in REMOVE_KEYWORDS)
    if remove_match and trip:
        place = _extract_place_name(message)
        preview, err = _plan_removal(trip_id, place)
        if err:
            return _chat_error(
                err,
                suggestions=["Remove another place", "Show me the updated plan",
                             "Add a place back"],
            )
        saving = preview["currentTotalCost"] - preview["newTotalCost"]
        return {
            "response": (
                "I can remove %s from your plan. That would take %d item%s out, "
                "leaving %d, and change the estimated total from Rs %s to Rs %s"
                % (", ".join(preview["removed"]), preview["removedCount"],
                   "" if preview["removedCount"] == 1 else "s",
                   preview["remainingItems"], preview["currentTotalCost"],
                   preview["newTotalCost"])
                + (" (Rs %s less)." % saving if saving else ".")
                + " Nothing has changed yet - confirm and I will do it."
            ),
            "suggestions": ["Yes, remove it", "Keep it", "Show me the updated plan"],
            # The client echoes this back as pendingAction with confirm=true.
            "pendingAction": {"action": "remove_place", "place": preview["place"]},
            "requiresConfirmation": True,
            "preview": {
                "removed": preview["removed"],
                "remainingItems": preview["remainingItems"],
                "currentTotalCost": preview["currentTotalCost"],
                "newTotalCost": preview["newTotalCost"],
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Transport CHANGE request. This must be tested BEFORE the read-only
    # transport listing below, otherwise "I want a bus after 2 PM" is answered
    # with a list of options and the itinerary is never touched - the exact
    # behaviour this branch exists to fix.
    if trip and _wants_transport_change(message):
        proposal, chosen, err = _propose_transport_change(trip, message)
        if err:
            return _chat_error(
                err,
                suggestions=["Show me transport options", "Keep the current plan"],
            )
        changed = proposal["transportChange"]
        cost = proposal["cost"]
        additional = cost["additional"]
        moved = sum(1 for c in proposal["changes"] if c.get("type") == "moved")
        dropped = proposal.get("dropped") or []
        warnings = proposal.get("warnings") or []

        lines = [proposal["summary"]]
        lines.append("")
        lines.append("Proposed changes:")
        lines.append("- Transport: %s -> %s" % (changed["fromMode"], changed["toMode"]))
        lines.append("- Departure: %s" % (changed["departure"] or "unscheduled"))
        lines.append("- Arrival: %s%s" % (changed["arrival"] or "unscheduled",
                                          " (estimated - the operator does not "
                                          "publish an arrival)" if changed.get("arrivalEstimated") else ""))
        if moved > 1:
            lines.append("- %d further item(s) moved to fit the new arrival." % (moved - 1))
        for d in dropped:
            lines.append("- Removed: %s (%s)" % (d.get("title"),
                                                 d.get("reason") or "no longer fits"))
        for w in warnings:
            lines.append("- Note: %s" % w)
        lines.append("- Estimated total: Rs %s (was Rs %s, change %s%s)" % (
            cost["revised"], cost["original"],
            ("+" if additional > 0 else "") + str(additional) if additional else "0",
            "" if cost.get("allCostsVerified", True) else
            " - some prices are estimates"))
        if trip.get("status") in ("BOOKED", "COMPLETED"):
            lines.append("")
            lines.append("You already have a confirmed booking for this trip. "
                         "I can update your itinerary, but the ticket itself "
                         "must be changed with the provider - I will not mark it "
                         "as changed unless it really is.")
        lines.append("")
        lines.append("Nothing has changed yet. Confirm and I will apply it.")

        return {
            "response": "\n".join(lines),
            "suggestions": ["Confirm the change", "Keep my current plan",
                            "Show me the alternatives"],
            "pendingAction": {"action": "switch_transport",
                              "transportId": changed["transportId"]},
            "requiresConfirmation": True,
            "preview": {
                "changes": proposal["changes"],
                "cost": cost,
                "dropped": dropped,
                "warnings": warnings,
                "transportChange": changed,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Alternate transport suggestion (validated against the real transport DB).
    # Read-only: this only lists options and never modifies the trip.
    trip_transport = bool(trip) and any(w in msg_lower for w in ["alternate", "alternative", "another "])
    if (any(w in msg_lower for w in TRANSPORT_KEYWORDS) or trip_transport) and trip:
        opts = _transport_suggestion(trip)
        if opts:
            lines = ["Alternate transport options for %s -> %s:" % (trip.get("origin"), trip.get("destination"))]
            for o in opts:
                lines.append("- %s (%s): Rs %s" % (o["name"], o["mode"], o["cost"]))
            return {
                "response": "\n".join(lines),
                "suggestions": ["Book the cheapest", "Show more options", "Remove a place"],
                "timestamp": datetime.utcnow().isoformat(),
            }
        return {
            "response": "No alternate approved transport is currently available for %s -> %s."
                        % (trip.get("origin"), trip.get("destination")),
            "suggestions": ["Show transport options", "Help me plan"],
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Generic dialectic responses (budget/food/delay/comfort) remain helpful.
    if any(w in msg_lower for w in ["reduce", "cheaper", "save", "budget"]):
        response = "I can help you reduce costs! Consider switching to budget-friendly flights and hotels. Would you like me to generate a budget-optimized plan?"
        suggestions = ["Generate budget plan", "Show cheaper hotels", "Reduce activity costs"]
    elif any(w in msg_lower for w in ["hotel", "stay", "accommodation"]):
        response = "Looking at hotel options for your trip. Your current selection is a great balance of comfort and value. Want to explore alternatives?"
        suggestions = ["Upgrade hotel", "Downgrade to budget", "Show hotel details"]
    elif any(w in msg_lower for w in ["vegetarian", "food", "restaurant", "diet"]):
        response = "I'll note your vegetarian preference! All restaurant recommendations will be filtered for vegetarian options."
        suggestions = ["Show veg restaurants", "Update food preference", "Add dietary restrictions"]
    elif any(w in msg_lower for w in ["delay", "what if", "reschedule"]):
        response = "If there's a flight delay, I can automatically replan your itinerary. Use the 'Simulate Delay' feature on your trip page to see how it works."
        suggestions = ["Simulate 3hr delay", "Simulate 5hr delay", "View replan options"]
    elif any(w in msg_lower for w in ["comfort", "upgrade", "premium"]):
        response = "Want to upgrade to a more comfortable experience? I can suggest premium flights, 5-star hotels, and exclusive activities."
        suggestions = ["Upgrade to premium", "Show premium options", "Compare plans"]
    elif any(w in msg_lower for w in ["budget", "cost", "spending", "price"]):
        if trip:
            est = trip.get("totalEstimatedCost", 0)
            budget = trip.get("budget", 0)
            response = "Your trip budget is Rs %s and estimated cost is Rs %s. %s" % (
                budget, est,
                "You have Rs %s remaining." % int(budget - est) if budget > est else "You are slightly over budget.")
        else:
            response = "Please select a trip first to see budget details."
        suggestions = ["View cost breakdown", "Optimize costs", "Switch to budget plan"]
    else:
        response = "I'm your AI travel assistant! I can help with trip planning, cost optimization, delay replanning, and food preferences. What would you like to know?"
        suggestions = ["Plan a trip", "Check budget", "Simulate delay", "Food preferences"]

    return {
        "response": response,
        "suggestions": suggestions,
        "timestamp": datetime.utcnow().isoformat(),
    }