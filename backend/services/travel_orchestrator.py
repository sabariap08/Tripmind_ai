"""Travel plan orchestrator.

Plans are built ONLY from registered catalogue data (transports, spots, tours,
guides, hotels) present in the database. When no registered services exist for
the requested corridor the API returns an explicit empty state — it never
fabricates inventory or falls back to hardcoded mock services.
"""
from datetime import datetime


def parse_trip_request(request_data):
    origin = request_data.get("origin", "")
    destination = request_data.get("destination", "")
    start_date = request_data.get("startDate")
    end_date = request_data.get("endDate")
    if isinstance(start_date, str):
        start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00")).replace(tzinfo=None)
    if isinstance(end_date, str):
        end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00")).replace(tzinfo=None)
    duration_days = max(1, (end_date - start_date).days + 1)
    return {
        "origin": origin,
        "destination": destination,
        "startDate": start_date,
        "endDate": end_date,
        "durationDays": duration_days,
        "travelers": request_data.get("travelers", 1),
        "budget": request_data.get("budget", 50000),
        "currency": request_data.get("currency", "INR"),
        "travelStyle": request_data.get("travelStyle", "BALANCED"),
        "foodPreference": request_data.get("foodPreference"),
        "transportType": request_data.get("transportType"),
        # User-chosen starting point (lat/lng/address) from the Google Maps picker.
        "startLocation": request_data.get("startLocation"),
        # Manual structured-planning inputs (NEW flow)
        "budgetUnlimited": bool(request_data.get("budgetUnlimited")) or request_data.get("budget") in (None, 0),
        "servicePreference": request_data.get("servicePreference"),
        "prioritizedSpotIds": request_data.get("prioritizedSpotIds") or [],
    }


def generate_travel_plans(request_data, db_data=None):
    parsed = parse_trip_request(request_data)

    if not db_data or not (db_data.get("transports") or db_data.get("spots")
                           or db_data.get("guides") or db_data.get("hotels")):
        return {
            "selectedPlan": None,
            "plans": [],
            "aiExplanation": (
                f"No registered travel services are available for "
                f"{parsed['origin'] or 'your origin'} → "
                f"{parsed['destination'] or 'your destination'} yet. "
                "To plan and book this trip, a transport provider (and optionally "
                "hotel/guide/tour operators) must first register services here."),
            "parsedRequest": parsed,
            "ml": {},
            "source": "empty",
        }

    return _generate_db_plans(parsed, db_data)


def _generate_db_plans(parsed, db_data):
    from services.trip_optimizer import build_db_plan
    plans = []
    for pt in ("BUDGET", "BALANCED", "PREMIUM"):
        plans.append(build_db_plan(parsed, db_data, pt))
    plans.sort(key=lambda p: p["optimizationScore"], reverse=True)
    selected = plans[0]
    ai = []
    ai.append(f"Optimized a {parsed['durationDays']}-day itinerary for {parsed['destination']} "
              f"using live catalogue data (transports, tourist spots, guides).")
    budget_note = ("with an unlimited budget (premium eligible)."
                   if parsed.get('budgetUnlimited')
                   else f"within ₹{parsed['budget']:,.0f} budget.")
    ai.append(f"Total estimated cost ₹{selected['totalCost']:,.0f} {budget_note}")
    return {
        "selectedPlan": selected,
        "plans": plans,
        "aiExplanation": " ".join(ai) or "AI plan generated.",
        "parsedRequest": parsed,
        "ml": _ml_predictions(parsed),
        "source": "db",
    }


def _ml_predictions(parsed):
    ml = {}
    try:
        from services.ml.injector import predict_delay, predict_trip_cost
        delay = predict_delay(parsed["origin"], parsed["destination"])
        if delay:
            ml["delayPrediction"] = delay
        cost = predict_trip_cost(parsed)
        if cost:
            ml["costPrediction"] = cost
    except Exception:
        pass
    return ml
