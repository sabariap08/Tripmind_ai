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


def generate_clarifying_questions(request_data, db_data=None):
    """Generate clarifying questions from the AI before plan generation.
    
    Returns a list of structured questions that the user must answer
    before the final plan is generated.
    """
    from services.ai_plan_builder import AIPlanError, call_ai, is_ai_available
    
    if not is_ai_available():
        # Return default questions if AI is not available
        return _default_clarifying_questions(request_data)
    
    parsed = parse_trip_request(request_data)
    
    # Build a prompt for generating clarifying questions
    prompt = _build_clarification_prompt(parsed, request_data)
    
    try:
        raw = call_ai(prompt, _CLARIFICATION_SYSTEM, max_tokens=2000, temperature=0.3)
        if not raw:
            return _default_clarifying_questions(request_data)
        
        # Parse the AI response as JSON
        import json
        try:
            questions = json.loads(raw)
            if isinstance(questions, dict) and "questions" in questions:
                return questions["questions"]
            elif isinstance(questions, list):
                return questions
        except json.JSONDecodeError:
            pass
        
        return _default_clarifying_questions(request_data)
    except Exception as e:
        print("[TripMind AI] Clarification generation failed: %s" % e)
        return _default_clarifying_questions(request_data)


def _default_clarifying_questions(request_data):
    """Fallback clarifying questions when AI is unavailable."""
    questions = []
    
    # Always ask about pace
    questions.append({
        "id": "pace",
        "type": "radio",
        "label": "What pace do you prefer for this trip?",
        "required": True,
        "options": [
            {"value": "relaxed", "label": "Relaxed — fewer activities, more downtime"},
            {"value": "balanced", "label": "Balanced — mix of activities and rest"},
            {"value": "packed", "label": "Packed — maximize every day"}
        ]
    })
    
    # Ask about transport preference if not specified
    if not request_data.get("transportType"):
        questions.append({
            "id": "transport_preference",
            "type": "radio",
            "label": "How do you prefer to travel between cities?",
            "required": True,
            "options": [
                {"value": "train", "label": "Train — scenic, comfortable"},
                {"value": "bus", "label": "Bus — economical, flexible"},
                {"value": "flight", "label": "Flight — fastest"},
                {"value": "cab", "label": "Private cab — door to door"},
                {"value": "mixed", "label": "AI decides based on route"}
            ]
        })
    
    # Ask about food preferences
    questions.append({
        "id": "food_style",
        "type": "checkbox",
        "label": "Any food preferences or restrictions?",
        "required": False,
        "options": [
            {"value": "vegetarian", "label": "Vegetarian only"},
            {"value": "vegan", "label": "Vegan"},
            {"value": "halal", "label": "Halal"},
            {"value": "no_spicy", "label": "No spicy food"},
            {"value": "local", "label": "Local specialties only"},
            {"value": "no_restrictions", "label": "No restrictions — I'll try anything"}
        ]
    })
    
    # Ask about activity types
    questions.append({
        "id": "activity_types",
        "type": "checkbox",
        "label": "What types of activities interest you?",
        "required": True,
        "options": [
            {"value": "heritage", "label": "Heritage sites, temples, museums"},
            {"value": "nature", "label": "Nature, parks, wildlife"},
            {"value": "adventure", "label": "Adventure, trekking, water sports"},
            {"value": "food", "label": "Food tours, cooking classes"},
            {"value": "shopping", "label": "Shopping, markets"},
            {"value": "wellness", "label": "Wellness, yoga, spa"},
            {"value": "photography", "label": "Photography spots"},
            {"value": "nightlife", "label": "Nightlife, bars, entertainment"}
        ]
    })
    
    # Ask about accommodation style
    questions.append({
        "id": "accommodation_style",
        "type": "radio",
        "label": "What type of accommodation do you prefer?",
        "required": True,
        "options": [
            {"value": "budget", "label": "Budget-friendly — hostels, guesthouses"},
            {"value": "mid", "label": "Mid-range — 3-star hotels, homestays"},
            {"value": "luxury", "label": "Luxury — 4-5 star hotels, resorts"},
            {"value": "mixed", "label": "Mix — AI decides per location"}
        ]
    })
    
    # Open text for special requests
    questions.append({
        "id": "special_requests",
        "type": "textarea",
        "label": "Any special requests, accessibility needs, or must-see places?",
        "required": False,
        "placeholder": "e.g., wheelchair accessible, traveling with infant, must visit specific temple..."
    })
    
    return questions


_CLARIFICATION_SYSTEM = """You are TripMind AI, a travel planning assistant. Your task is to generate clarifying questions that will help create a personalized travel itinerary.

Given the user's trip inputs, generate 4-6 structured questions that will resolve ambiguity and help create a better plan. Return ONLY a JSON array of questions.

Each question must have:
- "id": unique string identifier (snake_case)
- "type": "radio" | "checkbox" | "textarea" | "select"
- "label": human-readable question text
- "required": boolean
- "options": array of {"value": "...", "label": "..."} (for radio, checkbox, select)
- "placeholder": string (for textarea)
- "required": boolean

Focus on ambiguities in:
1. Trip pace (relaxed/balanced/packed)
2. Transport preferences between cities
3. Food restrictions/preferences
4. Activity interests
5. Accommodation style
6. Special needs/accessibility

Output ONLY the JSON array, no extra text."""


def generate_travel_plans(request_data, db_data=None, clarifications=None):
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
        plans = generate_ai_plans(parsed, db_data, clarifications)
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
