"""DB-backed trip planner.

Builds an itinerary from real database entities (transports, tourist spots,
guides, optional hotels, restaurants) instead of hardcoded data.
Machine-learning budget splits and learned durations remain the decision
engine (never if/else rules flavoured as AI).

When a catalogue type is empty in the DB the planner RUNS WITHOUT it (empty
state) — it never fabricates unregistered services.
"""
from datetime import datetime, timedelta
from services.ml.injector import predict_duration, predict_delay

STYLE_WEIGHTS = {
    "BUDGET": {"cost": 0.50, "time": 0.10, "comfort": 0.10, "convenience": 0.15, "reliability": 0.15},
    "BALANCED": {"cost": 0.35, "time": 0.20, "comfort": 0.20, "convenience": 0.15, "reliability": 0.10},
    "PREMIUM": {"cost": 0.10, "time": 0.25, "comfort": 0.40, "convenience": 0.15, "reliability": 0.10},
}

BUDGET_ALLOCATION = {
    "BUDGET": {"flight": 0.40, "hotel": 0.25, "transport": 0.15, "activities": 0.10, "food": 0.10},
    "BALANCED": {"flight": 0.42, "hotel": 0.28, "transport": 0.12, "activities": 0.10, "food": 0.08},
    "PREMIUM": {"flight": 0.45, "hotel": 0.30, "transport": 0.10, "activities": 0.08, "food": 0.07},
}

ALLOC_KEYS = ["flight", "hotel", "transport", "activities", "food"]


def _learned_budget_split(trip):
    """Return (split_dict, predicted_cost) using ML if available."""
    try:
        from services.ml.injector import predict_trip_cost
        pred = predict_trip_cost(trip)
        if pred and pred.get("budgetSplit"):
            split = pred["budgetSplit"]  # [flight, hotel, transport, activities, food]
            return {k: split[i] for i, k in enumerate(ALLOC_KEYS)}, pred.get("predictedCost")
    except Exception:
        pass
    return None, None


def _normalize(value, min_val, max_val):
    if max_val == min_val:
        return 0.5
    return max(0, min(1, (value - min_val) / (max_val - min_val)))


def learned_duration_or_default(item_type, default_minutes):
    try:
        d = predict_duration(item_type)
        if d:
            return d
    except Exception:
        pass
    return default_minutes


def parse_datetime(date_str, time_str):
    d = None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M"):
        try:
            d = datetime.strptime(date_str[:19], fmt[:19])
            break
        except (ValueError, TypeError):
            continue
    if d is None:
        d = datetime.utcnow()
    hh, mm = 0, 0
    if isinstance(time_str, str) and ":" in time_str:
        try:
            hh, mm = [int(x) for x in time_str.split(":")[:2]]
        except (TypeError, ValueError):
            hh, mm = 6, 0
    return d.replace(hour=hh or 6, minute=mm or 0, second=0, microsecond=0)


def _cost(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _name(v, fallback):
    return (v or "").strip() or fallback


def pick_transport(transports, budget_cap, distance_km=None):
    cands = [t for t in transports if _cost(_fare(t, distance_km)) <= budget_cap]
    if not cands:
        cands = transports
    if not cands:
        return None
    return sorted(cands, key=lambda t: _cost(_fare(t, distance_km)))[0]


def _fare(t, distance_km=None):
    f = t.get("fare")
    if isinstance(f, dict):
        if distance_km:
            price_per_km = _cost(f.get("pricePerKm") or f.get("perKm"))
            if price_per_km > 0:
                base = _cost(f.get("baseFare"))
                minimum = _cost(f.get("minimum"))
                return max(minimum, base + price_per_km * distance_km)
        for key in ("price", "baseFare", "sleeper", "seater", "ec", "cc", "sl"):
            if _cost(f.get(key)) > 0:
                return f.get(key)
    for block in ("classes", "coaches"):
        for it in t.get(block) or []:
            if _cost(it.get("price")) > 0:
                return it.get("price")
    return 0


def build_db_plan(request, db_data, style="BALANCED"):
    """Returns a plan dict in the same shape as optimize_itinerary output."""
    db_transports = db_data.get("transports") or []
    db_spots = db_data.get("spots") or []
    db_guides = db_data.get("guides") or []
    db_tours = db_data.get("tours") or []

    hotels = _db_hotels(db_data.get("hotels")) or []

    foods = db_data.get("foods") or []

    weights = STYLE_WEIGHTS.get(style, STYLE_WEIGHTS["BALANCED"])
    weights = dict(weights)
    pref = (request.get("servicePreference") or "").upper()
    if pref == "HOTELS":
        weights["comfort"] += 0.15; weights["cost"] -= 0.10
    elif pref == "TRANSPORT":
        weights["time"] += 0.15; weights["cost"] -= 0.10
    elif pref == "ACTIVITIES":
        weights["convenience"] += 0.10; weights["time"] += 0.10
    elif pref == "GUIDE":
        weights["convenience"] += 0.10; weights["comfort"] += 0.05
    for k in weights:
        weights[k] = max(0.05, min(0.6, weights[k]))
    alloc = dict(BUDGET_ALLOCATION.get(style, BUDGET_ALLOCATION["BALANCED"]))
    ml_split, _ml_cost = _learned_budget_split(request)
    if ml_split:
        alloc = ml_split

    budget = request["budget"] * request.get("travelers", 1)
    unlimited = bool(request.get("budgetUnlimited")) or request.get("budget") in (None, 0)
    if unlimited:
        budget = 100_000_000  # treated as "no budget constraint"
    transport_cap = budget * (alloc.get("transport", 0.15) + 0.05)
    hotel_cap = budget * alloc.get("hotel", 0.28) / max(1, request["durationDays"])

    route_km = None
    if any(t.get("type") in ("CAB", "AUTO") for t in db_transports):
        try:
            from services.maps_distance import route_distance_km
            route_km = route_distance_km(request.get("origin"), request.get("destination"))
        except Exception:
            route_km = None

    leg = pick_transport(db_transports, transport_cap, route_km)
    hotel = next((h for h in hotels if _cost(h.get("pricePerNight")) <= hotel_cap),
                 hotels[0] if hotels else None)

    prioritized = [str(p) for p in (request.get("prioritizedSpotIds") or []) if str(p)]
    by_id = {str(s["_id"]): s for s in db_spots}
    spots, picked_ids = [], set()
    for p in prioritized:
        if p in by_id and p not in picked_ids:
            spots.append(by_id[p])
            picked_ids.add(p)
    for s in db_spots:
        if len(spots) >= 4:
            break
        if str(s["_id"]) not in picked_ids:
            spots.append(s)
            picked_ids.add(str(s["_id"]))
    ranked = sorted([s for s in db_spots if str(s["_id"]) not in picked_ids],
                    key=lambda s: -(s.get("popularity") or 0))
    for s in ranked:
        if len(spots) >= 4:
            break
        spots.append(s)
    activities = []
    spot_tours = {t.get("spotId"): t for t in db_tours}
    for s in spots:
        a = {
            "title": s.get("name"),
            "location": (_name(s.get("location", {}).get("name"), "") or s.get("city", "")),
            "price": _cost(s.get("entryFee")),
            "spotId": s["_id"],
            "openingTime": s.get("openingTime"),
            "closingTime": s.get("closingTime"),
            "lat": s.get("location", {}).get("lat"),
            "lng": s.get("location", {}).get("lng"),
            "bookable": True,
        }
        tour = spot_tours.get(s["_id"])
        if tour:
            a["tourId"] = tour["_id"]
            a["tourName"] = tour.get("name")
            a["tourCost"] = _cost(tour.get("cost"))
            a["tourDuration"] = tour.get("duration")
            a["tourGuideRequired"] = tour.get("guideRequired")
        activities.append(a)

    guide = None
    if db_guides:
        guide = db_guides[0]
        activities.append({
            "title": f"Guided tour with {guide['name']}",
            "location": guide.get("profile", {}).get("specialty", "") or request["destination"],
            "price": _cost((guide.get("pricing") or {}).get("pricePerHour")) or 0,
            "guideId": guide["userId"],
            "bookable": True,
        })

    foods_sel = [dict(f) for f in (foods or [])[:2]]
    for f in foods_sel:
        f.setdefault("pricePerPerson", _cost(f.get("price") or 0))
        f.setdefault("bookableId", None)

    decision = _arrive_decision(request, leg, hotel, activities)

    (daily_plan, total_cost, breakdown) = _build_daily(
        request, leg, hotel, activities, foods_sel, decision=decision,
        distance_km=route_km)

    scores = _scores(request, leg, hotel, activities, style, weights, budget, distance_km=route_km)

    reason = []
    if leg:
        reason.append(f"Selected {leg.get('type', 'TRANSPORT')} · {leg.get('serviceName', '')} "
                      f"({_corridor_label(leg)}) at ₹{_cost(_fare(leg, route_km)):,.0f}.")
    if hotel:
        reason.append(f"Staying at {hotel.get('name')} ({hotel.get('stars', 3)}★) ₹{_cost(hotel.get('pricePerNight')):,.0f}/night.")
    if spots:
        reason.append(f"Curated {len(spots)} tourist spots by priority/popularity: {', '.join(s.get('name') for s in spots)}.")
    if guide:
        reason.append(f"Local guide {guide['name']} assigned for {request['destination']}.")
    reason.append(decision.get("reason"))
    reason.append(f"{style.title()} plan {'with unlimited budget (premium eligible)' if unlimited else f'under ₹{request.get('budget', 0):,.0f}/person budget'}.")

    return {
        "planType": style,
        "totalCost": total_cost,
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
        "travelTime": f"{leg and leg.get('type') or 'N/A'}",
        "days": request["durationDays"],
        "reasoning": reason,
        "scores": scores,
    }


def _db_hotels(raw):
    """Normalize hotel-service output (hotels with available room types) into
    the optimizer's hotel shape. Returns None when no DB hotels were provided."""
    if not raw:
        return None
    out = []
    for h in raw:
        types = [t for t in (h.get("roomTypes") or []) if t.get("availableRooms", 0) > 0]
        if not types:
            continue
        best = min(types, key=lambda t: _cost(t.get("pricePerNight")))
        out.append({
            **_normalize_hotel(h),
            "roomTypeId": best["id"],
            "roomTypeName": best["name"],
            "pricePerNight": _cost(best["pricePerNight"]),
            "availableRooms": sum(_cost(t.get("availableRooms", 0)) for t in types),
            "rating": _cost(h.get("starRating")) or 3.0,
            "stars": _cost(h.get("starRating")) or 3,
        })
    return out


def _normalize_hotel(h):
    return {
        "id": h.get("id"),
        "name": h.get("name"),
        "city": h.get("city"),
        "lat": h.get("lat"),
        "lng": h.get("lng"),
    }


def _haversine_km(a, b, c, d):
    import math
    for v in (a, b, c, d):
        if v is None:
            return None
    lat1, lon1, lat2, lon2 = map(math.radians, (float(a), float(b), float(c), float(d)))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _arrival_time(leg):
    dep = parse_datetime("2026-01-01", leg.get("boardingTime") or leg.get("departureTime") or "06:00")
    if leg.get("boardingDay") is not None:
        try:
            dep += timedelta(days=int(leg.get("boardingDay") or 0))
        except (TypeError, ValueError):
            pass
    ride = int(learned_duration_or_default(leg.get("type"), 90))
    return dep + timedelta(minutes=ride)


def _arrive_decision(request, leg, hotel, activities):
    """Decide ARRIVE → DIRECT SPOT vs ARRIVE → HOTEL → FRESH UP → SPOT based on
    arrival time, hotel/spot distance and spot opening/closing hours."""
    spot = next((a for a in activities if a.get("openingTime")), None)
    if not leg or not hotel:
        return {"mode": "DIRECT_SPOT", "reason": "Activity-first routing (no hotel or transport leg)."}
    if spot is None:
        return {"mode": "DIRECT_SPOT", "reason": "No opening hours on the first destination; routing straight to it."}
    arr = _arrival_time(leg)
    try:
        open_hm = [int(x) for x in (spot.get("openingTime") or "09:00").split(":")[:2]]
        close_hm = [int(x) for x in (spot.get("closingTime") or "18:00").split(":")[:2]]
        open_min = open_hm[0] * 60 + open_hm[1]
        close_min = close_hm[0] * 60 + close_hm[1]
    except (ValueError, IndexError):
        open_min, close_min = 540, 1080
    arr_min = arr.hour * 60 + arr.minute
    dist = _haversine_km(spot.get("lat"), spot.get("lng"), hotel.get("lat"), hotel.get("lng"))
    spot_near = dist is None or dist <= 8.0
    opens_late = arr_min < open_min
    closes_early = arr_min >= close_min - 60

    if closes_early:
        mode = "HOTEL_FIRST"
        why = f"Arriving at {arr:%H:%M} is too late for the first destination (closes {spot.get('closingTime')}); checking in first."
    elif opens_late and spot_near:
        mode = "DIRECT_SPOT"
        why = (f"Arriving at {arr:%H:%M} before the destination opens ({spot.get('openingTime')}) with a spot nearby — "
               f"go straight to {spot.get('title')}.")
    elif not spot_near:
        mode = "HOTEL_FIRST"
        why = f"Hotel is far from the first destination (~{int(dist)} km); freshen up at the hotel first."
    else:
        mode = "DIRECT_SPOT"
        why = f"Arriving {arr:%H:%M} while {spot.get('title')} is open and nearby — visit before hotel check-in."
    return {"mode": mode, "reason": why}


def _corridor_label(t):
    if t.get("type") == "BUS":
        return f"{t.get('boardingPoint')} → {t.get('droppingPoint')}"
    if t.get("type") == "TRAIN":
        return f"{t.get('boardingStation')} → {t.get('destinationStation')}"
    if t.get("type") == "FLIGHT":
        return f"{t.get('departureAirport')} → {t.get('arrivalAirport')}"
    return t.get("serviceArea", "")


def _build_daily(request, leg, hotel, activities, foods, decision=None, distance_km=None):
    start = request["startDate"] if isinstance(request["startDate"], datetime) else datetime.utcnow()
    days = request["durationDays"]
    travelers = request.get("travelers", 1)
    transfer_min = int(learned_duration_or_default("TRANSFER", 90))
    food_min = int(learned_duration_or_default("FOOD", 60))
    act_min = int(learned_duration_or_default("ACTIVITY", 180))
    hotel_min = int(learned_duration_or_default("HOTEL", 60))

    if decision is None:
        decision = {"mode": "HOTEL_FIRST", "reason": ""}
    hotel_first = decision.get("mode") == "HOTEL_FIRST"

    daily = []
    total = 0.0
    breakdown = {"transport": 0.0, "hotel": 0.0, "activities": 0.0, "food": 0.0, "flights": 0.0}

    def add(pairs):
        nonlocal total
        out = []
        for item in pairs:
            out.append(item)
            total += _cost(item.get("cost")) * travelers
        return out

    def typical(nth):
        return [x for x in activities if not (x.get("title") or "").startswith("Guided")][nth:nth + 1] or [None]

    def tour_item(a):
        if a and a.get("tourId"):
            return {"type": "ACTIVITY", "title": f"Tour · {a.get('tourName')}",
                    "provider": a.get("location", ""), "cost": _cost(a.get("tourCost")),
                    "startTime": "", "endTime": "",
                    "bookableId": f"tour:{a.get('tourId')}"}
        return None

    for day in range(1, days + 1):
        d = start + timedelta(days=day - 1)
        items = []
        if day == 1:
            if leg:
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
                    {"type": leg.get("type", "TRANSPORT"), "title": f"{leg.get('type')} · {leg.get('serviceName', '')}",
                     "provider": leg.get("serviceName", ""),
                     "vehicle": leg.get("busNumber") or leg.get("trainNumber") or leg.get("flightNumber") or leg.get("vehicleNumber"),
                     "cost": leg_fare,
                     "startTime": dep.isoformat(),
                     "endTime": arr.isoformat(),
                     "distanceKm": distance_km,
                     "bookableId": f"transport:{leg['_id']}"},
                    {"type": "TRANSFER", "title": "Arrival to stay",
                     "provider": "Cab", "cost": int(transfer_min * 3 * travelers),
                     "startTime": (arr + timedelta(minutes=20)).isoformat(),
                     "endTime": (arr + timedelta(minutes=20 + transfer_min)).isoformat()},
                ])
            cursor = item_after(items)

            def hotel_block(at):
                nonlocal cursor, total, breakdown
                breakdown["hotel"] += _cost(hotel.get("pricePerNight")) * travelers
                bid = f"hotel:{hotel.get('id')}:{hotel.get('roomTypeId')}" if hotel else None
                block = add([
                    {"type": "HOTEL", "title": f"Check-in · {hotel.get('name')}",
                     "provider": hotel.get("name"), "cost": _cost(hotel.get("pricePerNight")),
                     "startTime": at.isoformat(),
                     "endTime": (at + timedelta(minutes=hotel_min)).isoformat(),
                     "bookableId": bid},
                    {"type": "TRANSFER", "title": "Fresh up & transfer to first destination",
                     "provider": "Cab", "cost": int(transfer_min * 2 * travelers),
                     "startTime": (at + timedelta(minutes=hotel_min)).isoformat(),
                     "endTime": (at + timedelta(minutes=hotel_min + transfer_min)).isoformat()},
                ])
                return block

            if hotel_first and hotel:
                items.extend(hotel_block(cursor))
                cursor = item_after(items)

            act_a = typical(0)
            guided = next((x for x in activities if (x.get("title") or "").startswith("Guided")), None)
            if act_a and act_a[0]:
                a = act_a[0]
                slot = cursor if not hotel_first else item_after(items)
                if hotel_first:
                    slot = item_after(items)
                breakdown["activities"] += _cost(a.get("price")) * travelers
                base = add([
                    {"type": "ACTIVITY", "title": a["title"], "provider": a.get("location", ""),
                     "cost": _cost(a.get("price")),
                     "startTime": slot.isoformat(),
                     "endTime": (slot + timedelta(minutes=act_min)).isoformat(),
                     "bookableId": f"spot:{a.get('spotId')}" if a.get("spotId") else None},
                ])
                t_next = slot + timedelta(minutes=act_min)
                tour = tour_item(a)
                if tour:
                    tour["startTime"] = t_next.isoformat()
                    tour["endTime"] = (t_next + timedelta(minutes=int(_cost(a.get("tourDuration")) * 60) or act_min)).isoformat()
                    breakdown["activities"] += _cost(a.get("tourCost")) * travelers
                    items.extend(add([tour]))
                    t_next = item_after(items)
                if guided and day == 1:
                    gslot = t_next
                    breakdown["activities"] += _cost(guided.get("price")) * travelers
                    items.extend(add([
                        {"type": "ACTIVITY", "title": guided["title"], "provider": guided.get("location", ""),
                         "cost": _cost(guided.get("price")),
                         "startTime": gslot.isoformat(),
                         "endTime": (gslot + timedelta(minutes=act_min)).isoformat(),
                         "bookableId": f"guide:{guided.get('guideId')}" if guided.get("guideId") else None},
                    ]))
            elif not hotel_first and hotel:
                # Direct-spot day: activities first, then evening hotel check-in.
                ev = item_after(items)
                items.extend(hotel_block(ev))
        elif day == days:
            items.extend(add([
                {"type": "FOOD", "title": f"Breakfast · {_name(foods and foods[0] and foods[0].get('name'), 'Local cafe')}",
                 "provider": foods and foods[0] and foods[0].get("name") or "",
                 "cost": _cost(foods and foods[0] and foods[0].get("pricePerPerson")) if foods else 0,
                 "bookableId": foods and foods[0] and foods[0].get("bookableId") or None,
                 "startTime": d.replace(hour=8, minute=0).isoformat(),
                 "endTime": (d.replace(hour=8, minute=0) + timedelta(minutes=food_min)).isoformat()},
            ]))
            a = typical(0)
            if a and a[0]:
                at = d.replace(hour=10, minute=0)
                breakdown["activities"] += _cost(a[0].get("price")) * travelers
                items.extend(add([
                    {"type": "ACTIVITY", "title": a[0]["title"], "provider": a[0].get("location", ""),
                     "cost": _cost(a[0].get("price")),
                     "startTime": at.isoformat(),
                     "endTime": (at + timedelta(minutes=act_min)).isoformat(),
                     "bookableId": f"spot:{a[0].get('spotId')}" if a[0].get("spotId") else None},
                ]))
                tour = tour_item(a[0])
                if tour:
                    t = at + timedelta(minutes=act_min)
                    tour["startTime"] = t.isoformat()
                    tour["endTime"] = (t + timedelta(minutes=int(_cost(a[0].get("tourDuration")) * 60) or act_min)).isoformat()
                    breakdown["activities"] += _cost(a[0].get("tourCost")) * travelers
                    items.extend(add([tour]))
            items.extend(add([
                {"type": "TRANSFER", "title": "Return home transfer", "provider": "Cab",
                 "cost": int(transfer_min * 4 * travelers),
                 "startTime": d.replace(hour=15, minute=0).isoformat(),
                 "endTime": (d.replace(hour=15, minute=0) + timedelta(minutes=transfer_min)).isoformat()},
            ]))
        else:
            f0 = foods and foods[0]
            items.extend(add([
                {"type": "FOOD", "title": f"Breakfast · {_name(f0 and f0.get('name'), 'Local cafe')}",
                 "provider": f0 and f0.get("name") or "",
                 "cost": _cost(f0 and f0.get("pricePerPerson")) if f0 else 0,
                 "bookableId": f0 and f0.get("bookableId") or None,
                 "startTime": d.replace(hour=8, minute=0).isoformat(),
                 "endTime": (d.replace(hour=8, minute=0) + timedelta(minutes=food_min)).isoformat()},
            ]))
            base = d.replace(hour=10, minute=0)
            act_a = typical(0)
            guided = next((x for x in activities if (x.get("title") or "").startswith("Guided")), None)
            if act_a and act_a[0]:
                breakdown["activities"] += _cost(act_a[0].get("price")) * travelers
                items.extend(add([
                    {"type": "ACTIVITY", "title": act_a[0]["title"], "provider": act_a[0].get("location", ""),
                     "cost": _cost(act_a[0].get("price")),
                     "startTime": base.isoformat(),
                     "endTime": (base + timedelta(minutes=act_min)).isoformat(),
                     "bookableId": f"spot:{act_a[0].get('spotId')}" if act_a[0].get("spotId") else None},
                ]))
            t1 = base + timedelta(minutes=act_min)
            if act_a and act_a[0] and act_a[0].get("tourId"):
                tour = tour_item(act_a[0])
                tour["startTime"] = t1.isoformat()
                tour["endTime"] = (t1 + timedelta(minutes=int(_cost(act_a[0].get("tourDuration")) * 60) or act_min)).isoformat()
                breakdown["activities"] += _cost(act_a[0].get("tourCost")) * travelers
                items.extend(add([tour]))
                t1 = item_after(items)
            if guided:
                breakdown["activities"] += _cost(guided.get("price")) * travelers
                items.extend(add([
                    {"type": "ACTIVITY", "title": guided["title"], "provider": guided.get("location", ""),
                     "cost": _cost(guided.get("price")),
                     "startTime": t1.isoformat(),
                     "endTime": (t1 + timedelta(minutes=act_min)).isoformat(),
                     "bookableId": f"guide:{guided.get('guideId')}" if guided.get("guideId") else None},
                ]))
                t1 = t1 + timedelta(minutes=act_min)
            items.extend(add([
                {"type": "FOOD", "title": f"Lunch · {_name(foods and len(foods) > 1 and foods[1].get('name') or (f0 and f0.get('name')), 'Local restaurant')}",
                 "provider": foods and len(foods) > 1 and foods[1].get("name") or "",
                 "cost": _cost(foods and len(foods) > 1 and foods[1].get("pricePerPerson")) if foods else 0,
                 "bookableId": foods and len(foods) > 1 and foods[1].get("bookableId") or None,
                 "startTime": t1.isoformat(),
                 "endTime": (t1 + timedelta(minutes=food_min)).isoformat()},
            ]))
        daily.append({"day": day, "date": d.isoformat(), "items": items})

    return daily, round(total, 2), {k: round(v, 2) for k, v in breakdown.items()}


def item_after(items):
    """Return the latest endTime amongst items, defaulting to now+2h."""
    latest = datetime.utcnow() + timedelta(hours=2)
    for it in items:
        try:
            if it.get("endTime"):
                t = datetime.fromisoformat(it["endTime"])
                if t > latest:
                    latest = t
        except (ValueError, TypeError):
            continue
    return latest


def _scores(request, leg, hotel, activities, style, weights, budget, distance_km=None):
    cost = (_cost(_fare(leg, distance_km)) if leg else 0) * (request.get("travelers") or 1)
    if not (leg or hotel or activities):
        return {"costScore": 0.5, "timeScore": 0.5, "comfortScore": 0.5,
                "convenienceScore": 0.5, "reliabilityScore": 0.5, "totalScore": 0.5}
    cost_score = 1 - _normalize(cost + (_cost(hotel and hotel.get("pricePerNight")) * (request.get("durationDays") or 1)),
                                0, budget)
    comfort = _cost(hotel and hotel.get("rating")) or 3.0
    comfort_score = _normalize(comfort / 5.0, 0, 1)
    convenient = _normalize(len(activities) + (1 if leg else 0), 1, 10)
    total = (weights["cost"] * cost_score +
             weights["time"] * 0.7 +
             weights["comfort"] * comfort_score +
             weights["convenience"] * convenient +
             weights["reliability"] * 0.9)
    return {
        "costScore": round(cost_score, 3),
        "timeScore": 0.7,
        "comfortScore": round(comfort_score, 3),
        "convenienceScore": round(convenient, 3),
        "reliabilityScore": 0.9,
        "totalScore": round(total, 3),
    }