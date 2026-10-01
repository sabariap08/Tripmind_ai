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
import time

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
# Real distance-based transfer fare (home -> boarding point, arrival -> stay,
# return home).  Transfers are priced from the ACTUAL road distance returned
# by the Google Maps integration, using a real registered CAB/AUTO fare card
# (max(minimum, baseFare + distanceKm * pricePerKm)).  There is NO flat-rate /
# "₹370" path: when the distance cannot be measured the item carries an
# explicit error instead of a made-up fare.
# ---------------------------------------------------------------------------

def _pick_transfer_cab(cabs, city):
    if not cabs:
        return None
    city = (city or "").lower()

    def key(c):
        area = " ".join([str(c.get("serviceArea") or ""), str(c.get("baseLocation") or "")]).lower()
        per = _cost_f((c.get("fare") or {}).get("pricePerKm") or (c.get("fare") or {}).get("perKm") or 0)
        return (0 if city and city in area else 1, per if per > 0 else float("inf"))
    return min(cabs, key=key)


def _cab_fare_for(cab, distance_km):
    """Real cab/auto fare rule: max(minimum, baseFare + distanceKm*pricePerKm)."""
    if not cab or not distance_km:
        return None
    f = cab.get("fare") or {}
    per = _cost_f(f.get("pricePerKm") or f.get("perKm") or 0)
    if per <= 0:
        return None
    base = _cost_f(f.get("baseFare") or 0)
    minimum = _cost_f(f.get("minimum") or 0) or base
    return max(minimum, base + per * distance_km)


def _transfer_km(origin_obj, dest_obj, label):
    """Measure road distance between two waypoints (coords preferred, else
    address).  Returns km or None.  Every lookup prints the
    ========== TRIPMIND DISTANCE DEBUG ========== block."""
    try:
        from services.maps_distance import route_distance_km
        o_addr = origin_obj.get("address")
        d_addr = dest_obj.get("address")
        return route_distance_km(
            o_addr, d_addr,
            origin_obj.get("lat"), origin_obj.get("lng"),
            dest_obj.get("lat"), dest_obj.get("lng"),
            label=label)
    except Exception as e:
        print("[TripMind] DISTANCE-ERROR: transfer lookup '%s' failed: %s" % (label, e))
        return None


def _leg_points(leg):
    """Boarding + dropping waypoints of a transport leg (coords for buses,
    station/airport names for train & flight)."""
    empty = {"lat": None, "lng": None, "address": None}
    if not leg:
        return dict(empty), dict(empty)
    if leg.get("type") == "BUS":
        board = {"lat": leg.get("boardingLat"), "lng": leg.get("boardingLng"),
                 "address": leg.get("boardingPoint") or ""}
        drop = {"lat": leg.get("droppingLat"), "lng": leg.get("droppingLng"),
                "address": leg.get("droppingPoint") or ""}
    else:
        # Train / flight: the "transfer" happens at the station / airport.
        board = {"lat": None, "lng": None,
                 "address": leg.get("boardingStation") or leg.get("departureAirport") or ""}
        drop = {"lat": None, "lng": None,
                "address": leg.get("destinationStation") or leg.get("arrivalAirport") or ""}
    return board, drop


def _compute_transfers(parsed, leg, hotel, cabs, return_leg=None):
    """Compute the per-leg transfer distances and cab fares for a plan.

    Returns a dict keyed by transfer leg name with {distanceKm, fare, error}:
      - home_to_boarding: user start location -> bus boarding point
      - arrival_to_stay:  bus dropping point -> hotel
      - return_home:      hotel / dropping -> user start location
                           (one-way trips only)
      - stay_to_return_boarding: hotel -> return boarding point (round trips)
      - return_arrival_to_home:  return dropping point -> start (round trips)
    """
    out = {}

    start = parsed.get("startLocation") or {}
    start_obj = {
        "lat": start.get("lat"),
        "lng": start.get("lng"),
        "address": start.get("address") or start.get("origin") or parsed.get("origin") or "",
    }
    city = parsed.get("origin") or ""
    dest_city = parsed.get("destination") or ""

    # Bus boarding waypoint (provider-stored coords, else the point name).
    boarding_obj, dropping_obj = _leg_points(leg)

    hotel_obj = {
        "lat": hotel.get("lat") if hotel else None,
        "lng": hotel.get("lng") if hotel else None,
        "address": (hotel.get("name") if hotel else None) or "",
    }

    def price(label, origin_obj, dest_obj, cab_city=None):
        km = _transfer_km(origin_obj, dest_obj, label)
        cab = _pick_transfer_cab(cabs, cab_city or city)
        fare = None
        error = None
        if km is None:
            error = "Google Maps could not measure the road distance for '%s'; " \
                    "no transfer fare was fabricated." % label
            print("[TripMind] TRANSFER-FARE for '%s': DISTANCE UNKNOWN -> %s" % (label, error))
        else:
            fare = _cab_fare_for(cab, km)
            if fare is None:
                error = "No registered CAB/AUTO fare card found for '%s' to price the transfer." % (cab_city or city)
                print("[TripMind] TRANSFER-FARE for '%s': distance=%.2fkm but NO fare card -> %s"
                      % (label, km, error))
            else:
                card = cab.get("fare") or {}
                print("[TripMind] TRANSFER-FARE for '%s': distance=%.2fkm base=%.2f perKm=%.2f "
                      "minimum=%.2f -> fare=₹%.2f"
                      % (label, km,
                         _cost_f(card.get("baseFare") or 0),
                         _cost_f(card.get("pricePerKm") or card.get("perKm") or 0),
                         _cost_f(card.get("minimum") or 0), fare))
        return {"distanceKm": km, "fare": fare, "cab": cab, "error": error}

    if leg:
        out["home_to_boarding"] = price("home->boarding", start_obj, boarding_obj)
        if hotel:
            out["arrival_to_stay"] = price("arrival->stay", dropping_obj, hotel_obj)
        if return_leg:
            # Round trip: the traveller goes from the stay to the return
            # boarding point, rides back, then transfers from the return
            # arrival point home. The intercity return_home cab is NOT used.
            r_board, r_drop = _leg_points(return_leg)
            out["stay_to_return_boarding"] = price(
                "stay->return-boarding", hotel_obj or dropping_obj, r_board,
                cab_city=dest_city)
            out["return_arrival_to_home"] = price(
                "return-arrival->home", r_drop, start_obj, cab_city=dest_city)
        else:
            out["return_home"] = price("return->home", hotel_obj or dropping_obj, start_obj)
    return out


def _transfer_cost(entry, travelers, capacity=4):
    """Per-traveler transfer cost: the cab ride fare split across the party
    (capped at one ride's capacity), so the plan total = the real whole-fare.
    On a distance/fare failure the item cost is 0 and the explicit error is
    carried in `fareError` instead of a made-up flat price."""
    fare = entry.get("fare") if entry else None
    if fare is None:
        return 0, (entry or {}).get("error")
    cap = max(1, min(int(capacity) or 4, int(travelers) or 1))
    return round(fare / cap, 2), None


def _pick_return_leg(parsed, db_data):
    """Real return-direction transport (destination -> origin) from the
    registered catalogue. Returns None when no return service is registered —
    the plan then falls back to the distance-priced return-home transfer
    instead of inventing a service."""
    dest_city = parsed.get("destination") or ""
    orig_city = parsed.get("origin") or ""
    try:
        from services.transport_service import available_transports, _corridor, _match
        cands = available_transports(dest_city, orig_city, parsed.get("transportType")) or []
        # Directional check: the corridor must run destination -> origin, so a
        # destination-only fallback match (e.g. a local cab) never becomes the
        # intercity return leg.
        cands = [c for c in cands
                 if _corridor(c) and _match(_corridor(c), dest_city, orig_city)]
    except Exception:
        cands = []
    if not cands:
        print("[TripMind] RETURN-LEG: no registered service for %s -> %s "
              "(return transport omitted; transfers still priced by distance)."
              % (dest_city, orig_city))
        return None

    mode = (parsed.get("transportType") or "").upper()

    def fare_of(t):
        f = t.get("fare")
        if isinstance(f, dict):
            return _cost_f(f.get("price") or f.get("baseFare") or f.get("pricePerKm") or 0)
        return _cost_f(f)

    # Prefer the traveller's requested mode, then the cheapest real fare.
    cands.sort(key=lambda t: (0 if mode and str(t.get("type") or "").upper() == mode else 1,
                              fare_of(t)))
    picked = cands[0]
    print("[TripMind] RETURN-LEG: picked %s · %s (%s) at Rs %s for %s -> %s"
          % (picked.get("type"), picked.get("serviceName") or picked.get("name") or "",
             picked.get("_id"), fare_of(picked), parsed.get("destination"),
             parsed.get("origin")))
    return picked


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
            "rating": h.get("rating") or h.get("popularity"),
            "roomTypes": types,
        })

    for f in (db_data.get("foods") or []):
        brief["foods"].append({
            "id": f.get("foodId") or f.get("bookableId"),
            "name": f.get("foodName") or f.get("name"),
            "pricePerPerson": _money(f.get("pricePerPerson")),
            "restaurant": f.get("restaurantName"),
            "provider": f.get("restaurantProvider") or "TripMind",
        })

    return brief


# ---------------------------------------------------------------------------
# Prompt + parsing
# ---------------------------------------------------------------------------

# The planner form lets the traveller opt into premium services. Each key is a
# concrete behaviour change the model must apply to EVERY plan, not a label. If
# we only wrote "premium services opted in: HOTELS" the model routinely ignored
# it and returned the same mid-range plan; these directives are what make the
# selection actually shape the itinerary.
_PREMIUM_DIRECTIVES = {
    "TRANSPORT": ("Comfortable transport: whenever the inventory offers a "
                  "higher-comfort option on this route (AC / higher class / "
                  "better-rated carrier), choose it over the cheapest one - "
                  "prefer flights and AC chair/2-tier over ordinary sleeper."),
    "HOTELS": ("Better hotels: choose the highest-star, best-rated property in "
               "the inventory and its best available room type, not the cheapest "
               "room, when the budget allows."),
    "ACTIVITIES": ("More activities: fill each day with every fitting paid "
                   "activity/tour the inventory offers (guided walks, treks, "
                   "experiences), not just the marquee sight."),
    "GUIDE": ("Local guide: assign a licensed guide from the inventory for the "
              "cultural/heritage stops and include the real guide fee in the "
              "plan."),
}


def _premium_directives(selected):
    """Turn the opted-in premium services into explicit planning instructions."""
    keys = [str(s).upper() for s in (selected or []) if str(s).strip()]
    lines = [_PREMIUM_DIRECTIVES[k] for k in keys if k in _PREMIUM_DIRECTIVES]
    if not lines:
        return ""
    return ("Premium services opted in - apply EVERY directive below to all "
            "three plans using only real inventory options:\n"
            + "\n".join("- " + line for line in lines) + "\n")


# Real meal windows in clock order. Meals are placed at (or after) these times
# so every FOOD item is labelled by the actual time of day it happens, instead
# of a hardcoded "Breakfast" stamped onto a 15:00 item.
_MEAL_WINDOWS = ((8, 30, "Breakfast"), (13, 0, "Lunch"), (20, 0, "Dinner"))


def _meal_label(hour):
    if hour < 11:
        return "Breakfast"
    if hour < 16:
        return "Lunch"
    if hour < 18:
        return "Snacks"
    return "Dinner"


def _build_prompt(parsed, brief, clarifications=None):
    if parsed.get("budgetUnlimited"):
        budget_line = "an unlimited budget (premium eligible)"
    else:
        per_person = parsed.get("budget", 0) or 0
        total = per_person * (parsed.get("travelers") or 1)
        budget_line = ("a budget of Rs %d per person, Rs %d for the whole party"
                       % (per_person, total))
        budget_line += (
                ". The Rs %d total is a real ceiling: do not exceed it. Spend it "
                "well - BUDGET should take the cheapest sensible transport and "
                "room, BALANCED a practical mix, PREMIUM the best available option for this route, and aim "
                "for roughly %d%%-%d%% of the total by choosing the highest-value "
                "options you can actually afford. For Coimbatore->Chennai style trips, "
                "realistic totals are ~Rs 30,000-50,000 per person for value and up to "
                "Rs 5,00,000 per person for premium justifications; scale meaningfully "
                "without inventing prices. Use ONLY the prices present in "
                "the inventory below. If, and only if, every option on this route "
                "genuinely costs far less than the budget, say so in the "
                "reasoning - never pad the itinerary or invent cost to use it up."
                % (total, int(_BUDGET_TARGET_LOW * 100), int(_BUDGET_TARGET_HIGH * 100)))
    return_line = ("ROUND TRIP: YES — the traveller returns to the origin on the "
                   "last day (the return transport is arranged separately); plan "
                   "the final day around that departure."
                   if parsed.get("returnTrip")
                   else "ROUND TRIP: NO — one-way trip; the last day ends at the "
                        "destination with the transfer home.")
    premium_line = (", ".join(parsed.get("premiumServices") or [])
                    or "none selected")
    premium_block = _premium_directives(parsed.get("premiumServices"))
    style_line = parsed.get("travelStyle") or "BALANCED"
    mode_line = parsed.get("transportType") or "any mode"
    food_line = parsed.get("foodPreference") or "no specific food preference"
    spot_pref = ", ".join(str(s) for s in (parsed.get("prioritizedSpotIds") or [])
                          ) or "none — choose the best-fitting spots"
    
    # Include clarifications if provided
    clarification_lines = []
    if clarifications:
        for key, value in clarifications.items():
            if value:
                clarification_lines.append("%s: %s" % (key, value))
    
    clar_text = "\n".join(["Clarification answers (follow these):"] + clarification_lines) if clarification_lines else ""
    if clar_text:
        clar_text = clar_text + "\n\n"
    
    return (
        "Design the trip itinerary entirely from the available inventory below. "
        "Exactly 3 different plans must be returned — one for each style: "
        "BUDGET (best value/lowest cost), BALANCED (mix of cost and comfort), "
        "PREMIUM (best comfort/experience regardless of price).\n\n"
        "Trip: %s -> %s | %d day(s), %d traveller(s) | %s.\n"
        "Starting point: %s.\n"
        "Preferred travel style: %s | preferred transport mode: %s | "
        "food preference: %s | premium services opted in: %s.\n"
        "%s\n"
        "%s\n"
        "Traveller-preferred spot ids (prioritise ALL of these in every plan): %s.\n"
        "Traveller preferences (IMPORTANT — follow them):\n\"%s\"\n\n"
        % (parsed.get("origin", ""), parsed.get("destination", ""),
           parsed.get("durationDays", 1), parsed.get("travelers", 1),
           budget_line, parsed.get("startLocation") or parsed.get("origin", ""),
           style_line, mode_line, food_line, premium_line,
           premium_block, return_line, spot_pref,
           parsed.get("preferences", ""))
        + clar_text
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
           "Include EVERY traveller-preferred spot listed above, and fill the rest of "
           "the itinerary with additional fitting spots from the inventory as the trip "
           "length allows. Assign activities across the trip days in a sensible order "
           "(arrival-day activities in the afternoon, departures on the last day). "
           "Choose at most 3 food items so the day can cover breakfast, lunch and "
           "dinner."))


_SYSTEM = (
    "You are TripMind's AI itinerary generator. You design complete travel plans "
    "for the requested origin -> destination route using ONLY the inventory and "
    "ids provided. Rules: 1) never invent resources, ids, prices, timings or "
    "names; 2) every id you return must appear in the inventory; 3) return exactly "
    "one JSON object, no markdown, no commentary; 4) choose the transport that "
    "best fits the traveller's preferences and the plan style (BUDGET prefers "
    "sleeper buses and sleeper trains; PREMIUM prefers Air-conditioned "
    "flights/trains); 5) always include a sensible hotel (or none only if the "
    "trip is under 2 days); 6) honour the ROUND TRIP instruction by planning the "
    "last day around the departure back home. Prefer tours that match the stated "
    "preferences.")

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


def _salvage_plans(raw):
    """Recover the complete plan objects from a truncated LLM reply.

    Reasoning models can spend their whole token budget before the JSON even
    starts, which cuts the reply mid-object. Every fully written plan is still
    real model output, so we keep those and ignore the half-written one instead
    of failing the whole request.
    """
    found, stack, in_str, esc = [], [], False, False
    for i, ch in enumerate(raw or ""):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            chunk = raw[stack.pop():i + 1]
            if '"style"' in chunk and '"transportId"' in chunk:
                try:
                    obj = json.loads(chunk)
                except Exception:
                    obj = None
                if isinstance(obj, dict) and obj.get("style") and obj.get("transportId"):
                    found.append(obj)
    return found


def _parse_response(raw):
    clean = _clean_json(raw)
    if not clean:
        raise AIPlanError("AI returned non-JSON output.")
    try:
        data = json.loads(clean)
    except (ValueError, TypeError) as e:
        salvaged = _salvage_plans(clean)
        if salvaged:
            print("[TripMind AI] LLM reply was cut off (%s); recovered %d complete "
                  "plan(s) and ignored the partial one." % (e, len(salvaged)))
            return salvaged
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
                    "provider": hotel.get("provider") or "",
                    "images": hotel.get("images") or [],
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
            "images": s.get("images") or [],
            "rating": s.get("popularity") or 4.0,
            "category": s.get("category") or "",
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
    for fid in (food_ids or [])[:3]:
        f = foods.get(str(fid))
        if not f:
            continue
        entry = dict(f)
        entry.setdefault("pricePerPerson", _cost_f(f.get("pricePerNight") or f.get("price") or 0))
        entry.setdefault("bookableId", None)
        foods_sel.append(entry)

    return_leg = _pick_return_leg(parsed, db_data) if parsed.get("returnTrip") else None

    route_km = None
    if (leg and leg.get("type") in ("CAB", "AUTO")) or \
            (return_leg and return_leg.get("type") in ("CAB", "AUTO")):
        try:
            from services.maps_distance import route_distance_km
            route_km = route_distance_km(parsed.get("origin"), parsed.get("destination"),
                                         label="corridor")
        except Exception:
            route_km = None

    transfers = _compute_transfers(parsed, leg, hotel, db_data.get("cabs") or [],
                                   return_leg=return_leg)

    decision = _arrive_decision(parsed, leg, hotel, activities)
    (daily_plan, total_cost, breakdown) = _ai_daily(parsed, leg, hotel, activities,
                                                    foods_sel, decision=decision,
                                                    distance_km=route_km,
                                                    transfers=transfers,
                                                    return_leg=return_leg)

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
        "returnTransport": return_leg,
        "hotel": hotel,
        "arrivalDecision": decision.get("mode"),
        "transports": [x for x in (leg, return_leg) if x],
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


def _leg_ride_minutes(leg, distance_km=None):
    """Ride length for a transport leg, in minutes.

    Prefer the operator's published schedule (boarding -> dropping). Fall back
    to a distance/speed estimate, then to the learned default. This is what
    keeps a Coimbatore->Chennai bus from being shown as a 90-minute hop.
    """
    try:
        dep = parse_datetime("2026-01-01", leg.get("boardingTime") or leg.get("departureTime") or "06:00")
        if leg.get("boardingDay") is not None:
            dep += timedelta(days=int(leg.get("boardingDay") or 0))
        arr_s = leg.get("droppingTime") or leg.get("arrivalTime")
        if arr_s:
            arr = parse_datetime("2026-01-01", arr_s)
            if leg.get("droppingDay") is not None:
                arr += timedelta(days=int(leg.get("droppingDay") or 0))
            mins = int((arr - dep).total_seconds() // 60)
            if mins > 0:
                return mins
    except Exception:
        pass
    if distance_km:
        speeds = {"TRAIN": 55.0, "BUS": 45.0, "FLIGHT": 600.0, "CAB": 50.0, "AUTO": 28.0}
        kmph = speeds.get(str(leg.get("type") or "").upper(), 45.0)
        if kmph > 0:
            return max(20, int(round(float(distance_km) / kmph * 60)))
    return int(learned_duration_or_default(leg.get("type"), 90))


def _arrival_time_ai(leg, distance_km=None):
    try:
        dep = parse_datetime("2026-01-01", leg.get("boardingTime") or leg.get("departureTime") or "06:00")
        if leg.get("boardingDay") is not None:
            dep += timedelta(days=int(leg.get("boardingDay") or 0))
        ride = _leg_ride_minutes(leg, distance_km)
        return dep + timedelta(minutes=ride)
    except Exception:
        return datetime.utcnow() + timedelta(hours=3)


def _ai_daily(request, leg, hotel, activities, foods, decision=None, distance_km=None,
              transfers=None, return_leg=None):
    start = request.get("startDate")
    try:
        if isinstance(start, str):
            start = parse_datetime(start.split("T")[0], "00:00")
    except Exception:
        start = None
    if not isinstance(start, datetime):
        start = datetime.utcnow()
    days = request.get("durationDays")
    if not days:
        end = request.get("endDate")
        try:
            if isinstance(end, str):
                end = parse_datetime(end.split("T")[0], "00:00")
            days = max(1, (end - start).days + 1) if isinstance(end, datetime) else 1
        except Exception:
            days = 1
    travelers = request.get("travelers", 1)
    transfer_min = int(learned_duration_or_default("TRANSFER", 90))
    food_min = int(learned_duration_or_default("FOOD", 60))
    act_min = int(learned_duration_or_default("ACTIVITY", 180))
    hotel_min = int(learned_duration_or_default("HOTEL", 60))

    if decision is None:
        decision = {"mode": "HOTEL_FIRST", "reason": ""}

    act_list = [a for a in activities if not (a.get("title") or "").startswith("Guided")]
    guided = next((x for x in activities if (x.get("title") or "").startswith("Guided")), None)

    transfers = transfers or {}

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
                "provider": "TripMind", "location": a.get("location", ""),
                "cost": _cost(a.get("tourCost")),
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
            ride = _leg_ride_minutes(leg, distance_km)
            arr = dep + timedelta(minutes=ride)
            leg_fare = _cost(_fare(leg, distance_km))
            breakdown["transport"] += leg_fare * travelers
            home_cost, home_err = _transfer_cost(transfers.get("home_to_boarding"), travelers)
            stay_cost, stay_err = _transfer_cost(transfers.get("arrival_to_stay"), travelers)
            breakdown["transport"] += (home_cost + stay_cost) * travelers
            home_item = {"type": "TRANSFER", "title": "Home to boarding point",
                         "provider": "Cab", "cost": home_cost,
                         "startTime": (dep - timedelta(minutes=90)).isoformat(),
                         "endTime": dep.isoformat()}
            if transfers.get("home_to_boarding") and transfers["home_to_boarding"].get("distanceKm"):
                home_item["distanceKm"] = round(transfers["home_to_boarding"]["distanceKm"], 2)
            if home_err:
                home_item["fareError"] = home_err
            stay_item = {"type": "TRANSFER", "title": "Arrival to stay", "provider": "Cab",
                         "cost": stay_cost,
                         "startTime": (arr + timedelta(minutes=20)).isoformat(),
                         "endTime": (arr + timedelta(minutes=20 + transfer_min)).isoformat()}
            if transfers.get("arrival_to_stay") and transfers["arrival_to_stay"].get("distanceKm"):
                stay_item["distanceKm"] = round(transfers["arrival_to_stay"]["distanceKm"], 2)
            if stay_err:
                stay_item["fareError"] = stay_err
            items = add([
                home_item,
                {"type": leg.get("type", "TRANSPORT"),
                 "title": "%s · %s" % (leg.get("type"), leg.get("serviceName", "")),
                 "provider": leg.get("provider") or leg.get("serviceName", ""),
                 "operator": leg.get("serviceName", ""),
                 "images": leg.get("images") or [],
                 "vehicle": _vehicle_label(leg), "cost": leg_fare,
                 "startTime": dep.isoformat(), "endTime": arr.isoformat(),
                 "distanceKm": distance_km, "bookableId": "transport:%s" % leg["_id"]},
                stay_item,
            ])
            slot = item_after(items)

        # The hotel block is gated on the arrival decision, but DIRECT_SPOT only
        # means "go to the first activity straight off the train". It does not
        # mean the passenger is not staying at the hotel: the room rate is
        # already counted in breakdown["hotel"] and therefore in totalCost, so
        # suppressing the item produced an itinerary that charged for N nights
        # while showing no hotel at all. The stay is real either way, so the
        # item is emitted unconditionally when a hotel was selected.
        if hotel:
            # A stay of N days means N-1 nights. Charging the room rate once
            # (on day 1 only) under-counted the hotel by the remaining nights,
            # which is what made whole itineraries look far cheaper than they are.
            nights = max(1, int(days) - 1)
            nightly = _cost(hotel.get("pricePerNight"))
            breakdown["hotel"] += nightly * travelers * nights
            if day == 1:
                items.extend(add([
                    {"type": "HOTEL", "title": "Check-in · %s" % hotel.get("name"),
                     "provider": hotel.get("provider") or hotel.get("name"),
                     "operator": hotel.get("name"),
                     "rating": hotel.get("rating"), "stars": hotel.get("stars"),
                     "images": hotel.get("images") or [],
                     "cost": nightly,
                     "nightLabel": "Night 1 of %d" % nights,
                     "startTime": slot.isoformat(),
                     "endTime": (slot + timedelta(minutes=hotel_min)).isoformat(),
                     "bookableId": "hotel:%s:%s" % (hotel.get("id"), hotel.get("roomTypeId"))},
                ]))
                slot = item_after(items)
            elif day <= nights:
                # Each later night is its own payable item, so the timeline and
                # the ledger agree on how many room-nights the trip actually uses.
                items.extend(add([
                    {"type": "HOTEL", "title": "Stay · %s" % hotel.get("name"),
                     "provider": hotel.get("provider") or hotel.get("name"),
                     "operator": hotel.get("name"),
                     "rating": hotel.get("rating"), "stars": hotel.get("stars"),
                     "images": hotel.get("images") or [],
                     "cost": nightly,
                     "nightLabel": "Night %d of %d" % (day, nights),
                     "startTime": slot.isoformat(),
                     "endTime": (slot + timedelta(minutes=hotel_min)).isoformat(),
                     "bookableId": "hotel:%s:%s" % (hotel.get("id"), hotel.get("roomTypeId"))},
                ]))
                slot = item_after(items)

        for a in per_day[day - 1]:
            breakdown["activities"] += _cost(a.get("price")) * travelers
            items.extend(add([
                {"type": "ACTIVITY", "title": a["title"], "provider": "TripMind",
                 "location": a.get("location", ""),
                 "images": a.get("images") or [],
                 "rating": a.get("rating"), "category": a.get("category") or "",
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
                 "provider": "TripMind", "location": guided.get("location", ""),
                 "cost": _cost(guided.get("price")),
                 "startTime": gslot.isoformat(),
                 "endTime": (gslot + timedelta(minutes=act_min)).isoformat(),
                 "bookableId": "guide:%s" % guided.get("guideId") if guided.get("guideId") else None},
            ]))

        if foods and (day > 1 or not per_day[0]):
            # Place meals at the real meal windows that are still ahead of the
            # day's clock. A plan that only reaches the city after lunch no
            # longer gets a "Breakfast" stamped on a 15:00 item: the label and
            # the time always agree. Each meal uses a distinct real food item
            # from the selected inventory - no invented menu.
            #
            # Anchor the day's clock to the latest item that actually belongs to
            # this calendar day rather than ``slot``: item_after() defaults to a
            # future "now", which would otherwise drag meals to today+2h on a
            # trip dated in the past.
            day_start = None
            day_end = None
            for it in items:
                try:
                    start = datetime.fromisoformat(it["startTime"]) if it.get("startTime") else None
                    if start is None or start.date() != d.date():
                        continue
                    end = datetime.fromisoformat(it["endTime"]) if it.get("endTime") else start
                    if day_start is None or start < day_start:
                        day_start = start
                    if day_end is None or end > day_end:
                        day_end = end
                except (ValueError, TypeError):
                    continue
            first_start = day_start or d.replace(hour=9, minute=0)
            cursor = day_end or d.replace(hour=8, minute=30)
            fi = 0
            for hh, mm, label in _MEAL_WINDOWS:
                if fi >= len(foods):
                    break
                meal_at = d.replace(hour=hh, minute=mm)
                if label == "Breakfast":
                    # Breakfast belongs before the first thing on the day, or,
                    # if the day is already clear, at the end of it.
                    if not (meal_at <= first_start or meal_at >= cursor):
                        continue
                elif meal_at < cursor:
                    continue
                f = foods[fi]
                fi += 1
                items.extend(add([
                    {"type": "FOOD",
                     "title": "%s · %s" % (label, _name(f.get("name"), "Local cafe")),
                     "provider": f.get("restaurantProvider") or f.get("name") or "",
                     "restaurant": f.get("restaurantName") or f.get("name") or "",
                     "images": f.get("restaurantImages") or [],
                     "rating": f.get("restaurantRating"),
                     "cost": _cost(f.get("pricePerPerson")),
                     "bookableId": f.get("bookableId") or None,
                     "startTime": meal_at.isoformat(),
                     "endTime": (meal_at + timedelta(minutes=food_min)).isoformat()},
                ]))
                cursor = max(cursor, meal_at + timedelta(minutes=food_min))
            if fi == 0:
                # Nothing landed in a window (e.g. a very late arrival): keep one
                # honest meal, labelled for the hour it actually happens.
                f = foods[0]
                items.extend(add([
                    {"type": "FOOD",
                     "title": "%s · %s" % (_meal_label(cursor.hour),
                                            _name(f.get("name"), "Local cafe")),
                     "provider": f.get("restaurantProvider") or f.get("name") or "",
                     "restaurant": f.get("restaurantName") or f.get("name") or "",
                     "images": f.get("restaurantImages") or [],
                     "rating": f.get("restaurantRating"),
                     "cost": _cost(f.get("pricePerPerson")),
                     "bookableId": f.get("bookableId") or None,
                     "startTime": cursor.isoformat(),
                     "endTime": (cursor + timedelta(minutes=food_min)).isoformat()},
                ]))
            slot = item_after(items)

        if day == days and return_leg:
            # Round trip: stay -> return boarding -> transport home -> arrival
            # -> home. Every fare comes from real distance/inventory data.
            r_time = str(return_leg.get("boardingTime") or "18:00")
            try:
                hh, mm = (r_time.split("T")[-1])[:5].split(":")
                rdep = d.replace(hour=int(hh), minute=int(mm))
            except Exception:
                rdep = d.replace(hour=18, minute=0)
            rride = _leg_ride_minutes(return_leg, distance_km)
            rarr = rdep + timedelta(minutes=rride)
            r_fare = _cost(_fare(return_leg, distance_km))
            breakdown["transport"] += r_fare * travelers
            s2b_cost, s2b_err = _transfer_cost(transfers.get("stay_to_return_boarding"),
                                               travelers)
            a2h_cost, a2h_err = _transfer_cost(transfers.get("return_arrival_to_home"),
                                               travelers)
            breakdown["transport"] += (s2b_cost + a2h_cost) * travelers
            to_board = {"type": "TRANSFER", "title": "Stay to return boarding point",
                        "provider": "Cab", "cost": s2b_cost,
                        "startTime": (rdep - timedelta(minutes=90)).isoformat(),
                        "endTime": rdep.isoformat()}
            if transfers.get("stay_to_return_boarding") and \
                    transfers["stay_to_return_boarding"].get("distanceKm"):
                to_board["distanceKm"] = round(
                    transfers["stay_to_return_boarding"]["distanceKm"], 2)
            if s2b_err:
                to_board["fareError"] = s2b_err
            back_item = {"type": return_leg.get("type", "TRANSPORT"),
                         "title": "Return %s · %s" % (return_leg.get("type"),
                                                      return_leg.get("serviceName", "")),
                         "provider": return_leg.get("provider") or return_leg.get("serviceName", ""),
                         "operator": return_leg.get("serviceName", ""),
                         "images": return_leg.get("images") or [],
                         "vehicle": _vehicle_label(return_leg), "cost": r_fare,
                         "startTime": rdep.isoformat(), "endTime": rarr.isoformat(),
                         "distanceKm": distance_km,
                         "bookableId": "transport:%s" % return_leg["_id"]}
            home_item = {"type": "TRANSFER", "title": "Return arrival to home",
                         "provider": "Cab", "cost": a2h_cost,
                         "startTime": (rarr + timedelta(minutes=20)).isoformat(),
                         "endTime": (rarr + timedelta(minutes=20 + transfer_min)).isoformat()}
            if transfers.get("return_arrival_to_home") and \
                    transfers["return_arrival_to_home"].get("distanceKm"):
                home_item["distanceKm"] = round(
                    transfers["return_arrival_to_home"]["distanceKm"], 2)
            if a2h_err:
                home_item["fareError"] = a2h_err
            items.extend(add([to_board, back_item, home_item]))
        elif day == days:
            back_cost, back_err = _transfer_cost(transfers.get("return_home"), travelers)
            breakdown["transport"] += back_cost * travelers
            back_item = {"type": "TRANSFER", "title": "Return home transfer", "provider": "Cab",
                         "cost": back_cost,
                         "startTime": slot.isoformat(),
                         "endTime": (slot + timedelta(minutes=transfer_min)).isoformat()}
            if transfers.get("return_home") and transfers["return_home"].get("distanceKm"):
                back_item["distanceKm"] = round(transfers["return_home"]["distanceKm"], 2)
            if back_err:
                back_item["fareError"] = back_err
            items.extend(add([back_item]))

        daily.append({"day": day, "date": d.isoformat(), "items": items})

    return daily, round(total, 2), {k: round(v, 2) for k, v in breakdown.items()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _normalize_request(parsed):
    """Ensure the request dict always carries datetimes + durationDays, no
    matter how the caller serialised the trip (JSON strings vs datetimes)."""
    out = dict(parsed or {})
    def _as_dt(v, default):
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            try:
                return parse_datetime(v.split("T")[0], "00:00")
            except Exception:
                return default
        return default
    start = _as_dt(out.get("startDate"), datetime.utcnow())
    end = _as_dt(out.get("endDate"), start)
    out["startDate"] = start
    out["endDate"] = max(end, start)
    if not out.get("durationDays"):
        out["durationDays"] = max(1, (out["endDate"] - start).days + 1)
    if not out.get("travelStyle"):
        out["travelStyle"] = "BALANCED"
    if "returnTrip" not in out:
        out["returnTrip"] = False
    if not isinstance(out.get("premiumServices"), list):
        out["premiumServices"] = []
    return out


# --------------------------------------------------------------- budget fit
# A budget is a CONSTRAINT *and* an optimisation target. It used to be neither,
# and that is why a passenger who entered Rs 5,00,000 was shown a Rs 15,199
# itinerary: the budget was accepted, stored, echoed back as a utilisation
# percentage in the response - and then had no effect whatsoever on which plan
# was recommended.
#
# Two things caused that:
#
#   1. Ranking ignored the budget. `generate_ai_plans` sorted plans by
#      `optimizationScore` alone, and that score is derived from
#      `cost_score = 1 - _normalize(cost, 0, budget)` in `_scores`. Against a
#      large budget every affordable plan normalises to ~0.97 and the gradient
#      between them is a few hundredths, so the effective rule was "cheapest
#      wins" no matter what the passenger could actually afford.
#   2. The prompt gave the model a per-person figure with no total and no
#      target, so the three BUDGET/BALANCED/PREMIUM plans had nothing to
#      differentiate against.
#
# IMPORTANT: this only REORDERS plans that already exist and are already priced
# from real catalogue fares. It never invents, inflates or pads a cost to
# consume a budget. If every honest option for this corridor costs Rs 15k, the
# best-fitting plan still wins and `budgetFitDetail.note` says so explicitly
# instead of the system quietly pretending the trip has to cost more.
_BUDGET_TARGET_LOW = 0.70
_BUDGET_TARGET_HIGH = 0.95


def _budget_total(parsed):
    """Whole-trip budget in rupees, or None when the traveller set none.

    `budget` is stored per traveller (see the trip payload built in routes), so
    it has to be multiplied by the party size before it means anything.
    """
    if parsed.get("budgetUnlimited"):
        return None
    per_traveller = parsed.get("budget") or 0
    if per_traveller <= 0:
        return None
    try:
        return float(per_traveller) * float(parsed.get("travelers") or 1)
    except (TypeError, ValueError):
        return None


def _budget_fit(plan, budget_total):
    """How well a plan's real cost honours the budget. Returns (score, detail).

    Over-budget plans are never auto-selected: they stay visible so the
    traveller can see the upgrade, but ranking pushes them behind every
    affordable plan, which is what "do not exceed the budget unless the user
    explicitly confirms an additional amount" requires.
    """
    detail = {"budgetTotal": budget_total, "utilization": None,
              "overBudget": False, "inTargetBand": False,
              "estimatedCost": float(plan.get("totalCost") or 0)}

    if not budget_total or budget_total <= 0:
        return 1.0, detail

    cost = float(plan.get("totalCost") or 0)
    utilization = cost / budget_total
    detail["utilization"] = round(utilization, 4)

    if utilization > 1.0:
        detail["overBudget"] = True
        # Scaled so a mildly-over plan still beats a wildly-over one.
        return max(0.0, 1.0 - (utilization - 1.0)), detail

    if utilization >= _BUDGET_TARGET_LOW:
        detail["inTargetBand"] = True
        return 1.0, detail

    # Under-spending is not automatically a defect - a two-day bus trip really
    # can cost far less than the ceiling the traveller typed. But when a
    # better-quality plan exists *within* budget, prefer it, because the
    # traveller has told us they can spend up to `budget`. This only reorders
    # existing plans; it never creates one.
    return max(0.0, utilization / _BUDGET_TARGET_LOW), detail


def _budget_note(plan, detail):
    """Plain-English reason the budget did or did not shape the choice."""
    if detail.get("budgetTotal") is None:
        return "No budget was set, so plans are ranked on trip quality alone."
    cost = detail.get("estimatedCost") or 0
    total = detail["budgetTotal"]
    pct = (detail.get("utilization") or 0) * 100
    if detail.get("overBudget"):
        return ("This plan costs Rs %s against a budget of Rs %s (%.0f%% of it). "
                "It exceeds the budget, so it needs an explicit "
                "additional-amount confirmation before booking."
                % (_money(cost), _money(total), pct))
    if detail.get("inTargetBand"):
        return ("This plan uses %.0f%% of the Rs %s budget." % (pct, _money(total)))
    return ("Only Rs %s of the Rs %s budget is genuinely required for this route "
            "with the available transport, hotels and activities (%.0f%%). The "
            "trip has not been padded with invented costs to spend the rest."
            % (_money(cost), _money(total), pct))


def generate_ai_plans(parsed, db_data, clarifications=None, verbose=True):
    """Generate 3 AI plans (BUDGET/BALANCED/PREMIUM) exclusively via AI.

    Raises AIPlanError when the AI backend is unavailable or returns an
    unusable response, so the caller NEVER falls back to code-rule plans.
    """
    if not is_ai_available():
        raise AIPlanError("No AI provider is configured (set OLLAMA_API_KEY — "
                          "primary — or GEMINI_API_KEY / CEREBRAS_API_KEY / "
                          "OPENROUTER_API_KEY as fallbacks).")

    parsed = _normalize_request(parsed)

    brief = _catalogue_brief(db_data)
    if not brief["transports"] and not brief["spots"]:
        raise AIPlanError("No registered inventory available for this route.")

    prompt = _build_prompt(parsed, brief, clarifications)
    print("[TripMind AI] LLM request: %d chars prompt, waiting for provider ..."
          % len(prompt))
    t0 = time.time()
    raw = call_ai(prompt, _SYSTEM, max_tokens=6000, temperature=0.3)
    if not raw:
        raise AIPlanError("AI provider returned no content (see the "
                          "[TripMind AI] LLM lines above for the failing "
                          "provider and reason).")
    print("[TripMind AI] LLM response: %d chars in %.1fs: %s"
          % (len(raw), time.time() - t0, raw[:200].replace("\n", " ")))

    try:
        selections = _parse_response(raw)
    except AIPlanError as e:
        # A truncated reply is worth one strict retry; every other failure
        # (no inventory, unusable plan) stays a hard, honest error.
        if "malformed" not in str(e) and "non-JSON" not in str(e):
            raise
        print("[TripMind AI] Retrying once with a stricter JSON-only prompt (%s)" % e)
        t1 = time.time()
        raw2 = call_ai(
            prompt + "\n\nIMPORTANT: reply with the JSON object only. No prose, "
                      "no commentary, and keep activityOrder to the listed spot "
                      "ids only.", _SYSTEM, max_tokens=6000, temperature=0.1)
        if not raw2:
            raise AIPlanError("AI provider returned no content on the retry (see "
                              "the [TripMind AI] LLM lines above for the failing "
                              "provider and reason).")
        print("[TripMind AI] LLM retry response: %d chars in %.1fs"
              % (len(raw2), time.time() - t1))
        selections = _parse_response(raw2)
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
    budget_total = _budget_total(parsed)
    for p in plans:
        fit, detail = _budget_fit(p, budget_total)
        p["budgetFit"] = round(fit, 4)
        detail["note"] = _budget_note(p, detail)
        p["budgetFitDetail"] = detail

    def _rank(p):
        detail = p.get("budgetFitDetail") or {}
        # Affordable plans always outrank over-budget ones, whatever they score
        # on trip quality; among affordable plans the one that best honours the
        # budget wins, and trip quality breaks the remaining ties.
        return (0 if detail.get("overBudget") else 1,
                p.get("budgetFit") or 0.0,
                p.get("optimizationScore") or 0.0)

    plans.sort(key=_rank, reverse=True)
    for p in plans:
        p["costBreakdown"] = p.get("costBreakdown") or {
            "transport": 0.0, "hotel": 0.0, "activities": 0.0,
            "food": 0.0, "flights": 0.0}
    return plans