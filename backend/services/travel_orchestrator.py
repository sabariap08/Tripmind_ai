from datetime import datetime, timedelta
from copy import deepcopy
from services.mock_flight_service import search_flights
from services.mock_hotel_service import search_hotels
from services.mock_transport_service import search_transport, search_airport_transfer
from services.mock_activity_service import search_activities, search_food
from services.travel_optimizer import optimize_itinerary


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
    }


def generate_travel_plans(request_data):
    parsed = parse_trip_request(request_data)
    style = parsed["travelStyle"]

    flights = search_flights(parsed["origin"], parsed["destination"], parsed["startDate"], style, 5)
    hotels = search_hotels(parsed["destination"], parsed["startDate"], parsed["endDate"], style, 3)
    transports = search_transport(parsed["origin"], parsed["destination"], 3)
    activities = search_activities(parsed["destination"], 4)
    foods = search_food(parsed["destination"], parsed.get("foodPreference"), 2)

    plan_types = ["BUDGET", "BALANCED", "PREMIUM"]
    plans = []
    for pt in plan_types:
        plan = optimize_itinerary(flights, hotels, transports, activities, foods, parsed, pt)
        plans.append(plan)

    plans.sort(key=lambda p: p["optimizationScore"], reverse=True)

    selected_plan = plans[0]
    ai_explanation = _generate_ai_explanation(selected_plan, parsed)

    return {
        "selectedPlan": selected_plan,
        "plans": plans,
        "aiExplanation": ai_explanation,
        "parsedRequest": parsed,
    }


def simulate_flight_delay(plan, delay_minutes):
    affected_items = []
    for day in plan.get("dailyPlan", []):
        for item in day.get("items", []):
            if item["type"] == "FLIGHT":
                item["status"] = "DELAYED"
                affected_items.append({
                    "title": item["title"],
                    "originalTime": item["startTime"],
                    "delayMinutes": delay_minutes,
                    "newTime": (datetime.fromisoformat(item["startTime"]) + timedelta(minutes=delay_minutes)).isoformat(),
                })
            elif item["type"] in ["TRANSFER", "HOTEL", "ACTIVITY", "FOOD"]:
                if day["day"] == 1:
                    item["status"] = "AFFECTED"
                    affected_items.append({
                        "title": item["title"],
                        "reason": "Downstream impact from flight delay",
                    })
    return {
        "affectedItems": affected_items,
        "delayMinutes": delay_minutes,
        "severity": "LOW" if delay_minutes < 120 else ("MEDIUM" if delay_minutes < 240 else "HIGH"),
    }


def generate_replan(original_plan, delay_minutes, request_data):
    parsed = parse_trip_request(request_data)
    new_plan = deepcopy(original_plan)
    extra_cost = 0

    for day in new_plan.get("dailyPlan", []):
        for item in day.get("items", []):
            if item["type"] == "FLIGHT":
                dep = datetime.fromisoformat(item["startTime"])
                arr = datetime.fromisoformat(item["endTime"])
                item["startTime"] = (dep + timedelta(minutes=delay_minutes)).isoformat()
                item["endTime"] = (arr + timedelta(minutes=delay_minutes)).isoformat()
                item["status"] = "RESCHEDULED"
                if delay_minutes > 180:
                    extra_cost += int(delay_minutes / 60 * 500)
            elif item["type"] == "TRANSFER" and day["day"] == 1:
                st = datetime.fromisoformat(item["startTime"])
                et = datetime.fromisoformat(item["endTime"])
                item["startTime"] = (st + timedelta(minutes=delay_minutes)).isoformat()
                item["endTime"] = (et + timedelta(minutes=delay_minutes)).isoformat()
                item["status"] = "RESCHEDULED"
            elif item["type"] == "HOTEL" and day["day"] == 1:
                st = datetime.fromisoformat(item["startTime"])
                item["startTime"] = (st + timedelta(minutes=delay_minutes)).isoformat()
                item["status"] = "RESCHEDULED"

    new_plan["totalCost"] = new_plan.get("totalCost", 0) + extra_cost
    new_plan["reasoning"] = [
        f"Replanned due to {delay_minutes}-minute delay.",
        f"Additional cost: ₹{extra_cost:,}" if extra_cost else "No additional cost.",
        "All affected items have been rescheduled.",
    ]

    affected_items = []
    for day in new_plan.get("dailyPlan", []):
        for item in day.get("items", []):
            if item.get("status") == "RESCHEDULED":
                affected_items.append(item["title"])

    return {
        "revisedPlan": new_plan,
        "originalCost": original_plan.get("totalCost", 0),
        "revisedCost": new_plan["totalCost"],
        "additionalCost": extra_cost,
        "affectedItems": affected_items,
        "explanation": f"Flight delayed by {delay_minutes} minutes. All downstream items rescheduled. {'Additional charges of ₹' + str(extra_cost) + ' applied for rebooking.' if extra_cost else 'No additional charges.'}",
    }


def _generate_ai_explanation(plan, parsed):
    parts = []
    parts.append(f"Based on your {parsed['travelStyle'].lower()} travel preference for {parsed['destination']},")
    if plan.get("flight"):
        parts.append(f"I recommend flying with {plan['flight']['airline']} (₹{plan['flight']['price']:,})")
    if plan.get("hotel"):
        parts.append(f"and staying at {plan['hotel']['name']} ({plan['hotel']['stars']}★, ₹{plan['hotel']['pricePerNight']:,}/night)")
    parts.append(f"for your {parsed['durationDays']}-day trip.")
    parts.append(f"Total estimated cost: ₹{plan['totalCost']:,} out of your ₹{parsed['budget']:,} budget.")
    remaining = parsed['budget'] - plan['totalCost']
    if remaining > 0:
        parts.append(f"You'll have ₹{remaining:,} remaining for additional expenses.")
    return " ".join(parts)
