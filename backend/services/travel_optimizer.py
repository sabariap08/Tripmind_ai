import random
from datetime import datetime, timedelta


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


def _normalize(value, min_val, max_val):
    if max_val == min_val:
        return 0.5
    return max(0, min(1, (value - min_val) / (max_val - min_val)))


def _score_plan(flights, hotels, transports, activities, foods, budget, weights):
    cost_score = 1 - _normalize(sum(f["price"] for f in flights[:1]) + sum(h["totalPrice"] for h in hotels[:1]), 0, budget)
    avg_duration = sum(f.get("durationMinutes", 600) for f in flights[:1]) / max(1, len(flights[:1]))
    time_score = 1 - _normalize(avg_duration, 120, 1440)
    comfort_score = _normalize(
        sum(h.get("rating", 3) for h in hotels[:1]) / max(1, len(hotels[:1])) / 5.0, 0, 1
    )
    convenience_score = _normalize(len(transports) + len(activities), 1, 10)
    reliability_score = 0.8 + random.uniform(-0.1, 0.1)

    total = (
        weights["cost"] * cost_score +
        weights["time"] * time_score +
        weights["comfort"] * comfort_score +
        weights["convenience"] * convenience_score +
        weights["reliability"] * reliability_score
    )
    return {
        "costScore": round(cost_score, 3),
        "timeScore": round(time_score, 3),
        "comfortScore": round(comfort_score, 3),
        "convenienceScore": round(convenience_score, 3),
        "reliabilityScore": round(reliability_score, 3),
        "totalScore": round(total, 3),
    }


def _generate_daily_plan(flight, hotel, transports, activities, foods, request):
    days = request["durationDays"]
    daily_plan = []

    for day in range(1, days + 1):
        items = []
        day_date = request["startDate"] + timedelta(days=day - 1)

        if day == 1:
            items.append({
                "type": "TRANSFER", "title": "Home to Airport Transfer",
                "provider": transports[0]["type"] if transports else "Taxi",
                "cost": transports[0]["price"] if transports else 500,
                "startTime": day_date.replace(hour=6, minute=0).isoformat(),
                "endTime": day_date.replace(hour=7, minute=30).isoformat(),
            })
            items.append({
                "type": "FLIGHT", "title": f"Flight - {flight['airline']}",
                "provider": flight["airline"],
                "cost": flight["price"],
                "startTime": flight["departureTime"],
                "endTime": flight["arrivalTime"],
            })
            items.append({
                "type": "TRANSFER", "title": "Airport to Hotel Transfer",
                "provider": transports[0]["type"] if transports else "Taxi",
                "cost": int(transports[0]["price"] * 0.6) if transports else 300,
                "startTime": (datetime.fromisoformat(flight["arrivalTime"]) + timedelta(minutes=30)).isoformat(),
                "endTime": (datetime.fromisoformat(flight["arrivalTime"]) + timedelta(hours=1, minutes=30)).isoformat(),
            })
            items.append({
                "type": "HOTEL", "title": f"Check-in - {hotel['name']}",
                "provider": hotel["name"],
                "cost": hotel["pricePerNight"],
                "startTime": (datetime.fromisoformat(flight["arrivalTime"]) + timedelta(hours=2)).isoformat(),
                "endTime": (datetime.fromisoformat(flight["arrivalTime"]) + timedelta(hours=2, minutes=30)).isoformat(),
            })
        elif day == days:
            items.append({
                "type": "TRANSFER", "title": "Hotel to Airport Transfer",
                "provider": transports[0]["type"] if transports else "Taxi",
                "cost": int(transports[0]["price"] * 0.6) if transports else 300,
                "startTime": day_date.replace(hour=10, minute=0).isoformat(),
                "endTime": day_date.replace(hour=11, minute=30).isoformat(),
            })
        else:
            if foods and len(foods) > 0:
                items.append({
                    "type": "FOOD", "title": f"Breakfast - {foods[0]['name']}",
                    "provider": foods[0]["name"],
                    "cost": foods[0]["pricePerPerson"],
                    "startTime": day_date.replace(hour=8, minute=0).isoformat(),
                    "endTime": day_date.replace(hour=9, minute=0).isoformat(),
                })
            act_idx = (day - 2) % max(1, len(activities))
            if activities:
                items.append({
                    "type": "ACTIVITY", "title": activities[act_idx]["title"],
                    "provider": activities[act_idx].get("location", ""),
                    "cost": activities[act_idx]["price"],
                    "startTime": day_date.replace(hour=10, minute=0).isoformat(),
                    "endTime": day_date.replace(hour=13, minute=0).isoformat(),
                })
            if foods and len(foods) > 1:
                items.append({
                    "type": "FOOD", "title": f"Lunch - {foods[1]['name']}",
                    "provider": foods[1]["name"],
                    "cost": foods[1]["pricePerPerson"],
                    "startTime": day_date.replace(hour=13, minute=30).isoformat(),
                    "endTime": day_date.replace(hour=14, minute=30).isoformat(),
                })
            if activities and len(activities) > 1:
                act2_idx = (day - 1) % max(1, len(activities))
                items.append({
                    "type": "ACTIVITY", "title": activities[act2_idx]["title"],
                    "provider": activities[act2_idx].get("location", ""),
                    "cost": activities[act2_idx]["price"],
                    "startTime": day_date.replace(hour=15, minute=0).isoformat(),
                    "endTime": day_date.replace(hour=17, minute=0).isoformat(),
                })
            if foods and len(foods) > 0:
                items.append({
                    "type": "FOOD", "title": f"Dinner - {foods[0]['name']}",
                    "provider": foods[0]["name"],
                    "cost": foods[0]["pricePerPerson"],
                    "startTime": day_date.replace(hour=19, minute=0).isoformat(),
                    "endTime": day_date.replace(hour=20, minute=30).isoformat(),
                })

        daily_plan.append({"day": day, "date": day_date.isoformat(), "items": items})

    return daily_plan


def optimize_itinerary(flights, hotels, transports, activities, foods, request, style="BALANCED"):
    budget = request["budget"]
    allocation = BUDGET_ALLOCATION.get(style, BUDGET_ALLOCATION["BALANCED"])
    weights = STYLE_WEIGHTS.get(style, STYLE_WEIGHTS["BALANCED"])

    flight_budget = budget * allocation["flight"]
    hotel_budget = budget * allocation["hotel"]

    best_flight = next((f for f in flights if f["price"] <= flight_budget), flights[0] if flights else None)
    per_night_budget = hotel_budget / max(1, request["durationDays"])
    best_hotel = next((h for h in hotels if h["pricePerNight"] <= per_night_budget), hotels[0] if hotels else None)

    selected_transports = transports[:2] if transports else []
    selected_activities = activities[:4] if activities else []
    selected_foods = foods[:2] if foods else []

    total_cost = 0
    if best_flight:
        total_cost += best_flight["price"]
    if best_hotel:
        total_cost += best_hotel["totalPrice"]
    for t in selected_transports:
        total_cost += t["price"]
    for a in selected_activities:
        total_cost += a["price"]
    for f_item in selected_foods:
        total_cost += f_item["pricePerPerson"] * request["durationDays"]

    scores = _score_plan(
        [best_flight] if best_flight else [],
        [best_hotel] if best_hotel else [],
        selected_transports,
        selected_activities,
        selected_foods,
        budget,
        weights,
    )

    daily_plan = _generate_daily_plan(
        best_flight or (flights[0] if flights else {"airline": "TBA", "price": 0, "departureTime": "", "arrivalTime": ""}),
        best_hotel or (hotels[0] if hotels else {"name": "TBA", "totalPrice": 0, "pricePerNight": 0}),
        selected_transports,
        selected_activities,
        selected_foods,
        request,
    )

    cost_breakdown = {
        "flights": best_flight["price"] if best_flight else 0,
        "hotel": best_hotel["totalPrice"] if best_hotel else 0,
        "transport": sum(t["price"] for t in selected_transports),
        "activities": sum(a["price"] for a in selected_activities),
        "food": sum(f_item["pricePerPerson"] for f_item in selected_foods) * request["durationDays"],
    }

    reasoning = []
    if best_flight:
        reasoning.append(f"Selected {best_flight['airline']} flight at ₹{best_flight['price']:,} for optimal {style.lower()} balance.")
    if best_hotel:
        reasoning.append(f"Selected {best_hotel['name']} ({best_hotel['stars']}★) at ₹{best_hotel['pricePerNight']:,}/night.")
    reasoning.append(f"Plan targets {style.lower()} travel style with ₹{budget:,} budget.")
    remaining = budget - total_cost
    if remaining > 0:
        reasoning.append(f"₹{remaining:,} remaining for additional expenses.")

    return {
        "planType": style,
        "totalCost": total_cost,
        "comfortScore": scores["comfortScore"],
        "optimizationScore": scores["totalScore"],
        "flight": best_flight,
        "hotel": best_hotel,
        "transports": selected_transports,
        "activities": selected_activities,
        "foods": selected_foods,
        "dailyPlan": daily_plan,
        "costBreakdown": cost_breakdown,
        "travelTime": f"{best_flight.get('duration', 'N/A')}" if best_flight else "N/A",
        "days": request["durationDays"],
        "reasoning": reasoning,
        "scores": scores,
    }
