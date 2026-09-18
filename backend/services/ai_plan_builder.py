"""AI-only travel plan generation (Requirements 25-27, AI-generated plans).

THIS module is the ONLY plan generator in the app. Deterministic /
code-rule itinerary construction has been removed: every itinerary is composed
by the AI model. The AI receives a compact but complete catalogue brief built
exclusively from registered database rows (transports, spots, tours, guides,
hotels, food items), with each resource identified by its real id and real
price. The AI returns selections (which transport, which spots/tours in which
order, which guide, which hotel + room type, which food items). The backend:

  - validates that every referenced id exists in the catalogue brief,
  - materialises the daily itinerary from the real DB rows,
  - recomputes every price from catalogue data (AI never supplies numbers),
  - refuses to fall back to any rule-based plan when the AI is unavailable.

So plans are generated ONLY by AI, but the AI can never invent inventory or
prices — the database remains the single source of truth.
"""
import json

from services.ai_service import call_ai, is_ai_available
from services.trip_optimizer import (STYLE_WEIGHTS, _build_daily, _cost,
                                     _fare, _scores, item_after,
                                     learned_duration_or_default,
                                     parse_datetime)
from datetime import datetime, timedelta


class AIPlanError(Exception):
    """Raised when the AI backend cannot produce a valid plan."""


def _cost_f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _money(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _corridor_label(t):
    if t.get("type") == "BUS":
        return "%s → %s" % (t.get("boardingPoint"), t.get("droppingPoint"))
    if t.get("type") == "TRAIN":
        return "%s → %s" % (t.get("boardingStation"), t.get("destinationStation"))
    if t.get("type") == "FLIGHT":
        return "%s → %s" % (t.get("departureAirport"), t.get("arrivalAirport"))
    return t.get("serviceArea", "")


def _vehicle_label(t):
    return (t.get("busNumber") or t.get("trainNumber") or t.get("flightNumber")
            or t.get("vehicleNumber") or t.get("serviceName", ""))


# ---------------------------------------------------------------------------
# Catalogue brief (ground-truth inventory handed to the AI)
# ---------------------------------------------------------------------------

def _catalogue_brief(db_data):
    """Compact, lossless list of registered inventory with real ids/prices."""
    brief = {"transports": [], "spots": [], "tours": [], "guides": [],
             "hotels": [], "foods": []}

    for t in (db_data.get("transports") or []):
        if t.get("type") not in ("TRAIN", "BUS", "FLIGHT"):
            continue  # inter-city main legs only are selectable
        brief["transports"].append({
            "id": str(t.get("_id")),
            "type": t.get("type"),
            "service": t.get("serviceName", ""),
            "vehicle": _vehicle_label(t),
            "route": _corridor_label(t),
            "depart": t.get("boardingTime") or t.get("departureTime"),
            "arrive": t.get("droppingTime") or t.get("arrivalTime"),
            "departDay": t.get("boardingDay"),
            "arriveDay": t.get("droppingDay"),
            "price": _money(_fare(t)),
        })

    for s in (db_data.get("spots") or []):
        loc = s.get("location") or {}
        brief["spots"].append({
            "id": str(s.get("_id")),
            "name": s.get("name"),
            "city": s.get("city"),
            "location": loc.get("name") or s.get("city"),
            "entryFee": _money(s.get("entryFee")),
            "openingTime": s.get("openingTime"),
            "closingTime": s.get("closingTime"),
            "popularity": s.get("popularity"),
            "visitingTravelers": s.get("visitingTravelers"),
        })

    tours = db_data.get("tours") or []
    spot_ids = {str(s.get("_id")) for s in (db_data.get("spots") or [])}
    for t in tours:
        sid = str(t.get("spotId") or "")
        if sid and sid not in spot_ids:
            continue
        brief["tours"].append({
            "id": str(t.get("_id")),
            "spotId": sid,
            "name": t.get("name"),
            "cost": _money(t.get("cost")),
            "durationHours": _money(t.get("duration")),
            "guideRequired": bool(t.get("guideRequired")),
            "maxParticipants": t.get("maxParticipants"),
        })

    for g in (db_data.get("guides") or []):
        pricing = g.get("pricing") or {}
        brief["guides"].append({
            "id": str(g.get("userId")),
            "name": g.get("name"),
            "city": g.get("city"),
            "specialty": (g.get("profile") or {}).get("specialty", ""),
            "pricePerHour": _money(pricing.get("pricePerHour")),
            "pricePerDay": _money(pricing.get("pricePerDay")),
        })

    for h in (db_data.get("hotels") or []):
        types = []
        for rt in (h.get("roomTypes") or []):
            avail = _money(rt.get("availableRooms"))
            if avail <= 0:
                continue
            types.append({
                "id": rt.get("id"),
                "name": rt.get("name"),
                "pricePerNight": _money(rt.get("pricePerNight")),
                "availableRooms": int(avail),
            })
        if not types:
            continue
        brief["hotels"].append({
            "id": h.get("id"),
            "name": h.get("name"),
            "city": h.get("city"),
            "stars": _money(h.get("starRating")) or 3,
            "roomTypes": types,
        })

    for f in (db_data.get("foods") or []):
        brief["foods"].append({
            "id": f.get("foodId") or f.get("bookableId"),
            "name": f.get("foodName") or f.get("name"),
            "pricePerPerson": _money(f.get("pricePerPerson")),
            "restaurant": f.get("restaurantName"),
        })

    return brief


# ---------------------------------------------------------------------------
# Prompt + parsing
# ---------------------------------------------------------------------------

def _build_prompt(parsed, brief):
    budget_line = ("an unlimited budget (premium eligible)"
                   if parsed.get("budgetUnlimited")
                   else "a budget of ₹%d per person" % parsed.get("budget", 0))
    return (
        "Design the trip itinerary entirely from the available inventory below. "
        "Exactly 3 different plans must be returned — one for each style: "
        "BUDGET (best value/lowest cost), BALANCED (mix of cost and comfort), "
        "PREMIUM (best comfort/experience regardless of price).\n\n"
        "Trip: %s -> %s | %d day(s), %d traveller(s) | %s.\n"
        "Starting point: %s.\n"
        "Traveller preferences (IMPORTANT — follow them):\n\"%s\"\n\n"
        % (parsed.get("origin", ""), parsed.get("destination", ""),
           parsed.get("durationDays", 1), parsed.get("travelers", 1),
           budget_line, parsed.get("startLocation") or parsed.get("origin", ""),
           parsed.get("preferences", ""))
        + "Available inventory (only these ids are valid; use ONLY them):\n"
        + json.dumps(brief, indent=2, default=str)
        + ("\n\nReply with ONLY a JSON object matching this schema (no markdown):\n"
           '{"plans": [{"style": "BUDGET", '
           '"transportId": "<id or null>", '
           '"hotel": {"hotelId": "<id or null>", "roomTypeId": "<id or null>"} | null, '
           '"guideId": "<id or null>", '
           '"activityOrder": [{"spotId": "<id>", "tourId": "<id or null>"}, ...], '
           '"foodIds": ["<id>", ...], '
           '"reasoning": ["<1-2 sentence why this suits the traveller>"]}]}'
           "\nRules: pick ids exactly as listed; never invent ids, prices or names. "
           "Use at most 3 spots per plan unless the trip is longer. Assign activities "
           "across the trip days in a sensible order (arrival-day activities in the "
           "afternoon, departures on the last day). Choose at most 2 food items."))


_SYSTEM = (
    "You are TripMind's AI itinerary generator. You design complete travel plans "
    "for Coimbatore <-> Chennai trips using ONLY the inventory and ids provided. "
    "Rules: 1) never invent resources, ids, prices, timings or names; 2) every id "
    "you return must appear in the inventory; 3) return exactly one JSON object, "
    "no markdown, no commentary; 4) choose the transport that best fits the "
    "traveller's preferences and the plan style (BUDGET prefers sleeper buses "
    "and sleeper trains; PREMIUM prefers Air-conditioned flights/trains); "
    "5) always include a sensible hotel (or none only if the trip is under 2 "
    "days). Prefer tours that match the stated preferences.")

def _clean_json(raw):
    clean = (raw or "").strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.lower().startswith("json"):
            clean = clean[4:]
        clean = clean.strip()
    start, end = clean.find("{"), clean.rfind("}")
    if start == -1 or end == -1:
        return None
    return clean[start:end + 1]


def _parse_response(raw):
    clean = _clean_json(raw)
    if not clean:
        raise AIPlanError("AI returned non-JSON output.")
    try:
        data = json.loads(clean)
    except (ValueError, TypeError) as e:
        raise AIPlanError("AI returned malformed JSON (%s)." % e)
    if not isinstance(data, dict):
        raise AIPlanError("AI returned non-object JSON.")
    plans = data.get("plans") or []
    if not isinstance(plans, list):
        raise AIPlanError("AI returned 'plans' in an unexpected shape.")
    return [p for p in plans if isinstance(p, dict)]


# ---------------------------------------------------------------------------
# Materialisation: AI choices -> real DB rows -> validated plan dict
# ---------------------------------------------------------------------------

def _build_indexes(db_data):
    by_id = {}
    for t in (db_data.get("transports") or []):
        by_id[str(t.get("_id"))] = t
    spots = {}
    for s in (db_data.get("spots") or []):
        spots[str(s.get("_id"))] = s
    tours = {}
    for t in (db_data.get("tours") or []):
        tours[str(t.get("_id"))] = t
    guides = {}
    for g in (db_data.get("guides") or []):
        guides[str(g.get("userId"))] = g
    hotels = {}
    for h in (db_data.get("hotels") or []):
        hotels[h.get("id")] = h
    foods = {}
    for f in (db_data.get("foods") or []):
        for fid in (f.get("foodId"), f.get("bookableId")):
            if fid:
                foods[str(fid)] = f
    return by_id, spots, tours, guides, hotels, foods


def _validate(hotel, hotel_selection):
    if not isinstance(hotel_selection, dict):
        return None
    if not hotel:
        return None
    rid = str(hotel_selection.get("roomTypeId") or "").lower()
    for rt in (hotel.get("roomTypes") or []):
        if str(rt.get("id") or "").lower() == rid:
            avail = _cost_f(rt.get("availableRooms"))
            if avail > 0:
                return {
                    "id": hotel.get("id"),
                    "name": hotel.get("name"),
                    "city": hotel.get("city"),
                    "lat": hotel.get("lat"),
                    "lng": hotel.get("lng"),
                    "roomTypeId": rt.get("id"),
                    "roomTypeName": rt.get("name"),
                    "pricePerNight": _cost_f(rt.get("pricePerNight")),
                    "availableRooms": int(avail),
                    "rating": _cost_f(hotel.get("starRating")) or 3.0,
                    "stars": int(_cost_f(hotel.get("starRating")) or 3),
                }
    return None


def _materialize(parsed, db_data, sel):
    """Turn one AI selection into a validated plan dict (same shape as the old
    deterministic optimizer kept, so downstream code is unchanged)."""
    by_id, spots, tours, guides, hotels, foods = _build_indexes(db_data)

    leg = None
    tid = sel.get("transportId")
    if isinstance(tid, dict):
        tid = tid.get("id")
    if tid:
        leg = by_id.get(str(tid))
        if not leg:
            raise AIPlanError("AI referenced an unknown transport id.")

    hotel = None
    hsel = sel.get("hotel")
    if isinstance(hsel, dict) and hsel.get("hotelId"):
        hotel = _validate(hotels.get(str(hsel.get("hotelId"))), hsel)

    guide = None
    gid = sel.get("guideId")
    if isinstance(gid, dict):
        gid = gid.get("id")
    if gid:
        guide = guides.get(str(gid))
        if not guide:
            raise AIPlanError("AI referenced an unknown guide id.")

    activities = []
    sel_spots = []
    order = sel.get("activityOrder")
    if order is None:
        order = []
    elif isinstance(order, str):
        raise AIPlanError("AI returned 'activityOrder' as a string; expected a list.")
    for entry in order:
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("spotId") or "")
        if not sid:
            continue
        s = spots.get(sid)
        if not s:
            raise AIPlanError("AI referenced an unknown spot id %s." % sid)
        sel_spots.append(sid)
        a = {
            "title": s.get("name"),
            "location": _name((s.get("location") or {}).get("name"), "") or s.get("city", ""),
            "price": _cost_f(s.get("entryFee")),
            "spotId": s.get("_id"),
            "openingTime": s.get("openingTime"),
            "closingTime": s.get("closingTime"),
            "lat": (s.get("location") or {}).get("lat"),
            "lng": (s.get("location") or {}).get("lng"),
            "bookable": True,
        }
        tid = str(entry.get("tourId") or "")
        tour = tours.get(tid) if tid else None
        if tour:
            a["tourId"] = tour.get("_id")
            a["tourName"] = tour.get("name")
            a["tourCost"] = _cost_f(tour.get("cost"))
            a["tourDuration"] = tour.get("duration")
            a["tourGuideRequired"] = tour.get("guideRequired")
        activities.append(a)

    if guide:
        activities.append({
            "title": "Guided tour with %s" % guide.get("name"),
            "location": (guide.get("profile") or {}).get("specialty", "") or parsed["destination"],
            "price": _cost_f((guide.get("pricing") or {}).get("pricePerHour")) or 0,
            "guideId": guide.get("userId"),
            "bookable": True,
        })

    foods_sel = []
    food_ids = sel.get("foodIds")
    if isinstance(food_ids, str):
        food_ids = [food_ids]
    for fid in (food_ids or [])[:2]:
        f = foods.get(str(fid))
        if not f:
            continue
        entry = dict(f)
        entry.setdefault("pricePerPerson", _cost_f(f.get("pricePerNight") or f.get("price") or 0))
        entry.setdefault("bookableId", None)
        foods_sel.append(entry)

    route_km = None
    if leg and leg.get("type") in ("CAB", "AUTO"):
        try:
            from services.maps_distance import route_distance_km
            route_km = route_distance_km(parsed.get("origin"), parsed.get("destination"))
        except Exception:
            route_km = None

    decision = _arrive_decision(parsed, leg, hotel, activities)
    (daily_plan, total_cost, breakdown) = _ai_daily(parsed, leg, hotel, activities,
                                                    foods_sel, decision=decision,
                                                    distance_km=route_km)

    style = sel.get("style")
    style = str(style or "").upper()
    if style not in STYLE_WEIGHTS:
        style = "BALANCED"
    weights = dict(STYLE_WEIGHTS.get(style, STYLE_WEIGHTS["BALANCED"]))
    budget = parsed.get("budget", 0) * parsed.get("travelers", 1)
    scores = _scores(parsed, leg, hotel, activities, style, weights,
                     budget or 1_000_000, distance_km=route_km)

    reason = []
    if leg:
        reason.append("Selected %s · %s (%s) at ₹%s." %
                      (leg.get("type"), leg.get("serviceName"), _corridor_label(leg),
                       _money(_fare(leg, route_km))))
    if hotel:
        reason.append("Staying at %s (%s) ₹%s/night." %
                      (hotel.get("name"), hotel.get("stars"), _money(hotel.get("pricePerNight"))))
    if activities:
        reason.append("Itinerary ordered per preference: %s." %
                      ", ".join((a.get("title") for a in activities[:5])))
    if guide:
        reason.append("Local guide %s assigned for %s." % (guide.get("name"), parsed["destination"]))
    ai_reason = sel.get("reasoning")
    if isinstance(ai_reason, str):
        ai_reason = [ai_reason]
    reason.extend((ai_reason if isinstance(ai_reason, list) else [])[:3])
    if not reason:
        reason.append("AI-generated itinerary from %s preferences." % style)

    return {
        "planType": style,
        "totalCost": round(total_cost, 2),
        "comfortScore": scores["comfortScore"],
        "optimizationScore": scores["totalScore"],
        "bookableIds": [x.get("spotId") or x.get("guideId") for x in activities if x.get("bookable")],
        "dbSource": True,
        "transport": leg,
        "hotel": hotel,
        "arrivalDecision": decision.get("mode"),
        "transports": [leg] if leg else [],
        "activities": activities,
        "foods": foods_sel,
        "dailyPlan": daily_plan,
        "costBreakdown": breakdown,
        "travelTime": "%s" % (leg and leg.get("type") or "N/A"),
        "days": parsed["durationDays"],
        "reasoning": reason,
        "scores": scores,
    }


def _name(v, fallback):
    return (v or "").strip() or fallback


# ---------------------------------------------------------------------------
# Daily-plan scheduler (driven solely by the AI's ordered selections)
# ---------------------------------------------------------------------------

def _arrive_decision(request, leg, hotel, activities):
    spot = next((a for a in activities if a.get("openingTime")), None)
    if not leg or not hotel:
        return {"mode": "DIRECT_SPOT", "reason": "Activity-first routing (no hotel or transport leg)."}
    if spot is None:
        return {"mode": "DIRECT_SPOT", "reason": "No opening hours on the first destination; routing straight to it."}
    arr = _arrival_time_ai(leg)
    return {"mode": "DIRECT_SPOT",
            "reason": "AI-ordered arrival routing for %s." % spot.get("title")}


def _arrival_time_ai(leg):
    try:
        dep = parse_datetime("2026-01-01", leg.get("boardingTime") or leg.get("departureTime") or "06:00")
        if leg.get("boardingDay") is not None:
            dep += timedelta(days=int(leg.get("boardingDay") or 0))
        ride = int(learned_duration_or_default(leg.get("type"), 90))
        return dep + timedelta(minutes=ride)
    except Exception:
        return datetime.utcnow() + timedelta(hours=3)


def _ai_daily(request, leg, hotel, activities, foods, decision=None, distance_km=None):
    start = request["startDate"] if isinstance(request["startDate"], datetime) else datetime.utcnow()
    days = request["durationDays"]
    travelers = request.get("travelers", 1)
    transfer_min = int(learned_duration_or_default("TRANSFER", 90))
    food_min = int(learned_duration_or_default("FOOD", 60))
    act_min = int(learned_duration_or_default("ACTIVITY", 180))
    hotel_min = int(learned_duration_or_default("HOTEL", 60))

    if decision is None:
        decision = {"mode": "HOTEL_FIRST", "reason": ""}

    act_list = [a for a in activities if not (a.get("title") or "").startswith("Guided")]
    guided = next((x for x in activities if (x.get("title") or "").startswith("Guided")), None)

    daily = []
    total = 0.0
    breakdown = {"transport": 0.0, "hotel": 0.0, "activities": 0.0,
                 "food": 0.0, "flights": 0.0}

    def add(pairs):
        nonlocal total
        out = []
        for item in pairs:
            out.append(item)
            total += _cost(item.get("cost")) * travelers
        return out

    def tour_item(a, at):
        if a and a.get("tourId"):
            return {
                "type": "ACTIVITY", "title": "Tour · %s" % a.get("tourName"),
                "provider": a.get("location", ""), "cost": _cost(a.get("tourCost")),
                "startTime": at.isoformat(),
                "endTime": (at + timedelta(minutes=int(_cost(a.get("tourDuration")) * 60) or act_min)).isoformat(),
                "bookableId": "tour:%s" % a.get("tourId")}
        return None

    # Slice ordered activities across the trip days (everyday gets its own
    # activity; remainder falls to the middle days).
    n_acts = len(act_list)
    per_day = []
    for d in range(days):
        per_day.append([])
    if n_acts:
        slots = per_day[-1] if days > 1 else per_day[0]
        for i in range(n_acts):
            if i == 0:
                per_day[0].append(act_list[i])
            elif days == 1:
                per_day[0].append(act_list[i])
            elif i == n_acts - 1 and days > 1:
                per_day[-1].append(act_list[i])
            else:
                per_day[min(i, days - 1)].append(act_list[i])

    for day in range(1, days + 1):
        d = start + timedelta(days=day - 1)
        items = []
        slot = d.replace(hour=9, minute=0)

        if day == 1 and leg:
            dep = parse_datetime(d.strftime("%Y-%m-%d"), leg.get("boardingTime") or "06:00")
            dep = dep + timedelta(days=int(leg.get("boardingDay") or 0))
            ride = int(learned_duration_or_default(leg.get("type"), transfer_min))
            arr = dep + timedelta(minutes=ride)
            leg_fare = _cost(_fare(leg, distance_km))
            breakdown["transport"] += leg_fare * travelers
            items = add([
                {"type": "TRANSFER", "title": "Home to boarding point",
                 "provider": "Cab", "cost": int(transfer_min * 4 * travelers),
                 "startTime": (dep - timedelta(minutes=90)).isoformat(),
                 "endTime": dep.isoformat()},
                {"type": leg.get("type", "TRANSPORT"),
                 "title": "%s · %s" % (leg.get("type"), leg.get("serviceName", "")),
                 "provider": leg.get("serviceName", ""),
                 "vehicle": _vehicle_label(leg), "cost": leg_fare,
                 "startTime": dep.isoformat(), "endTime": arr.isoformat(),
                 "distanceKm": distance_km, "bookableId": "transport:%s" % leg["_id"]},
                {"type": "TRANSFER", "title": "Arrival to stay", "provider": "Cab",
                 "cost": int(transfer_min * 3 * travelers),
                 "startTime": (arr + timedelta(minutes=20)).isoformat(),
                 "endTime": (arr + timedelta(minutes=20 + transfer_min)).isoformat()},
            ])
            slot = item_after(items)

        if day == 1 and hotel and decision.get("mode") != "DIRECT_SPOT":
            breakdown["hotel"] += _cost(hotel.get("pricePerNight")) * travelers
            items.extend(add([
                {"type": "HOTEL", "title": "Check-in · %s" % hotel.get("name"),
                 "provider": hotel.get("name"), "cost": _cost(hotel.get("pricePerNight")),
                 "startTime": slot.isoformat(),
                 "endTime": (slot + timedelta(minutes=hotel_min)).isoformat(),
                 "bookableId": "hotel:%s:%s" % (hotel.get("id"), hotel.get("roomTypeId"))},
            ]))
            slot = item_after(items)

        for a in per_day[day - 1]:
            breakdown["activities"] += _cost(a.get("price")) * travelers
            items.extend(add([
                {"type": "ACTIVITY", "title": a["title"], "provider": a.get("location", ""),
                 "cost": _cost(a.get("price")), "startTime": slot.isoformat(),
                 "endTime": (slot + timedelta(minutes=act_min)).isoformat(),
                 "bookableId": "spot:%s" % a.get("spotId") if a.get("spotId") else None},
            ]))
            slot = item_after(items)
            tour = tour_item(a, slot)
            if tour:
                breakdown["activities"] += _cost(a.get("tourCost")) * travelers
                items.extend(add([tour]))
                slot = item_after(items)
        if guided and day == days:
            gslot = slot
            breakdown["activities"] += _cost(guided.get("price")) * travelers
            items.extend(add([
                {"type": "ACTIVITY", "title": guided["title"],
                 "provider": guided.get("location", ""), "cost": _cost(guided.get("price")),
                 "startTime": gslot.isoformat(),
                 "endTime": (gslot + timedelta(minutes=act_min)).isoformat(),
                 "bookableId": "guide:%s" % guided.get("guideId") if guided.get("guideId") else None},
            ]))

        if foods and (day > 1 or not per_day[0]):
            f0 = foods[0] if foods else None
            items.extend(add([
                {"type": "FOOD", "title": "Breakfast · %s" % _name(f0 and f0.get("name"), "Local cafe"),
                 "provider": f0 and f0.get("name") or "",
                 "cost": _cost(f0 and f0.get("pricePerPerson")) if f0 else 0,
                 "bookableId": f0 and f0.get("bookableId") or None,
                 "startTime": slot.isoformat(),
                 "endTime": (slot + timedelta(minutes=food_min)).isoformat()},
            ]))
            slot = item_after(items)

        if day == days:
            items.extend(add([
                {"type": "TRANSFER", "title": "Return home transfer", "provider": "Cab",
                 "cost": int(transfer_min * 4 * travelers),
                 "startTime": slot.isoformat(),
                 "endTime": (slot + timedelta(minutes=transfer_min)).isoformat()},
            ]))

        daily.append({"day": day, "date": d.isoformat(), "items": items})

    return daily, round(total, 2), {k: round(v, 2) for k, v in breakdown.items()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_ai_plans(parsed, db_data, verbose=True):
    """Generate 3 AI plans (BUDGET/BALANCED/PREMIUM) exclusively via AI.

    Raises AIPlanError when the AI backend is unavailable or returns an
    unusable response, so the caller NEVER falls back to code-rule plans.
    """
    if not is_ai_available():
        raise AIPlanError("No AI provider is configured (missing "
                          "GEMINI_API_KEY / OPENROUTER_API_KEY).")

    brief = _catalogue_brief(db_data)
    if not brief["transports"] and not brief["spots"]:
        raise AIPlanError("No registered inventory available for this route.")

    prompt = _build_prompt(parsed, brief)
    raw = call_ai(prompt, _SYSTEM, max_tokens=2200, temperature=0.3)
    if not raw:
        raise AIPlanError("AI provider returned no content.")

    selections = _parse_response(raw)
    plans = []
    for sel in selections:
        try:
            plans.append(_materialize(parsed, db_data, sel))
        except AIPlanError:
            raise  # a genuinely unusable AI plan is a hard error, never fall back
        except Exception as e:
            raise AIPlanError("AI plan could not be materialised (%s)." % e)

    if not plans:
        raise AIPlanError("AI returned no usable plans.")
    plans.sort(key=lambda p: p["optimizationScore"], reverse=True)
    for p in plans:
        p["costBreakdown"] = p.get("costBreakdown") or {
            "transport": 0.0, "hotel": 0.0, "activities": 0.0,
            "food": 0.0, "flights": 0.0}
    return plans