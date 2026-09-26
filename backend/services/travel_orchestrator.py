"""Travel plan orchestrator.

Plans are generated EXCLUSIVELY by the AI planner (services/ai_plan_builder):
the model composes every itinerary from the registered catalogue data
(transports, spots, tours, guides, hotels, food) that is present in the
database. The backend validates the model's resource ids and recomputes every
price from catalogue rows — the AI never invents inventory or numbers.

There is NO deterministic/code-rule plan generator, so planning always reflects
AI judgement. When no registered services exist for the requested corridor the
API returns an explicit empty state; when the AI backend is unavailable the API
returns an explicit AI-unavailable state. It never fabricates inventory.
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
        "preferences": (request_data.get("preferences") or "").strip(),
        # Round-trip toggle: when true the plan includes a real return leg
        # (destination -> origin) priced from catalogue inventory.
        "returnTrip": bool(request_data.get("returnTrip")),
        # Premium services the traveller opted into (multi-select).
        "premiumServices": [s for s in (request_data.get("premiumServices") or [])
                            if s in ("TRANSPORT", "HOTELS", "ACTIVITIES", "GUIDE")],
    }


def _ai_failure_hint(err):
    """An accurate next step for the traveller — never a misleading guess.

    A cut-off model reply is an output-length problem, not a credentials one, so
    it must not send the user off to check API keys that were never the cause."""
    text = str(err).lower()
    if "malformed" in text or "non-json" in text or "no usable plans" in text:
        return ("The model's reply was incomplete, so no complete plan could be "
                "read from it. This is a reply-length issue rather than a key "
                "problem - press Generate again; the planner already retries once "
                "with a stricter JSON-only prompt.")
    if "no ai provider" in text or "not configured" in text:
        return ("The AI provider is not configured on the server. Check the "
                "[TripMind AI] log lines above, then set OLLAMA_API_KEY in the "
                "server environment and try again.")
    return ("Check the [TripMind AI] log lines above for the failing provider and "
            "the exact reason, then try again.")


def generate_travel_plans(request_data, db_data=None):
    parsed = parse_trip_request(request_data)
    request_data = parsed

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

    # AI-ONLY generation: every plan is composed by the AI model. There is no
    # deterministic fallback path — if the AI backend is down the request fails
    # loudly instead of producing code-rule plans.
    from services.ai_plan_builder import AIPlanError, generate_ai_plans
    try:
        plans = generate_ai_plans(parsed, db_data)
    except AIPlanError as e:
        # Surface the real LLM cause in the server console — never silent.
        print("[TripMind AI] AI planner failed: %s" % e)
        return {
            "selectedPlan": None,
            "plans": [],
            "aiExplanation": (
                "The AI planner could not generate plans: %s %s"
                % (str(e).rstrip("."), _ai_failure_hint(e))
            ),
            "parsedRequest": parsed,
            "ml": {},
            "source": "ai_unavailable",
        }

    selected = plans[0] if plans else None
    ai = []
    ai.append(f"AI generated a {parsed['durationDays']}-day, {parsed['travelers']}-traveller "
              f"itinerary for {parsed['destination']} from live catalogue data "
              f"(transports, spots, guides, hotels).")
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
