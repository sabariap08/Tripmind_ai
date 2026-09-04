import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify
from services.mongodb import get_collection, ensure_demo_user
from services.travel_orchestrator import (
    generate_travel_plans, generate_replan, simulate_flight_delay
)

trips_bp = Blueprint("trips", __name__)


@trips_bp.route("/api/trips", methods=["GET"])
def list_trips():
    user_id = ensure_demo_user()
    trips = list(get_collection("trips").find(
        {"userId": user_id},
        sort=[("createdAt", -1)]
    ))
    for t in trips:
        t["_id"] = str(t["_id"])
        if "itineraries" in t:
            for it in t["itineraries"]:
                if "_id" in it:
                    it["_id"] = str(it["_id"])
    return jsonify(trips)


@trips_bp.route("/api/trips", methods=["POST"])
def create_trip():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    required = ["origin", "destination", "startDate", "endDate", "budget"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    if data["budget"] < 1000:
        return jsonify({"error": "Budget must be at least 1000"}), 400

    travelers = data.get("travelers", 1)
    if travelers < 1 or travelers > 20:
        return jsonify({"error": "Travelers must be between 1 and 20"}), 400

    user_id = ensure_demo_user()
    trip_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    trip = {
        "_id": trip_id,
        "userId": user_id,
        "origin": data["origin"],
        "destination": data["destination"],
        "startDate": data["startDate"],
        "endDate": data["endDate"],
        "travelers": travelers,
        "budget": data["budget"],
        "currency": data.get("currency", "INR"),
        "travelStyle": data.get("travelStyle", "BALANCED"),
        "status": "DRAFT",
        "totalEstimatedCost": None,
        "createdAt": now,
        "updatedAt": now,
        "itineraries": [],
        "bookings": [],
        "events": [],
        "recommendations": [],
    }

    get_collection("trips").insert_one(trip)
    return jsonify({"tripId": trip_id, "message": "Trip created"}), 201


@trips_bp.route("/api/trips/<trip_id>", methods=["GET"])
def get_trip(trip_id):
    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return jsonify({"error": "Trip not found"}), 404
    trip["_id"] = str(trip["_id"])
    return jsonify(trip)


@trips_bp.route("/api/trips/<trip_id>/generate", methods=["POST"])
def generate_plans(trip_id):
    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return jsonify({"error": "Trip not found"}), 404

    request_data = {
        "origin": trip["origin"],
        "destination": trip["destination"],
        "startDate": trip["startDate"],
        "endDate": trip["endDate"],
        "travelers": trip["travelers"],
        "budget": trip["budget"],
        "currency": trip.get("currency", "INR"),
        "travelStyle": trip.get("travelStyle", "BALANCED"),
        "foodPreference": trip.get("foodPreference"),
    }

    result = generate_travel_plans(request_data)
    selected = result["selectedPlan"]

    now = datetime.utcnow().isoformat()

    itineraries = []
    for i, plan in enumerate(result["plans"]):
        itin_id = str(uuid.uuid4())
        status = "SELECTED" if i == 0 else "AVAILABLE"
        items = []
        for day_plan in plan.get("dailyPlan", []):
            for j, item in enumerate(day_plan.get("items", [])):
                items.append({
                    "_id": str(uuid.uuid4()),
                    "type": item["type"],
                    "title": item["title"],
                    "provider": item.get("provider", ""),
                    "location": item.get("location", ""),
                    "startTime": item.get("startTime"),
                    "endTime": item.get("endTime"),
                    "cost": item.get("cost", 0),
                    "currency": "INR",
                    "status": item.get("status", "PLANNED"),
                    "day": day_plan["day"],
                    "sortOrder": j,
                    "metadata": None,
                })
        itineraries.append({
            "_id": itin_id,
            "tripId": trip_id,
            "version": 1,
            "status": status,
            "totalCost": plan["totalCost"],
            "generatedBy": "AI",
            "planType": plan["planType"],
            "reasoning": plan.get("reasoning", []),
            "createdAt": now,
            "items": items,
            "optimizationScore": plan.get("optimizationScore", 0),
            "comfortScore": plan.get("comfortScore", 0),
            "travelTime": plan.get("travelTime", "N/A"),
        })

    recommendation = {
        "_id": str(uuid.uuid4()),
        "tripId": trip_id,
        "category": "FLIGHT",
        "recommendation": f"Book {selected['flight']['airline']} flight" if selected.get("flight") else "No flight selected",
        "reasoning": result["aiExplanation"],
        "estimatedCost": selected.get("flight", {}).get("price"),
        "confidence": selected.get("optimizationScore", 0.8),
        "createdAt": now,
    }

    get_collection("trips").update_one(
        {"_id": trip_id},
        {"$set": {
            "totalEstimatedCost": selected["totalCost"],
            "status": "PLANNED",
            "updatedAt": now,
            "itineraries": itineraries,
            "recommendations": [recommendation],
        }}
    )

    return jsonify({
        "selectedPlan": selected,
        "plans": result["plans"],
        "aiExplanation": result["aiExplanation"],
    })


@trips_bp.route("/api/trips/<trip_id>/book", methods=["POST"])
def book_trip(trip_id):
    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return jsonify({"error": "Trip not found"}), 404

    selected_itin = None
    for itin in trip.get("itineraries", []):
        if itin.get("status") == "SELECTED":
            selected_itin = itin
            break

    if not selected_itin:
        return jsonify({"error": "No selected itinerary found"}), 400

    bookings = []
    total = 0
    now = datetime.utcnow().isoformat()

    for item in selected_itin.get("items", []):
        if item["type"] in ["FLIGHT", "HOTEL"]:
            ref_type = "FLT" if item["type"] == "FLIGHT" else "HOT"
            ref = f"TM-{ref_type}-{uuid.uuid4().int % 100000:05d}"
            bookings.append({
                "_id": str(uuid.uuid4()),
                "tripId": trip_id,
                "provider": item.get("provider", ""),
                "bookingReference": ref,
                "status": "CONFIRMED",
                "price": item.get("cost", 0),
                "currency": "INR",
                "bookedAt": now,
            })
            total += item.get("cost", 0)

    get_collection("trips").update_one(
        {"_id": trip_id},
        {"$set": {
            "status": "BOOKED",
            "updatedAt": now,
            "bookings": bookings,
        }}
    )

    return jsonify({"bookings": bookings, "totalCost": total})


@trips_bp.route("/api/trips/<trip_id>/events", methods=["GET"])
def get_events(trip_id):
    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return jsonify({"error": "Trip not found"}), 404
    events = trip.get("events", [])
    events.sort(key=lambda e: e.get("occurredAt", ""), reverse=True)
    return jsonify(events)


@trips_bp.route("/api/trips/<trip_id>/itinerary", methods=["GET"])
def get_itinerary(trip_id):
    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return jsonify({"error": "Trip not found"}), 404
    itineraries = trip.get("itineraries", [])
    for itin in itineraries:
        if "items" in itin:
            itin["items"].sort(key=lambda x: (x.get("day", 0), x.get("sortOrder", 0)))
    itineraries.sort(key=lambda x: x.get("version", 0), reverse=True)
    return jsonify(itineraries)


@trips_bp.route("/api/trips/<trip_id>/simulate-delay", methods=["POST"])
def simulate_delay(trip_id):
    data = request.get_json()
    delay_minutes = data.get("delayMinutes", 60)

    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return jsonify({"error": "Trip not found"}), 404

    selected_itin = None
    for itin in trip.get("itineraries", []):
        if itin.get("status") == "SELECTED":
            selected_itin = itin
            break

    if not selected_itin:
        return jsonify({"error": "No selected itinerary"}), 400

    severity = "LOW" if delay_minutes < 120 else ("MEDIUM" if delay_minutes < 240 else "HIGH")
    now = datetime.utcnow().isoformat()

    event = {
        "_id": str(uuid.uuid4()),
        "tripId": trip_id,
        "type": "FLIGHT_DELAY",
        "title": f"Flight Delay - {delay_minutes} minutes",
        "description": f"Simulated flight delay of {delay_minutes} minutes",
        "severity": severity,
        "occurredAt": now,
        "resolvedAt": None,
    }

    get_collection("trips").update_one(
        {"_id": trip_id},
        {"$set": {
            "status": "REPLANNING",
            "updatedAt": now,
        },
        "$push": {"events": event}}
    )

    return jsonify({"event": event, "severity": severity})


@trips_bp.route("/api/trips/<trip_id>/replan", methods=["POST"])
def replan_trip(trip_id):
    data = request.get_json()
    delay_minutes = data.get("delayMinutes", 60)

    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return jsonify({"error": "Trip not found"}), 404

    selected_itin = None
    for itin in trip.get("itineraries", []):
        if itin.get("status") == "SELECTED":
            selected_itin = itin
            break

    if not selected_itin:
        return jsonify({"error": "No selected itinerary"}), 400

    plan = {
        "totalCost": selected_itin.get("totalCost", 0),
        "dailyPlan": _extract_daily_plan(selected_itin),
    }

    request_data = {
        "origin": trip["origin"],
        "destination": trip["destination"],
        "startDate": trip["startDate"],
        "endDate": trip["endDate"],
        "travelers": trip["travelers"],
        "budget": trip["budget"],
        "travelStyle": trip.get("travelStyle", "BALANCED"),
    }

    result = generate_replan(plan, delay_minutes, request_data)
    now = datetime.utcnow().isoformat()

    version = max((it.get("version", 0) for it in trip.get("itineraries", [])), default=0) + 1

    new_items = []
    for day_plan in result["revisedPlan"].get("dailyPlan", []):
        for j, item in enumerate(day_plan.get("items", [])):
            new_items.append({
                "_id": str(uuid.uuid4()),
                "type": item["type"],
                "title": item["title"],
                "provider": item.get("provider", ""),
                "location": item.get("location", ""),
                "startTime": item.get("startTime"),
                "endTime": item.get("endTime"),
                "cost": item.get("cost", 0),
                "currency": "INR",
                "status": item.get("status", "PLANNED"),
                "day": day_plan["day"],
                "sortOrder": j,
                "metadata": None,
            })

    new_itin = {
        "_id": str(uuid.uuid4()),
        "tripId": trip_id,
        "version": version,
        "status": "SELECTED",
        "totalCost": result["revisedPlan"]["totalCost"],
        "generatedBy": "AI",
        "planType": selected_itin.get("planType", "BALANCED"),
        "reasoning": result["revisedPlan"].get("reasoning", []),
        "createdAt": now,
        "items": new_items,
        "optimizationScore": selected_itin.get("optimizationScore", 0),
        "comfortScore": selected_itin.get("comfortScore", 0),
        "travelTime": selected_itin.get("travelTime", "N/A"),
    }

    updated_itineraries = []
    for itin in trip.get("itineraries", []):
        if itin.get("status") == "SELECTED":
            itin["status"] = "SUPERSEDED"
        updated_itineraries.append(itin)
    updated_itineraries.append(new_itin)

    replan_rec = {
        "_id": str(uuid.uuid4()),
        "tripId": trip_id,
        "category": "REPLANNING",
        "recommendation": f"Replanned after {delay_minutes}-minute delay",
        "reasoning": result["explanation"],
        "estimatedCost": result["additionalCost"],
        "confidence": 0.85,
        "createdAt": now,
    }

    get_collection("trips").update_one(
        {"_id": trip_id},
        {"$set": {
            "status": "PLANNED",
            "totalEstimatedCost": result["revisedPlan"]["totalCost"],
            "updatedAt": now,
            "itineraries": updated_itineraries,
        },
        "$push": {"recommendations": replan_rec}}
    )

    return jsonify({
        "originalPlan": plan,
        "revisedPlan": result["revisedPlan"],
        "additionalCost": result["additionalCost"],
        "affectedItems": result["affectedItems"],
        "explanation": result["explanation"],
    })


def _extract_daily_plan(itinerary):
    items = itinerary.get("items", [])
    days = {}
    for item in items:
        day = item.get("day", 1)
        if day not in days:
            days[day] = {"day": day, "items": []}
        days[day]["items"].append(item)
    return [days[k] for k in sorted(days.keys())]
