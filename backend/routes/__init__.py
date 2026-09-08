"""Consolidated route registry.

All route blueprints from the former routes/ package are folded into this
single file using the same facade technique as services/ml.py: each module's
source is executed into its own `routes.<name>` namespace registered in
sys.modules, so existing imports (from routes.trips import trips_bp, ...) keep
working unchanged. Route code is preserved byte-for-byte; URL rules are
identical to the original 15-file layout.
"""

import sys
import types


_SRC = {
    'trips': r'''import uuid
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, Response
from functools import wraps
from services.mongodb import get_collection
from services.auth import current_user, require_login, is_admin
from services.transport_service import available_transports
from services.tourist_service import list_spots, list_tours
from services.guide_service import browse_guides
from services.hotel_service import search_hotels
from services.travel_orchestrator import generate_travel_plans
from services.booking_service import (
    create_booking, pay_trip_bookings, switch_transport
)
from services.ticket_service import issue_trip_token, build_trip_ticket_pdf

trips_bp = Blueprint("trips", __name__)

# Itinerary item types that represent an actual transport leg (used for delay
# propagation on DB-generated plans).
_TRANSPORT_ITEM_TYPES = ("BUS", "TRAIN", "FLIGHT", "CAB", "AUTO", "TRANSPORT")


def _resolve_user(fallback=True):
    """Return the authenticated user id or None. The legacy demo-user fallback
    is removed — every trip belongs to a real account."""
    user = current_user(allow_demo=False)
    return (user or {}).get("id")


def _owned_trip(trip_id, user_id):
    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return None
    if user_id and str(trip.get("userId")) != str(user_id):
        return None
    return trip


def _accessible_trip(trip_id, user):
    """Trip readable by its owner or an admin (read-only access)."""
    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return None
    if is_admin(user):
        return trip
    if not user or str(trip.get("userId")) != str(user.get("id")):
        return None
    return trip


def _ensure_trip_completed(trip):
    """Lazily mark a BOOKED trip COMPLETED once its end date has passed.

    Trip completion is a property of the trip itself (not of its individual
    service bookings): a trip is complete when its last travel day is behind us
    and it had been booked.
    """
    if not trip or trip.get("status") == "COMPLETED" or trip.get("status") != "BOOKED":
        return trip
    end = (trip.get("endDate") or "")[:10]
    try:
        done = datetime.strptime(end, "%Y-%m-%d").date() < datetime.utcnow().date()
    except (ValueError, TypeError):
        return trip
    if not done:
        return trip
    now = datetime.utcnow().isoformat()
    get_collection("trips").update_one({"_id": trip["_id"]}, {"$set": {
        "status": "COMPLETED", "completedAt": now, "updatedAt": now}})
    trip["status"] = "COMPLETED"
    for b in trip.get("bookings", []) or []:
        bid = b.get("_id")
        if bid and b.get("status") not in ("CANCELLED", "REJECTED"):
            get_collection("bookings").update_one({"_id": bid}, {"$set": {"status": "COMPLETED"}})
    return trip


@trips_bp.route("/api/trips", methods=["GET"])
def list_trips():
    user_id = _resolve_user()
    if not user_id:
        return jsonify({"error": "Authentication required. Please log in."}), 401
    trips = list(get_collection("trips").find(
        {"userId": user_id},
        sort=[("createdAt", -1)]
    ))
    for t in trips:
        _ensure_trip_completed(t)
        t["_id"] = str(t["_id"])
        if "itineraries" in t:
            for it in t["itineraries"]:
                if "_id" in it:
                    it["_id"] = str(it["_id"])
    return jsonify(trips)


@trips_bp.route("/api/admin/trips", methods=["GET"])
def admin_list_all_trips():
    """Admin overview of every user's planned/booked trips (Current Plans of Users)."""
    user = current_user(allow_demo=False)
    if not is_admin(user):
        return jsonify({"error": "You do not have access to this resource."}), 403
    trips = list(get_collection("trips").find(sort=[("createdAt", -1)]))
    users = {
        str(u.get("_id")): u
        for u in get_collection("users").find({}, {"name": 1, "email": 1, "mobile": 1})
    }
    for t in trips:
        _ensure_trip_completed(t)
        t["_id"] = str(t["_id"])
        if "itineraries" in t:
            for it in t["itineraries"]:
                if "_id" in it:
                    it["_id"] = str(it["_id"])
        u = users.get(str(t.get("userId") or "")) or {}
        t["user"] = {
            "name": u.get("name", "") or "",
            "email": u.get("email", "") or "",
            "mobile": u.get("mobile", "") or "",
        }
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

    budget_unlimited = bool(data.get("budgetUnlimited")) or data.get("budget") in (None, 0)
    if budget_unlimited:
        budget_value = 0
    else:
        budget_value = int(data.get("budget") or 0)
        if budget_value < 1000:
            return jsonify({"error": "Budget must be at least 1000"}), 400
    data["budget"] = budget_value
    data["budgetUnlimited"] = budget_unlimited

    travelers = data.get("travelers", 1)
    if travelers < 1 or travelers > 20:
        return jsonify({"error": "Travelers must be between 1 and 20"}), 400

    # Pick optional modules so catalogue-aware planning can engage.
    transport_type = data.get("transportType")
    if transport_type not in ("BUS", "TRAIN", "FLIGHT", "CAB", "AUTO"):
        transport_type = None

    user_id = _resolve_user()
    if not user_id:
        return jsonify({"error": "Authentication required. Please log in."}), 401
    trip_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    trip = {
        "_id": trip_id,
        "userId": user_id,
        "origin": data["origin"],
        "destination": data["destination"],
        # User-selected starting point from the Google Maps picker (optional in API,
        # but used by the optimizer when present).
        "startLocation": data.get("startLocation") or None,
        "destinationLocation": data.get("destinationLocation") or None,
        "startDate": data["startDate"],
        "endDate": data["endDate"],
        "travelers": travelers,
        "budget": data["budget"],
        "currency": data.get("currency", "INR"),
        "travelStyle": data.get("travelStyle", "BALANCED"),
        "transportType": transport_type,
        "servicePreference": data.get("servicePreference"),
        "prioritizedSpotIds": [str(s) for s in (data.get("prioritizedSpotIds") or []) if str(s)],
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
@require_login
def get_trip(trip_id):
    trip = _accessible_trip(trip_id, request.current_user)
    if not trip:
        return jsonify({"error": "Trip not found"}), 404
    _ensure_trip_completed(trip)
    trip["_id"] = str(trip["_id"])
    return jsonify(trip)


@trips_bp.route("/api/trips/<trip_id>/generate", methods=["POST"])
@require_login
def generate_plans(trip_id):
    trip = _owned_trip(trip_id, request.current_user.get("id"))
    if not trip:
        return jsonify({"error": "Trip not found"}), 404

    request_data = {
        "origin": trip["origin"],
        "destination": trip["destination"],
        "startDate": trip["startDate"],
        "endDate": trip["endDate"],
        "travelers": trip["travelers"],
        "budget": trip["budget"],
        "budgetUnlimited": bool(trip.get("budgetUnlimited")),
        "currency": trip.get("currency", "INR"),
        "travelStyle": trip.get("travelStyle", "BALANCED"),
        "foodPreference": trip.get("foodPreference"),
        "transportType": trip.get("transportType"),
        "servicePreference": trip.get("servicePreference"),
        "prioritizedSpotIds": trip.get("prioritizedSpotIds") or [],
        "startLocation": trip.get("startLocation"),
    }

    db_data = _gather_db_data(trip)

    result = generate_travel_plans(request_data, db_data)
    selected = result["selectedPlan"]

    now = datetime.utcnow().isoformat()

    if not selected:
        get_collection("trips").update_one(
            {"_id": trip_id},
            {"$set": {"itineraries": [], "recommendations": [], "updatedAt": now}})
        return jsonify({
            "selectedPlan": None,
            "plans": [],
            "aiExplanation": result["aiExplanation"],
            "source": "empty",
            "message": "No registered services found for this route yet. "
                       "Ask a transport or hotel provider to register services "
                       "for this route, then generate the plan again.",
        }), 200

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
                    "bookableId": item.get("bookableId"),
                    "distanceKm": item.get("distanceKm"),
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
        "category": "TRANSPORT" if selected.get("transport") else "FLIGHT",
        "recommendation": _recommendation_text(selected),
        "reasoning": result["aiExplanation"],
        "estimatedCost": selected.get("flight", {}).get("price") or (selected.get("transport") or {}).get("fare"),
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

    try:
        from services.ml.injector import reinforce_cost, reinforce_timing
        reinforce_cost(trip, selected["totalCost"])
        for day_plan in selected.get("dailyPlan", []):
            for item in day_plan.get("items", []):
                reinforce_timing(item.get("type"), item.get("startTime"), item.get("endTime"))
    except Exception:
        pass

    return jsonify({
        "selectedPlan": selected,
        "plans": result["plans"],
        "aiExplanation": result["aiExplanation"],
        "ml": result.get("ml", {}),
        "source": result.get("source", "mock"),
    })


@trips_bp.route("/api/trips/<trip_id>/book", methods=["POST"])
@require_login
def book_trip(trip_id):
    user = request.current_user
    trip = _owned_trip(trip_id, user.get("id"))
    if not trip:
        return jsonify({"error": "Trip not found"}), 404

    selected_itin = None
    for itin in trip.get("itineraries", []):
        if itin.get("status") == "SELECTED":
            selected_itin = itin
            break

    if not selected_itin:
        return jsonify({"error": "No selected itinerary found"}), 400

    travelers = int(trip.get("travelers") or 1)
    now = datetime.utcnow().isoformat()
    bookings = []
    total = 0
    errors = []

    for item in selected_itin.get("items", []):
        btype = (item.get("type") or "").upper()
        bookable = item.get("bookableId") or ""
        parts = bookable.split(":")

        payload = None
        if btype in ("BUS", "TRAIN", "FLIGHT", "CAB", "AUTO", "TRANSPORT"):
            if parts and parts[0] == "transport" and len(parts) > 1:
                payload = {"type": "TRANSPORT", "transportId": parts[1],
                           "qty": travelers, "seatType": None,
                           "tripId": trip_id, "date": trip.get("startDate")}
                if btype in ("CAB", "AUTO"):
                    distance_km = item.get("distanceKm")
                    if not distance_km:
                        try:
                            from services.maps_distance import route_distance_km
                            distance_km = route_distance_km(trip.get("origin"), trip.get("destination"))
                        except Exception:
                            distance_km = None
                    if distance_km:
                        payload["details"] = {"distanceKm": float(distance_km)}
        elif btype == "HOTEL":
            # bookableId = hotel:<hotelId>:<roomTypeId>
            if parts and parts[0] == "hotel" and len(parts) >= 3:
                payload = {"type": "HOTEL", "hotelId": parts[1],
                           "roomTypeId": parts[2], "qty": 1,
                           "tripId": trip_id,
                           "details": {"checkin": trip.get("startDate"),
                                       "checkout": trip.get("endDate")}}
        elif btype == "ACTIVITY":
            if parts and parts[0] == "spot" and len(parts) > 1:
                payload = {"type": "SPOT", "spotId": parts[1], "qty": travelers,
                           "tripId": trip_id, "date": trip.get("startDate")}
            elif parts and parts[0] == "guide" and len(parts) > 1:
                start = (item.get("startTime") or "")[11:16] or "09:00"
                end = (item.get("endTime") or "")[11:16] or "17:00"
                payload = {"type": "GUIDE", "guideId": parts[1], "qty": 1,
                           "date": trip.get("startDate"),
                           "tripId": trip_id,
                           "details": {"startTime": start, "endTime": end}}
        elif btype == "TOUR":
            if parts and parts[0] == "tour" and len(parts) > 1:
                payload = {"type": "TOUR", "tourId": parts[1], "qty": travelers,
                           "tripId": trip_id, "date": trip.get("startDate")}
        elif btype in ("FOOD", "RESTAURANT"):
            # bookableId = restaurant:<restaurantId>:<foodItemId>
            if parts and parts[0] == "restaurant" and len(parts) >= 3:
                payload = {"type": "RESTAURANT", "restaurantId": parts[1],
                           "foodItemId": parts[2], "qty": travelers,
                           "tripId": trip_id, "date": trip.get("startDate")}

        if payload is not None:
            booking, err = create_booking(payload, {"id": user.get("id"), "role": user.get("role")})
            if err:
                errors.append(f"{item.get('title', btype)}: {err}")
                continue
            booking = dict(booking)
            booking["tripId"] = trip_id
            booking["provider"] = item.get("provider", "")
            booking["itemTitle"] = item.get("title", "")
            bookings.append(booking)
            total += float(booking.get("total") or 0)

    if errors and not bookings:
        return jsonify({"error": "Booking failed: " + "; ".join(errors)}), 400

    reference = "TRP" + uuid.uuid4().hex[:8].upper()
    paid = bool(bookings) and all(
        b.get("paymentStatus") in ("WALLET", "COMPLETED") for b in bookings)
    if paid:
        payment_status = "COMPLETED"
    elif errors:
        payment_status = "FAILED" if bookings else "PENDING"
    else:
        payment_status = "PENDING"

    get_collection("trips").update_one(
        {"_id": trip_id},
        {"$set": {
            "status": "BOOKED",
            "reference": reference,
            "bookedAt": now,
            "paymentStatus": payment_status,
            "updatedAt": now,
            "bookings": bookings,
            "bookingErrors": errors,
        }}
    )

    published = [{
        "bookingReference": b.get("reference"),
        "type": b.get("type"),
        "provider": b.get("provider"),
        "itemTitle": b.get("itemTitle"),
        "status": b.get("status"),
        "price": b.get("total"),
        "currency": "INR",
        "bookedAt": b.get("createdAt"),
    } for b in bookings]

    return jsonify({"bookings": published, "totalCost": total, "errors": errors, "partial": bool(errors)})


@trips_bp.route("/api/trips/<trip_id>/pay", methods=["POST"])
@require_login
def pay_trip(trip_id):
    trip = _owned_trip(trip_id, request.current_user.get("id"))
    if not trip:
        return jsonify({"error": "Trip not found"}), 404
    if not (trip.get("bookings") or []):
        return jsonify({"error": "No bookings to pay for."}), 400
    updated, trip, errors = pay_trip_bookings(trip, request.current_user)
    paid = sum(float(b.get("total") or 0) for b in updated
               if b.get("paymentStatus") in ("WALLET", "COMPLETED"))
    return jsonify({
        "paymentStatus": trip.get("paymentStatus"),
        "paidBookings": len([b for b in updated if b.get("paymentStatus") in ("WALLET", "COMPLETED")]),
        "totalPaid": round(paid, 2),
        "errors": errors,
        "message": "Payment complete." if not errors else "Some payments failed: " + "; ".join(errors),
    })


@trips_bp.route("/api/trips/<trip_id>/token", methods=["GET"])
@require_login
def trip_token(trip_id):
    trip = _accessible_trip(trip_id, request.current_user)
    if not trip:
        return jsonify({"error": "Trip not found"}), 404
    return jsonify({"token": issue_trip_token(trip)})


@trips_bp.route("/api/trips/<trip_id>/ticket", methods=["GET"])
@require_login
def trip_ticket(trip_id):
    trip = _accessible_trip(trip_id, request.current_user)
    if not trip:
        return jsonify({"error": "Trip not found"}), 404
    _ensure_trip_completed(trip)
    try:
        pdf = build_trip_ticket_pdf(trip)
    except Exception:
        return jsonify({"error": "Could not generate the trip ticket."}), 500
    ref = trip.get("reference") or trip["_id"]
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition":
                 'attachment; filename="TripMind-trip-%s.pdf"' % ref})


@trips_bp.route("/api/trips/<trip_id>/events", methods=["GET"])
@require_login
def get_events(trip_id):
    trip = _accessible_trip(trip_id, request.current_user)
    if not trip:
        return jsonify({"error": "Trip not found"}), 404
    _ensure_trip_completed(trip)
    events = trip.get("events", [])
    events.sort(key=lambda e: e.get("occurredAt", ""), reverse=True)
    return jsonify(events)


@trips_bp.route("/api/trips/<trip_id>/itinerary", methods=["GET"])
@require_login
def get_itinerary(trip_id):
    trip = _accessible_trip(trip_id, request.current_user)
    if not trip:
        return jsonify({"error": "Trip not found"}), 404
    _ensure_trip_completed(trip)
    itineraries = trip.get("itineraries", [])
    for itin in itineraries:
        if "items" in itin:
            itin["items"].sort(key=lambda x: (x.get("day", 0), x.get("sortOrder", 0)))
    itineraries.sort(key=lambda x: x.get("version", 0), reverse=True)
    return jsonify(itineraries)


def _apply_delay(plan_items, delay_minutes, shift=False):
    """Flag DB itinerary items affected by a transport delay.

    The transport leg is marked DELAYED and every item that starts at/after it
    is marked AFFECTED. When ``shift`` is True the reschedule actually happens:
    those items' times move forward by the delay and they are labelled
    RESCHEDULED. Returns (items, affected).
    """
    delay_minutes = int(delay_minutes or 60)
    affected = []
    delayed_ts = None
    items = sorted(plan_items, key=lambda x: (x.get("day", 1), x.get("sortOrder", 0)))
    for item in items:
        is_transport = (item.get("type") or "").upper() in _TRANSPORT_ITEM_TYPES
        try:
            st = datetime.fromisoformat((item.get("startTime") or "")[:19])
        except (ValueError, TypeError):
            st = None
        if delayed_ts is None and is_transport and st is not None:
            delayed_ts = st
        if is_transport and st is not None:
            item["status"] = "RESCHEDULED" if shift else "DELAYED"
            if shift:
                item["startTime"] = (st + timedelta(minutes=delay_minutes)).isoformat()
                et = item.get("endTime")
                if et:
                    try:
                        item["endTime"] = (datetime.fromisoformat((et or "")[:19])
                                           + timedelta(minutes=delay_minutes)).isoformat()
                    except (ValueError, TypeError):
                        pass
            affected.append({"title": item.get("title", ""), "status": item["status"]})
        elif st is not None and delayed_ts is not None and st >= delayed_ts:
            item["status"] = "RESCHEDULED" if shift else "AFFECTED"
            if shift:
                item["startTime"] = (st + timedelta(minutes=delay_minutes)).isoformat()
                et = item.get("endTime")
                if et:
                    try:
                        item["endTime"] = (datetime.fromisoformat((et or "")[:19])
                                           + timedelta(minutes=delay_minutes)).isoformat()
                    except (ValueError, TypeError):
                        pass
            affected.append({"title": item.get("title", ""), "status": item["status"]})
    return items, affected


@trips_bp.route("/api/trips/<trip_id>/simulate-delay", methods=["POST"])
@require_login
def simulate_delay(trip_id):
    data = request.get_json() or {}
    delay_minutes = int(data.get("delayMinutes", 60))
    if delay_minutes < 1:
        return jsonify({"error": "delayMinutes must be a positive number"}), 400

    trip = _owned_trip(trip_id, request.current_user.get("id"))
    if not trip:
        return jsonify({"error": "Trip not found"}), 404

    selected_itin = next((it for it in trip.get("itineraries", [])
                          if it.get("status") == "SELECTED"), None)
    if not selected_itin:
        return jsonify({"error": "No selected itinerary"}), 400

    severity = "LOW" if delay_minutes < 120 else ("MEDIUM" if delay_minutes < 240 else "HIGH")
    now = datetime.utcnow().isoformat()

    items, affected = _apply_delay(list(selected_itin.get("items") or []), delay_minutes)
    selected_itin["items"] = items
    trip_bookings = []
    for b in trip.get("bookings", []) or []:
        btype = (b.get("type") or "").upper()
        if btype in _TRANSPORT_ITEM_TYPES or btype == "TRANSPORT":
            b["delayStatus"] = "DELAYED"
            b["delay"] = {"minutes": delay_minutes}
        elif b.get("status") not in ("CANCELLED", "REJECTED"):
            b["delayStatus"] = "AFFECTED"
        trip_bookings.append(b)
        if b.get("_id"):
            get_collection("bookings").update_one(
                {"_id": b["_id"]},
                {"$set": {"delayStatus": b.get("delayStatus"),
                          "delay": b.get("delay", None)}})

    event = {
        "_id": str(uuid.uuid4()),
        "tripId": trip_id,
        "type": "DELAY",
        "title": f"Transport delay - {delay_minutes} minutes",
        "description": f"Simulated {delay_minutes}-minute transport delay; downstream "
                       f"items affected ({len(affected)}).",
        "severity": severity,
        "occurredAt": now,
        "resolvedAt": None,
    }

    itineraries = []
    for it in trip.get("itineraries", []):
        if it.get("_id") == selected_itin.get("_id"):
            it["items"] = items
        itineraries.append(it)

    get_collection("trips").update_one(
        {"_id": trip_id},
        {"$set": {
            "status": "REPLANNING",
            "updatedAt": now,
            "itineraries": itineraries,
            "bookings": trip_bookings,
            "delay": {"minutes": delay_minutes, "severity": severity,
                      "occurredAt": now, "status": "ACTIVE"},
        },
         "$push": {"events": event}}
    )

    try:
        from services.ml.injector import reinforce_delay
        route = f"{trip['origin'].strip().lower()}|{trip['destination'].strip().lower()}"
        reinforce_delay(route, None, True, delay_minutes)
    except Exception:
        pass

    return jsonify({"event": event, "severity": severity, "affectedItems": affected})


@trips_bp.route("/api/trips/<trip_id>/replan", methods=["POST"])
@require_login
def replan_trip(trip_id):
    data = request.get_json() or {}
    delay_minutes = int(data.get("delayMinutes", 60))
    if delay_minutes < 1:
        return jsonify({"error": "delayMinutes must be a positive number"}), 400

    trip = _owned_trip(trip_id, request.current_user.get("id"))
    if not trip:
        return jsonify({"error": "Trip not found"}), 404

    selected_itin = next((it for it in trip.get("itineraries", [])
                          if it.get("status") == "SELECTED"), None)
    if not selected_itin:
        return jsonify({"error": "No selected itinerary"}), 400
    if trip.get("delay", {}).get("status") != "ACTIVE":
        return jsonify({"error": "No active delay to resolve. Run Simulate Delay first."}), 400

    now = datetime.utcnow().isoformat()
    version = max((it.get("version", 0) for it in trip.get("itineraries", [])), default=0) + 1

    items, affected = _apply_delay(list(selected_itin.get("items") or []),
                                   delay_minutes, shift=True)
    for it in items:
        if it.get("status") == "RESCHEDULED":
            it["status"] = "RESCHEDULED"
    total = round(sum(float(it.get("cost") or 0) for it in items), 2)

    new_itin = {
        "_id": str(uuid.uuid4()),
        "tripId": trip_id,
        "version": version,
        "status": "SELECTED",
        "totalCost": total,
        "generatedBy": "AI",
        "planType": selected_itin.get("planType", "BALANCED"),
        "reasoning": selected_itin.get("reasoning", []) + [
            f"Replanned after a {delay_minutes}-minute delay. "
            f"All affected items rescheduled (+{delay_minutes} min)."],
        "createdAt": now,
        "items": items,
        "optimizationScore": selected_itin.get("optimizationScore", 0),
        "comfortScore": selected_itin.get("comfortScore", 0),
        "travelTime": selected_itin.get("travelTime", "N/A"),
    }

    updated_itineraries = []
    for it in trip.get("itineraries", []):
        if it.get("status") == "SELECTED":
            it["status"] = "SUPERSEDED"
        updated_itineraries.append(it)
    updated_itineraries.append(new_itin)

    replan_rec = {
        "_id": str(uuid.uuid4()),
        "tripId": trip_id,
        "category": "REPLANNING",
        "recommendation": f"Replanned after {delay_minutes}-minute delay",
        "reasoning": f"Rescheduled {len(affected)} affected itinerary items.",
        "estimatedCost": 0,
        "confidence": 0.85,
        "createdAt": now,
    }

    trip_bookings = []
    for b in trip.get("bookings", []) or []:
        b.pop("delayStatus", None)
        b.pop("delay", None)
        trip_bookings.append(b)
        if b.get("_id"):
            get_collection("bookings").update_one(
                {"_id": b["_id"]},
                {"$unset": {"delayStatus": "", "delay": ""}})

    delay_doc = dict(trip.get("delay") or {})
    delay_doc.update({"status": "RESOLVED", "resolvedAt": now})

    get_collection("trips").update_one(
        {"_id": trip_id},
        {"$set": {
            "status": "PLANNED",
            "totalEstimatedCost": total,
            "updatedAt": now,
            "itineraries": updated_itineraries,
            "bookings": trip_bookings,
            "delay": delay_doc,
        },
         "$push": {"recommendations": replan_rec,
                   "events": {"_id": str(uuid.uuid4()), "tripId": trip_id,
                              "type": "DELAY_RESOLVED",
                              "title": "Delay resolved - replanned",
                              "description": "Itinerary rescheduled after delay.",
                              "severity": "LOW", "occurredAt": now}}}
    )

    return jsonify({
        "revisedPlan": {"totalCost": total, "dailyPlan": [], "items": items},
        "originalCost": selected_itin.get("totalCost", 0),
        "revisedCost": total,
        "additionalCost": 0,
        "affectedItems": [a["title"] for a in affected],
        "explanation": f"Transport delayed by {delay_minutes} minutes; itinerary "
                       f"rescheduled. No additional charges.",
    })


@trips_bp.route("/api/trips/<trip_id>/itinerary/items", methods=["POST"])
@require_login
def edit_itinerary_items(trip_id):
    user = request.current_user
    trip = _owned_trip(trip_id, user.get("id"))
    if not trip:
        return jsonify({"error": "Trip not found"}), 404

    data = request.get_json() or {}
    action = (data.get("action") or "").lower()
    if action not in ("remove", "add", "update"):
        return jsonify({"error": "Action must be remove, add or update."}), 400

    selected = next((it for it in trip.get("itineraries", []) if it.get("status") == "SELECTED"), None)
    if not selected:
        return jsonify({"error": "No selected itinerary found"}), 400

    items = list(selected.get("items") or [])

    if action == "remove":
        item_id = data.get("itemId")
        if not item_id:
            return jsonify({"error": "Missing field: itemId"}), 400
        keep = [it for it in items if str(it.get("_id")) != str(item_id)]
        if len(keep) == len(items):
            return jsonify({"error": "Itinerary item not found."}), 404
        items = keep
    elif action == "update":
        item_id = data.get("itemId")
        item = next((it for it in items if str(it.get("_id")) == str(item_id)), None)
        if not item:
            return jsonify({"error": "Itinerary item not found."}), 404
        if "cost" in data:
            try:
                item["cost"] = float(data["cost"])
            except (TypeError, ValueError):
                return jsonify({"error": "cost must be a number."}), 400
            if item["cost"] < 0:
                return jsonify({"error": "cost cannot be negative."}), 400
    else:  # add
        itype = (data.get("type") or "").upper()
        title = (data.get("title") or "").strip()
        if not itype or not title:
            return jsonify({"error": "type and title are required to add an itinerary item."}), 400
        try:
            cost = float(data.get("cost") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "cost must be a number."}), 400
        day = int(data.get("day") or 1)
        max_day = max((it.get("day", 1) for it in items), default=1)
        if day < 1:
            day = 1
        items.append({
            "_id": str(uuid.uuid4()),
            "type": itype,
            "title": title,
            "provider": data.get("provider", ""),
            "location": data.get("location", ""),
            "startTime": data.get("startTime"),
            "endTime": data.get("endTime"),
            "cost": cost,
            "currency": "INR",
            "status": "PLANNED",
            "day": day,
            "sortOrder": max((it.get("sortOrder", 0) for it in items), default=-1) + 1,
            "metadata": None,
            "bookableId": data.get("bookableId"),
            "distanceKm": data.get("distanceKm"),
        })

    travelers = int(trip.get("travelers") or 1)
    new_items = []
    for it in items:
        for field in ("type", "title", "provider", "location", "startTime", "endTime",
                      "cost", "currency", "status", "day", "sortOrder", "metadata",
                      "bookableId", "distanceKm"):
            it.setdefault(field, None if field not in ("type", "title", "currency", "status") else "")
        new_items.append(it)
    total = round(sum(float(it.get("cost") or 0) for it in new_items) * travelers, 2)

    budget = int(trip.get("budget") or 0) * travelers
    unlimited = bool(trip.get("budgetUnlimited")) or trip.get("budget") in (None, 0)
    now = datetime.utcnow().isoformat()

    corrected = []
    for it in new_items:
        keep = {k: it.get(k) for k in (
            "_id", "type", "title", "provider", "location", "startTime", "endTime",
            "cost", "currency", "status", "day", "sortOrder", "metadata",
            "bookableId", "distanceKm")}
        corrected.append(keep)
    items = corrected

    selected["items"] = items
    selected["totalCost"] = total
    selected["version"] = int(selected.get("version", 1)) + 1
    selected["updatedAt"] = now
    selected["reasoning"] = selected.get("reasoning", []) + [
        "Itinerary edited by the user; total cost recalculated."]

    superseded = []
    for it in trip.get("itineraries", []):
        superseded.append({**{k: v for k, v in it.items() if k != "items"}, **{
            "items": it.get("items") or []}})
    merged = []
    for it in superseded:
        if it.get("status") == "SELECTED" and it.get("_id") != selected.get("_id"):
            it["status"] = "SUPERSEDED"
        merged.append(it)
    merged = [it for it in merged if it.get("_id") != selected.get("_id")] + [selected]

    get_collection("trips").update_one(
        {"_id": trip_id},
        {"$set": {
            "itineraries": merged,
            "totalEstimatedCost": total,
            "updatedAt": now,
        }}
    )

    return jsonify({
        "itinerary": selected,
        "totalCost": total,
        "budget": budget if not unlimited else None,
        "budgetUnlimited": unlimited,
        "budgetRemaining": None if unlimited else round(max(0, budget - total), 2),
        "budgetUtilization": None if (unlimited or budget <= 0) else round(min(1.0, total / budget), 4),
        "itemCount": len(items),
    })


def _recommendation_text(plan):
    leg = plan.get("transport")
    if leg:
        return f"Book {leg.get('type')} via {leg.get('serviceName', '')} ({leg.get('busNumber') or leg.get('trainNumber') or leg.get('flightNumber') or leg.get('vehicleNumber')})"
    if plan.get("flight"):
        return f"Book {plan['flight']['airline']} flight"
    return "Plan ready — no transport booking recommended."


def _gather_db_data(trip):
    """Pull real catalogue data for the trip corridor."""
    db_data = {}
    try:
        ttype = trip.get("transportType")
        transports = available_transports(trip["origin"], trip["destination"], ttype)
        if transports:
            db_data["transports"] = transports
    except Exception:
        pass
    try:
        spots = list_spots(city=trip.get("destination"))
        if spots:
            db_data["spots"] = spots
    except Exception:
        pass
    try:
        tours = list_tours(city=trip.get("destination"))
        if tours:
            db_data["tours"] = tours
    except Exception:
        pass
    try:
        guides = browse_guides(location=trip.get("destination"))
        if guides:
            db_data["guides"] = guides
    except Exception:
        pass
    try:
        hotels = search_hotels(city=trip.get("destination"))
        if hotels:
            db_data["hotels"] = hotels
    except Exception:
        pass
    try:
        from services.restaurant_service import list_restaurants, list_food_items
        restaurants = list_restaurants(None, city=trip.get("destination"))
        foods = []
        for r in (restaurants or [])[:3]:
            items = list_food_items(r["id"], only_available=True)
            if not items:
                continue
            item = items[0]
            foods.append({
                "name": r.get("name", ""),
                "restaurantName": r.get("name", ""),
                "pricePerPerson": float(item.get("price") or 0),
                "restaurantId": r["id"],
                "foodId": item.get("id"),
                "foodName": item.get("name", ""),
                "bookableId": "restaurant:%s:%s" % (r["id"], item.get("id") or ""),
            })
        if foods:
            db_data["foods"] = foods
    except Exception:
        pass
    return db_data


def _extract_daily_plan(itinerary):
    items = itinerary.get("items", [])
    days = {}
    for item in items:
        day = item.get("day", 1)
        if day not in days:
            days[day] = {"day": day, "items": []}
        days[day]["items"].append(item)
    return [days[k] for k in sorted(days.keys())]
''',
    'ai': r'''from flask import Blueprint, request, jsonify
from services.ai_chat import handle_ai_chat
from services.assistant import handle_assistant_message, execute_action
from services.groq_service import call_ai, is_ai_available
from services.reviews import get_all_reviews
from services.route_mindmap import get_journey_flow
from services.mongodb import get_collection
from services.auth import require_login, current_user

ai_bp = Blueprint("ai", __name__)


def _owned_trip(trip_id, user_id):
    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return None
    if str(trip.get("userId")) != str(user_id):
        return None
    return trip


@ai_bp.route("/api/mindmap/flow", methods=["GET"])
def journey_flow():
    frm = (request.args.get("from") or "Coimbatore").strip()
    to = (request.args.get("to") or "Chennai").strip()
    flow = get_journey_flow(frm, to)
    return jsonify(flow)


@ai_bp.route("/api/ai/chat", methods=["POST"])
@require_login
def ai_chat():
    user = request.current_user
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Message is required"}), 400

    trip_id = data.get("tripId")
    message = data["message"]
    if trip_id and not _owned_trip(trip_id, user.get("id")):
        return jsonify({"error": "Trip not found"}), 404
    result = handle_ai_chat(trip_id, message)
    return jsonify(result)


@ai_bp.route("/api/assistant/chat", methods=["POST"])
@require_login
def assistant_chat():
    user = request.current_user
    data = request.get_json()
    if not data or not (data.get("message") or "").strip():
        return jsonify({"error": "Message is required"}), 400
    trip_id = data.get("tripId")
    if trip_id and not _owned_trip(trip_id, user.get("id")):
        return jsonify({"error": "Trip not found"}), 404
    result = handle_assistant_message(user, data["message"].strip(), trip_id)
    return jsonify(result)


@ai_bp.route("/api/assistant/action", methods=["POST"])
@require_login
def assistant_action():
    """Executes a confirmed assistant proposal. Every mutation is re-validated
    for ownership and current state before it runs."""
    user = request.current_user
    data = request.get_json()
    action_type = data.get("type") if isinstance(data, dict) else None
    params = data.get("params") if isinstance(data, dict) else None
    if action_type not in ("change_transport", "pay_trip", "remove_place"):
        return jsonify({"error": "Unsupported action."}), 400
    payload, status = execute_action(user, action_type, params)
    return jsonify(payload), status


@ai_bp.route("/api/ai/feedback-analysis", methods=["POST"])
@require_login
def feedback_analysis():
    """AI analysis of all trip reviews (structured output, no DB mutation).

    Returns {summary, sentiment, themes, suggestions, rawReviewCount}.
    """
    from services.auth import is_admin
    if not is_admin(request.current_user):
        return jsonify({"error": "Admins only."}), 403
    if not is_ai_available():
        return jsonify({
            "summary": "AI not configured. Showing placeholder analysis.",
            "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
            "themes": [],
            "suggestions": [],
            "rawReviewCount": 0,
        })

    reviews = get_all_reviews(limit=300)
    if not reviews:
        return jsonify({
            "summary": "No reviews yet.",
            "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
            "themes": [],
            "suggestions": [],
            "rawReviewCount": 0,
        })

    review_text = "\n".join(
        f"Rating {r['rating']}/5: {r['comment']} ({r.get('origin','?')}→{r.get('destination','?')})"
        for r in reviews
    )

    system = (
        "You are TripMind AI, a travel analytics engine. "
        "You receive anonymised user reviews of AI-planned trips. "
        "Return ONLY a JSON object (no markdown, no explanation) with this schema: "
        '{"summary":"<1-2 sentence overall summary>",'
        '"sentiment":{"positive":<int>,"neutral":<int>,"negative":<int>},'
        '"themes":[{"theme":"<name>","count":<int>,"sentiment":"positive|neutral|negative"}],'
        '"suggestions":["<actionable improvement>"]}'
    )
    prompt = (
        f"Here are {len(reviews)} user reviews (rating out of 5 + free comment):\n\n"
        f"{review_text}\n\n"
        "Analyse them and return the JSON object described in the system instructions."
    )
    try:
        raw = call_ai(prompt, system)
        import json
        parsed = json.loads(raw)
        parsed["rawReviewCount"] = len(reviews)
        parsed.setdefault("summary", parsed.get("overall_summary") or parsed.get("summary_text") or "See themes and suggestions below.")
        parsed.setdefault("sentiment", {"positive": 0, "neutral": 0, "negative": 0})
        parsed.setdefault("themes", [])
        parsed.setdefault("suggestions", [])
        return jsonify(parsed)
    except Exception:
        return jsonify({
            "summary": "Unable to analyse reviews at this time.",
            "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
            "themes": [],
            "suggestions": [],
            "rawReviewCount": len(reviews),
        })
''',
    'auth': r'''from flask import Blueprint, request, jsonify, session
from config import ROLES, PROVIDER_ROLES, APPROVAL_STATUSES, DEV_MODE
from services.auth import (
    register_user, register_provider, login_user, logout_user, current_user,
    require_login, require_admin, is_admin,
)
from services import duplicate
from services.mongodb import get_collection
from datetime import datetime

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    role = (data.get("role") or "").strip().upper()

    dup = duplicate.register_duplicate_check(data)
    if dup:
        return jsonify({"error": dup["message"], "field": dup["field"]}), 409

    if role == ROLES["USER"] or not role:
        user, err = register_user(data, role=ROLES["USER"])
    elif role in PROVIDER_ROLES:
        # Provider registrations start PENDING and wait for Admin approval.
        user, err = register_provider(data, role=role)
    else:
        return jsonify({"error": "Invalid role."}), 400
    if err:
        return jsonify({"error": err}), 400
    msg = ("Account created. Your provider account is pending Admin approval."
           if user["role"] in PROVIDER_ROLES else "Account created. Please log in.")
    return jsonify({"user": user, "message": msg}), 201


@auth_bp.route("/api/auth/check-availability", methods=["GET"])
def check_availability():
    """Live duplicate-data check used by registration wizards and catalog
    forms. Returns {"available": true/false} for a known field."""
    field = request.args.get("field") or ""
    value = request.args.get("value") or ""
    identity_type = request.args.get("identityType") or ""
    user = current_user(allow_demo=False)
    result = duplicate.check_available(field, value, user=user, identity_type=identity_type)
    if result is None:
        return jsonify({"error": "Unknown availability field: %s" % field}), 400
    return jsonify({"field": field, "value": value, "available": result})


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    if not data.get("email") or not data.get("password"):
        return jsonify({"error": "Email and password are required."}), 400
    user, err = login_user(data["email"], data["password"])
    if err:
        return jsonify({"error": err}), 401
    return jsonify({"user": user, "message": "Logged in."})


@auth_bp.route("/api/auth/logout", methods=["POST"])
def logout():
    logout_user()
    return jsonify({"message": "Logged out."})


@auth_bp.route("/api/auth/me", methods=["GET"])
def me():
    user = current_user(allow_demo=False)
    if not user:
        return jsonify({"user": None}), 200
    return jsonify({"user": user})


@auth_bp.route("/api/auth/registration-fields", methods=["GET"])
def registration_fields():
    """Field definitions the registration wizard must collect for a provider
    role (business identity collected once, presented read-only in the portal
    afterwards). Public — the wizard asks before an account exists."""
    from services.duplicate import role_fields, WEEK_DAYS
    role = (request.args.get("role") or "").strip().upper()
    if role not in PROVIDER_ROLES:
        return jsonify({"error": "Unknown provider role."}), 400
    fields, gst = role_fields(role)
    return jsonify({"role": role, "fields": fields, "gst": gst,
                    "weekDays": list(WEEK_DAYS)})


@auth_bp.route("/api/auth/roles", methods=["GET"])
def roles():
    import config as cfg
    return jsonify({
        "roles": list(ROLES.values()),
        "mapsEnabled": bool(cfg.GOOGLE_MAPS_API_KEY),
        # Required to render the client-side Google Maps JS API (prototype).
        "mapsKey": cfg.GOOGLE_MAPS_API_KEY,
    })


@auth_bp.route("/api/users/me", methods=["GET"])
@require_login
def my_profile():
    return jsonify({"user": request.current_user})


@auth_bp.route("/api/users/me", methods=["PATCH"])
@require_login
def update_profile():
    data = request.get_json() or {}
    upd = {}
    for field in ("name", "phone", "preferences"):
        if field in data and data[field] is not None:
            upd[field] = data[field]
    # Keep the canonical unique `mobile` in sync with the user-editable `phone`.
    if ("phone" in data and data["phone"] is not None) or ("mobile" in data and data["mobile"]):
        mobile = duplicate.normalize_mobile(data.get("phone") if data.get("phone") is not None else data.get("mobile"))
        if len(mobile) == 10:
            upd["mobile"] = mobile
    if "profile" in data and isinstance(data["profile"], dict):
        upd["profile"] = data["profile"]
    if upd:
        get_collection("users").update_one(
            {"_id": request.current_user["id"]}, {"$set": upd})
    return jsonify({"message": "Profile updated."})


@auth_bp.route("/api/admin/users", methods=["GET"])
@require_admin
def admin_list_users():
    """List accounts with optional role / approval-status / keyword filters
    (Admin only)."""
    role = (request.args.get("role") or "").strip().upper()
    approval = (request.args.get("approvalStatus") or "").strip().upper()
    status = (request.args.get("status") or "").strip().upper()
    q = (request.args.get("q") or "").strip().lower()
    explicit_approval = bool(approval and approval in APPROVAL_STATUSES)
    query = {}
    if role and role in ROLES.values():
        query["role"] = role
    if explicit_approval:
        query["approvalStatus"] = approval
    if status and status in ("ACTIVE", "INACTIVE"):
        query["status"] = status
    if q:
        query["$or"] = [{"name": {"$regex": q, "$options": "i"}},
                        {"email": {"$regex": q, "$options": "i"}}]
    users = []
    for u in get_collection("users").find(query).sort("createdAt", -1):
        derived = u.get("approvalStatus") or ("APPROVED" if u.get("approved") else "PENDING")
        if not explicit_approval and derived not in ("APPROVED", "SUSPENDED"):
            # All Users lists only accounts reviewed by the Admin — never
            # PENDING registrations or REJECTED accounts. (Server-side truth.)
            continue
        users.append({
            "id": str(u["_id"]),
            "name": u.get("name"),
            "email": u.get("email"),
            "role": u.get("role"),
            "status": u.get("status", "ACTIVE"),
            "approvalStatus": derived,
            "approvalReason": u.get("approvalReason", ""),
            "profile": u.get("profile", {}),
            "registration": u.get("registration", {}),
            "documents": u.get("documents", []),
            "images": u.get("images", []),
            "createdAt": u.get("createdAt"),
        })
    return jsonify({"users": users})


@auth_bp.route("/api/admin/users/<user_id>/approval", methods=["POST"])
@require_admin
def admin_set_approval(user_id):
    """Admin decision on an account.

    status := APPROVED | REJECTED | SUSPENDED | ACTIVE | INACTIVE
    - APPROVED / REJECTED / SUSPENDED are account approval states (any role).
      A SUSPENDED account can no longer log in or use the platform.
    - ACTIVE / INACTIVE toggle the account itself (block/unblock).
    """
    data = request.get_json() or {}
    status = (data.get("status") or "").strip().upper()
    reason = (data.get("reason") or "").strip()
    if status not in ("APPROVED", "REJECTED", "SUSPENDED", "ACTIVE", "INACTIVE"):
        return jsonify({"error": "Invalid decision status."}), 400
    try:
        uid = str(user_id)
        if not uid or len(uid) != 24 or not all(c in "0123456789abcdefABCDEF" for c in uid):
            return jsonify({"error": "Invalid user id."}), 400
    except Exception:
        return jsonify({"error": "Invalid user id."}), 400

    user = get_collection("users").find_one({"_id": uid})
    if not user:
        return jsonify({"error": "User not found."}), 404

    if user.get("role") == ROLES["ADMIN"]:
        # Never allow the Admin to suspend / reject / block a fellow admin —
        # there is no account above the Admin to restore it.
        if status in ("APPROVED", "REJECTED", "SUSPENDED", "INACTIVE"):
            return jsonify({"error": "Administrator accounts cannot be suspended, rejected or blocked."}), 400

    upd = {}
    reviewer = request.current_user.get("name") or request.current_user.get("email")
    now = datetime.utcnow().isoformat()
    if status == "APPROVED":
        upd.update({"approved": True, "approvalStatus": "APPROVED", "approvalReason": "",
                    "approvedAt": now, "approvedBy": reviewer})
    elif status == "REJECTED":
        if not reason:
            return jsonify({"error": "A rejection reason is required."}), 400
        upd.update({"approved": False, "approvalStatus": "REJECTED", "approvalReason": reason,
                    "rejectedAt": now, "rejectedBy": reviewer})
    elif status == "SUSPENDED":
        upd.update({"approved": False, "approvalStatus": "SUSPENDED",
                    "approvalReason": reason or "Suspended by Admin.",
                    "suspendedAt": now, "suspendedBy": reviewer})
    if status == "ACTIVE":
        upd["status"] = "ACTIVE"
    elif status == "INACTIVE":
        upd["status"] = "INACTIVE"
        upd["approvalReason"] = reason or upd.get("approvalReason", "Blocked by Admin.")

    if upd:
        get_collection("users").update_one({"_id": uid}, {"$set": upd})
        updated = get_collection("users").find_one({"_id": uid})
    else:
        updated = user
    pub = {
        "id": str(updated["_id"]),
        "name": updated.get("name"),
        "email": updated.get("email"),
        "role": updated.get("role"),
        "status": updated.get("status", "ACTIVE"),
        "approvalStatus": updated.get("approvalStatus") or ("APPROVED" if updated.get("approved") else "PENDING"),
        "approvalReason": updated.get("approvalReason", ""),
    }
    return jsonify({"message": "Account updated successfully.", "user": pub})''',
    'transport': r'''from flask import Blueprint, request, jsonify
from config import ROLES, TRANSPORT_TYPES
from services.auth import require_roles, require_login, is_admin, require_approved_provider
from services.transport_service import (create_transport, update_transport,
                                        get_transport, list_transports,
                                        set_status, set_service_profile,
                                        available_transports)
from services.mongodb import get_collection

transport_bp = Blueprint("transport", __name__)


@transport_bp.route("/api/transport/types", methods=["GET"])
def transport_types():
    return jsonify({
        "types": [{"value": k, "label": v["label"], "group": v["group"]}
                  for k, v in TRANSPORT_TYPES.items()],
    })


def _transport_view(owner, user=None, include_docs=False):
    return {
        "transportId": owner["_id"],
        "type": owner["type"],
        "status": owner["status"],
        "serviceName": owner["serviceName"],
        "summary": _summary(owner),
        "details": owner if include_docs else None,
        "canEdit": bool(user and user["id"] == owner["ownerId"]),
    }


def _summary(t):
    if t["type"] == "BUS":
        return f"{t['busNumber']} : {t['boardingPoint']} (Day {t['boardingDay']} {t['boardingTime']}) -> {t['droppingPoint']}"
    if t["type"] == "TRAIN":
        return f"{t['trainNumber']} {t['trainName']} : {t['boardingStation']} -> {t['destinationStation']}"
    if t["type"] == "FLIGHT":
        return f"{t['flightNumber']} : {t['departureAirport']} -> {t['arrivalAirport']}"
    return f"{t['vehicleNumber']} : {t.get('serviceArea', '')}"


@transport_bp.route("/api/transport/services", methods=["GET", "POST"])
@require_approved_provider
def services():
    user = request.current_user
    if request.method == "POST":
        if user["role"] != ROLES["TRANSPORT_ADMIN"]:
            return jsonify({"error": "Only transport admins can manage a service profile."}), 403
        profile = set_service_profile(user["id"], request.get_json() or {})
        return jsonify({"profile": profile})
    u = get_collection("users").find_one({"_id": user["id"]})
    return jsonify({"profile": (u or {}).get("profile", {})})


@transport_bp.route("/api/transport/list", methods=["GET"])
@require_login
def list_all():
    user = request.current_user
    ttype = request.args.get("type")
    is_owner = user["role"] == ROLES["TRANSPORT_ADMIN"]
    owner_id = user["id"] if is_owner else (request.args.get("ownerId") or None)
    docs = list_transports(owner_id=owner_id, ttype=ttype)
    return jsonify({"transports": [_transport_view(d, user, include_docs=bool(is_owner)) for d in docs]})


@transport_bp.route("/api/transport/register", methods=["POST"])
@require_approved_provider
def register():
    user = request.current_user
    if user["role"] != ROLES["TRANSPORT_ADMIN"]:
        return jsonify({"error": "Only transport admins can register transport."}), 403
    data = request.get_json() or {}
    ttype = (data.get("type") or "").upper()
    if ttype not in TRANSPORT_TYPES:
        return jsonify({"error": "Type must be one of %s." % ", ".join(TRANSPORT_TYPES)}), 400
    doc, err = create_transport(ttype, data, request.current_user["id"])
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"transport": _transport_view(doc, request.current_user)}), 201


@transport_bp.route("/api/transport/<tid>", methods=["GET", "PUT"])
@require_login
def detail(tid):
    doc = get_transport(tid)
    if not doc:
        return jsonify({"error": "Transport not found."}), 404
    if request.method == "PUT":
        if request.current_user["role"] != ROLES["TRANSPORT_ADMIN"]:
            return jsonify({"error": "Not authorized."}), 403
        if request.current_user.get("approvalStatus") != "APPROVED":
            return jsonify({"error": "Your provider account must be approved by the Admin."}), 403
        data = request.get_json() or {}
        data["transportId"] = tid
        new, err = update_transport(doc["type"], data, request.current_user["id"])
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"transport": _transport_view(new, request.current_user)})
    return jsonify({"transport": _transport_view(doc, request.current_user, include_docs=True)})


@transport_bp.route("/api/transport/<tid>/status", methods=["POST"])
@require_login
def approve(tid):
    user = request.current_user
    if not is_admin(user):
        return jsonify({"error": "Only admins can approve transports."}), 403
    data = request.get_json() or {}
    status = data.get("status")
    if status not in ("APPROVED", "REJECTED"):
        return jsonify({"error": "Status must be APPROVED or REJECTED."}), 400
    doc = set_status(tid, status, data.get("reason"))
    return jsonify({"transport": _transport_view(doc, user)})


@transport_bp.route("/api/transport/search", methods=["GET"])
def search():
    origin = request.args.get("origin", "").strip()
    destination = request.args.get("destination", "").strip()
    ttype = request.args.get("type")
    docs = available_transports(origin, destination, ttype)
    return jsonify({"transports": [_transport_view(d, include_docs=True) for d in docs]})''',
    'tourist': r'''from flask import Blueprint, request, jsonify
from config import ROLES
from services.auth import (require_roles, require_login, is_admin,
                           require_approved_provider)
from services.tourist_service import (create_spot, update_spot, get_spot,
                                      list_spots, set_status,
                                      add_guide_location, list_guide_locations,
                                      create_tour, list_tours, get_tour,
                                      set_tour_status)
from services.mongodb import get_collection
from services.guide_service import browse_guides

tourist_bp = Blueprint("tourist", __name__)


@tourist_bp.route("/api/spots", methods=["GET"])
def spots():
    city = request.args.get("city")
    return jsonify({"spots": list_spots(city=city)})


@tourist_bp.route("/api/spots", methods=["POST"])
@require_approved_provider
def add_spot():
    if request.current_user["role"] != ROLES["TOURIST_SPOT_ADMIN"]:
        return jsonify({"error": "Only tourist spot admins can add spots."}), 403
    doc, err = create_spot(request.get_json() or {}, request.current_user["id"])
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"spot": doc}), 201


@tourist_bp.route("/api/spots/<sid>", methods=["GET", "PUT"])
@require_login
def spot(sid):
    if request.method == "PUT":
        if request.current_user["role"] != ROLES["TOURIST_SPOT_ADMIN"]:
            return jsonify({"error": "Not authorized."}), 403
        data = request.get_json() or {}
        data["spotId"] = sid
        doc, err = update_spot(data, request.current_user["id"])
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"spot": doc})
    doc = get_spot(sid)
    if not doc:
        return jsonify({"error": "Spot not found."}), 404
    return jsonify({"spot": doc})


@tourist_bp.route("/api/tours", methods=["GET", "POST"])
@require_login
def tours():
    if request.method == "POST":
        if request.current_user["role"] != ROLES["TOURIST_SPOT_ADMIN"]:
            return jsonify({"error": "Only tourist spot admins can add tours."}), 403
        if request.current_user.get("approvalStatus") != "APPROVED":
            return jsonify({"error": "Your provider account must be approved by the Admin."}), 403
        data = request.get_json() or {}
        doc, err = create_tour(data, request.current_user["id"])
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"tour": doc}), 201
    return jsonify({"tours": list_tours(
        spot_id=request.args.get("spotId"),
        city=request.args.get("city"))})


@tourist_bp.route("/api/tours/<tid>", methods=["GET"])
@require_login
def tour_detail(tid):
    doc = get_tour(tid)
    if not doc or doc.get("status") != "APPROVED":
        return jsonify({"error": "Tour not found."}), 404
    return jsonify({"tour": doc})


@tourist_bp.route("/api/spots/<sid>/status", methods=["POST"])
@require_login
def approve_spot(sid):
    user = request.current_user
    if not is_admin(user):
        return jsonify({"error": "Only admins can approve spots."}), 403
    status = (request.get_json() or {}).get("status")
    if status not in ("APPROVED", "REJECTED"):
        return jsonify({"error": "Status must be APPROVED or REJECTED."}), 400
    return jsonify({"spot": set_status(sid, status)})


@tourist_bp.route("/api/guide-locations", methods=["GET", "POST"])
@require_login
def guide_locations():
    user = request.current_user
    if request.method == "POST":
        if user["role"] != ROLES["TOURIST_SPOT_ADMIN"]:
            return jsonify({"error": "Only tourist spot admins can add guide locations."}), 403
        if user.get("approvalStatus") != "APPROVED":
            return jsonify({"error": "Your provider account must be approved by the Admin."}), 403
        doc, err = add_guide_location(user["id"], request.get_json() or {})
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"location": doc}), 201
    return jsonify({"locations": list_guide_locations(city=request.args.get("city"))})


@tourist_bp.route("/api/guides/browse", methods=["GET"])
def browse():
    return jsonify({"guides": browse_guides(
        location=request.args.get("location"),
        date=request.args.get("date"))})''',
    'guides': r'''from flask import Blueprint, request, jsonify
from config import ROLES
from services.auth import require_roles, require_login, require_approved_provider
from services.guide_service import (guide_profile, update_guide_profile,
                                    set_availability, set_pricing,
                                    browse_guides)

guide_bp = Blueprint("guide", __name__)


@guide_bp.route("/api/guide/profile", methods=["GET", "PUT"])
@require_approved_provider
def profile():
    uid = request.current_user["id"]
    if request.method == "PUT":
        if request.current_user["role"] != ROLES["GUIDE"]:
            return jsonify({"error": "Only guides can manage their profile."}), 403
        update_guide_profile(uid, request.get_json() or {})
    return jsonify(guide_profile(uid))


@guide_bp.route("/api/guide/availability", methods=["POST"])
@require_approved_provider
def availability():
    if request.current_user["role"] != ROLES["GUIDE"]:
        return jsonify({"error": "Only guides can set availability."}), 403
    doc, err = set_availability(request.current_user["id"], request.get_json() or {})
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"availability": doc})


@guide_bp.route("/api/guide/pricing", methods=["POST"])
@require_approved_provider
def pricing():
    if request.current_user["role"] != ROLES["GUIDE"]:
        return jsonify({"error": "Only guides can set pricing."}), 403
    doc, err = set_pricing(request.current_user["id"], request.get_json() or {})
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"pricing": doc})


@guide_bp.route("/api/guides", methods=["GET"])
def browse():
    return jsonify({"guides": browse_guides(
        location=request.args.get("location"),
        date=request.args.get("date"))})''',
    'hotel': r'''from flask import Blueprint, request, jsonify
from config import ROLES
from services.auth import require_login, require_approved_provider
from services.hotel_service import (create_hotel, update_hotel, get_hotel,
                                    search_hotels, list_my_hotels, occupancy,
                                    set_blocked_rooms, add_room,
                                    STANDARD_AMENITIES, BED_TYPES, HOTEL_CATEGORIES)
from services.booking_service import hotel_bookings

hotel_bp = Blueprint("hotel", __name__)


@hotel_bp.route("/api/hotel/meta", methods=["GET"])
def meta():
    return jsonify({"amenities": list(STANDARD_AMENITIES),
                    "bedTypes": list(BED_TYPES),
                    "categories": list(HOTEL_CATEGORIES)})


@hotel_bp.route("/api/hotels", methods=["POST"])
@require_approved_provider
def add_hotel():
    if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
        return jsonify({"error": "Only hotel admins can add hotels."}), 403
    doc, err = create_hotel(request.current_user, request.get_json() or {})
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"hotel": doc}), 201


@hotel_bp.route("/api/hotels/mine", methods=["GET"])
@require_login
def mine():
    if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
        return jsonify({"error": "Only hotel admins can view their hotels."}), 403
    return jsonify({"hotels": list_my_hotels(request.current_user)})


@hotel_bp.route("/api/hotels/search", methods=["GET"])
@require_login
def search():
    return jsonify({"hotels": search_hotels(
        city=request.args.get("city"),
        category=request.args.get("category"),
        ac=request.args.get("ac"),
        guests=request.args.get("guests"),
        name=request.args.get("name"))})


@hotel_bp.route("/api/hotels/<hid>", methods=["GET", "PUT"])
@require_login
def hotel(hid):
    if request.method == "PUT":
        if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
            return jsonify({"error": "Not authorized to edit hotels."}), 403
        doc, err = update_hotel(request.current_user, hid, request.get_json() or {})
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"hotel": doc})
    doc = get_hotel(hid)
    if not doc:
        return jsonify({"error": "Hotel not found."}), 404
    return jsonify({"hotel": doc})


@hotel_bp.route("/api/hotels/<hid>/occupancy", methods=["GET"])
@require_login
def occ(hid):
    if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
        return jsonify({"error": "Only hotel admins can view occupancy."}), 403
    data, err = occupancy(request.current_user, hid)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(data)


@hotel_bp.route("/api/hotels/<hid>/rooms", methods=["POST"])
@require_approved_provider
def room_add(hid):
    if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
        return jsonify({"error": "Only hotel admins can manage rooms."}), 403
    doc, err = add_room(request.current_user, hid, request.get_json() or {})
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"hotel": doc}), 201


@hotel_bp.route("/api/hotels/<hid>/room-types/<rtid>/block", methods=["POST"])
@require_login
def block(hid, rtid):
    if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
        return jsonify({"error": "Only hotel admins can manage rooms."}), 403
    doc, err = set_blocked_rooms(request.current_user, hid, rtid,
                                 (request.get_json() or {}).get("blocked", 0))
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"hotel": doc})


@hotel_bp.route("/api/hotels/bookings", methods=["GET"])
@require_login
def bookings():
    if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
        return jsonify({"error": "Only hotel admins can view their bookings."}), 403
    rows = hotel_bookings(request.current_user["id"])
    return jsonify({"bookings": rows})''',
    'restaurant': r'''"""Restaurant module routes (RESTAURANT_ADMIN role).

- Public catalogue: approved restaurants + available food items.
- Provider endpoints: create/update own restaurants and food items.
  Ownership is enforced server-side; only the owning RESTAURANT_ADMIN can
  modify a restaurant or its food items.
"""
from flask import Blueprint, request, jsonify
from services.auth import require_login, require_approved_provider
from services.restaurant_service import (
    create_restaurant, list_restaurants, my_restaurants, update_restaurant,
    list_food_items, add_food_item, update_food_item, delete_food_item,
)

restaurant_bp = Blueprint("restaurant", __name__)


def _owner():
    return request.current_user


@restaurant_bp.route("/api/restaurants", methods=["GET"])
@require_login
def get_restaurants():
    rows = list_restaurants(
        _owner(),
        city=request.args.get("city"),
        q=request.args.get("q"),
    )
    return jsonify({"restaurants": rows})


@restaurant_bp.route("/api/restaurants/mine", methods=["GET"])
@require_approved_provider
def get_mine():
    if request.current_user["role"] != "RESTAURANT_ADMIN":
        return jsonify({"error": "You do not have access to this resource."}), 403
    return jsonify({"restaurants": my_restaurants(request.current_user["id"])})


@restaurant_bp.route("/api/restaurants", methods=["POST"])
@require_approved_provider
def create():
    if request.current_user["role"] != "RESTAURANT_ADMIN":
        return jsonify({"error": "You do not have access to this resource."}), 403
    data = request.get_json(silent=True) or {}
    restaurant, err = create_restaurant(request.current_user["id"], data)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"restaurant": restaurant, "message": "Restaurant created."}), 201


@restaurant_bp.route("/api/restaurants/<rid>", methods=["GET"])
@require_login
def get_one(rid):
    restaurant = _existing_public(rid)
    if not restaurant:
        return jsonify({"error": "Restaurant not found."}), 404
    rows = list_food_items(rid, user=_owner(), only_available=True)
    return jsonify({"restaurant": restaurant, "foodItems": rows})


@restaurant_bp.route("/api/restaurants/<rid>", methods=["PUT"])
@require_approved_provider
def update(rid):
    if request.current_user["role"] != "RESTAURANT_ADMIN":
        return jsonify({"error": "You do not have access to this resource."}), 403
    data = request.get_json(silent=True) or {}
    restaurant, ok, err = update_restaurant(request.current_user["id"], rid, data)
    if not ok:
        return jsonify({"error": err or "Restaurant not found."}), (404 if "not found" in (err or "") else 400)
    return jsonify({"restaurant": restaurant, "message": "Restaurant updated."})


@restaurant_bp.route("/api/restaurants/<rid>/food-items", methods=["GET"])
@require_login
def get_food(rid):
    rows = list_food_items(
        rid,
        user=_owner(),
        only_available=request.current_user["role"] != "RESTAURANT_ADMIN",
    )
    return jsonify({"foodItems": rows})


@restaurant_bp.route("/api/restaurants/<rid>/food-items", methods=["POST"])
@require_approved_provider
def add_food(rid):
    if request.current_user["role"] != "RESTAURANT_ADMIN":
        return jsonify({"error": "You do not have access to this resource."}), 403
    data = request.get_json(silent=True) or {}
    item, err = add_food_item(request.current_user["id"], rid, data)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"foodItem": item, "message": "Food item added."}), 201


@restaurant_bp.route("/api/restaurants/<rid>/food-items/<fid>", methods=["PUT"])
@require_approved_provider
def update_food(rid, fid):
    if request.current_user["role"] != "RESTAURANT_ADMIN":
        return jsonify({"error": "You do not have access to this resource."}), 403
    data = request.get_json(silent=True) or {}
    item, ok, err = update_food_item(request.current_user["id"], rid, fid, data)
    if not ok:
        code = 404 if "not found" in (err or "") else 400
        return jsonify({"error": err or "Food item not found."}), code
    return jsonify({"foodItem": item, "message": "Food item updated."})


@restaurant_bp.route("/api/restaurants/<rid>/food-items/<fid>", methods=["DELETE"])
@require_approved_provider
def remove_food(rid, fid):
    if request.current_user["role"] != "RESTAURANT_ADMIN":
        return jsonify({"error": "You do not have access to this resource."}), 403
    err = delete_food_item(request.current_user["id"], rid, fid)
    if err:
        return jsonify({"error": err}), 404
    return jsonify({"message": "Food item removed."})


def _existing_public(rid):
    from services.mongodb import get_collection
    from services.restaurant_service import _public_restaurant
    d = get_collection("restaurants").find_one({"_id": str(rid), "status": "APPROVED"})
    return _public_restaurant(d) if d else None''',
    'bookings': r'''from flask import Blueprint, request, jsonify
from datetime import datetime
from config import ROLES, PROVIDER_ROLES
from services.auth import require_login, require_approved_provider, is_admin
from services.booking_service import (create_booking, cancel_booking, pay_booking,
                                      list_bookings, all_bookings,
                                      respond_guide_request, guide_bookings,
                                      provider_bookings)
from services.mongodb import get_collection

booking_bp = Blueprint("booking", __name__)


@booking_bp.route("/api/bookings", methods=["GET", "POST"])
@require_login
def bookings():
    user = request.current_user
    if request.method == "POST":
        doc, err = create_booking(request.get_json() or {}, user)
        if err:
            return jsonify({"error": err}), 400
        msg = ("Guide request sent. Awaiting guide confirmation."
               if doc["type"] == "GUIDE" else "Booking confirmed.")
        return jsonify({"booking": doc, "message": msg}), 201
    return jsonify({"bookings": list_bookings(user)})


@booking_bp.route("/api/bookings/all", methods=["GET"])
@require_login
def admin_all():
    if not is_admin(request.current_user):
        return jsonify({"error": "Admins only."}), 403
    return jsonify({"bookings": all_bookings()})


@booking_bp.route("/api/bookings/<bid>/pay", methods=["POST"])
@require_login
def pay(bid):
    doc = get_collection("bookings").find_one({"_id": bid})
    if not doc or str(doc.get("userId")) != request.current_user["id"]:
        return jsonify({"error": "Booking not found or not yours."}), 404
    updated, err = pay_booking(doc, request.current_user)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"booking": updated, "message": "Payment completed."})


@booking_bp.route("/api/bookings/<bid>", methods=["DELETE"])
@require_login
def cancel(bid):
    doc, err = cancel_booking(bid, request.current_user)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"booking": doc, "message": "Booking cancelled."})


@booking_bp.route("/api/provider/bookings", methods=["GET"])
@require_approved_provider
def provider_booking_list():
    """Bookings on resources owned by the provider (Transport → Upcoming
    Passengers, Hotel → Hotel Bookings, Tourist Spot → Experience bookings)."""
    btype = (request.args.get("type") or "").upper()
    if btype not in ("TRANSPORT", "HOTEL", "TOUR", "SPOT", "RESTAURANT"):
        return jsonify({"error": "Unsupported booking type."}), 400
    rows = provider_bookings(request.current_user["id"], btype)
    users = {}
    for row in rows:
        uid = str(row.get("userId") or "")
        if uid and uid not in users:
            u = get_collection("users").find_one({"_id": uid}, {"name": 1, "email": 1, "mobile": 1})
            users[uid] = {"name": (u or {}).get("name", ""),
                          "email": (u or {}).get("email", ""),
                          "mobile": (u or {}).get("mobile", "")}
        row["customer"] = users.get(uid, {})
    return jsonify({"bookings": rows})


@booking_bp.route("/api/guide/requests", methods=["GET"])
@require_login
def guide_requests():
    if request.current_user["role"] != ROLES["GUIDE"]:
        return jsonify({"error": "Only guides can view requests."}), 403
    rows = guide_bookings(request.current_user["id"])
    return jsonify({"requests": [b for b in rows if b.get("status") == "PENDING"]})


@booking_bp.route("/api/guide/requests/<bid>", methods=["POST"])
@require_login
def guide_respond(bid):
    if request.current_user["role"] != ROLES["GUIDE"]:
        return jsonify({"error": "Only guides can respond to requests."}), 403
    data = request.get_json() or {}
    doc, err = respond_guide_request(bid, request.current_user["id"],
                                     data.get("action"), data.get("message") or "")
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"booking": doc, "message": "Request handled."})


@booking_bp.route("/api/guide/assignments", methods=["GET"])
@require_login
def guide_assignments():
    if request.current_user["role"] != ROLES["GUIDE"]:
        return jsonify({"error": "Only guides can view assignments."}), 403
    rows = guide_bookings(request.current_user["id"])
    today = datetime.utcnow().strftime("%Y-%m-%d")
    upcoming = [b for b in rows if b.get("status") == "CONFIRMED" and (b.get("date") or "") >= today]
    completed = [b for b in rows if b.get("status") in ("CONFIRMED", "COMPLETED")
                 and (b.get("date") or "") < today]
    return jsonify({"upcoming": upcoming, "completed": completed})''',
    'admin': r'''from collections import Counter
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from config import PROVIDER_ROLES
from services.auth import require_admin
from services.mongodb import get_collection
from services.transport_service import list_transports

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/api/admin/stats", methods=["GET"])
@require_admin
def stats():
    users = list(get_collection("users").find())
    bookings = list(get_collection("bookings").find())
    trips = list(get_collection("trips").find())
    transports = list_transports(approved_only=False)
    spots = list(get_collection("tourist_spots").find())
    hotels = list(get_collection("hotels").find())
    tours = list(get_collection("tours").find())

    role_count = Counter(u.get("role", "USER") for u in users)
    status_count = Counter(t.get("status") for t in transports)
    spot_status = Counter(s.get("status") for s in spots)
    hotel_status = Counter(h.get("status") for h in hotels)
    tour_status = Counter(t.get("status") for t in tours)
    booking_status = Counter(b.get("status") for b in bookings)
    trip_status = Counter(t.get("status") for t in trips)
    provider_approval = Counter(
        u.get("approvalStatus", "APPROVED" if u.get("approved") else "PENDING")
        for u in users if u.get("role") in PROVIDER_ROLES)

    now = datetime.utcnow()
    now_str = now.strftime("%Y-%m-%d")
    revenue = sum(b.get("total") or 0 for b in bookings if b.get("status") == "CONFIRMED")

    # Trip completion is a property of the trip itself: a trip is complete when
    # its status is COMPLETED, or when a BOOKED trip's end date has passed.
    completed_trips = [t for t in trips
                       if t.get("status") == "COMPLETED"
                       or (t.get("status") == "BOOKED"
                           and (t.get("endDate") or "")[:10] < now_str)]
    trips_by_month = {}
    for i in range(11, -1, -1):
        idx = now.year * 12 + (now.month - 1) - i
        y, m = divmod(idx, 12)
        trips_by_month["%04d-%02d" % (y, m + 1)] = 0
    for t in completed_trips:
        key = ((t.get("completedAt") or t.get("endDate") or "")[:7])
        if key in trips_by_month:
            trips_by_month[key] += 1

    pending_provider = sum(1 for u in users if u.get("approvalStatus") == "PENDING")
    pending_content = (sum(1 for t in transports if t.get("status") == "PENDING")
                       + sum(1 for s in spots if s.get("status") == "PENDING")
                       + sum(1 for h in hotels if h.get("status") == "PENDING")
                       + sum(1 for t in tours if t.get("status") == "PENDING"))

    return jsonify({
        "users": len(users),
        "roles": dict(role_count),
        "providerApproval": dict(provider_approval),
        "trips": len(trips),
        "tripStatus": dict(trip_status),
        "bookings": len(bookings),
        "bookingStatus": dict(booking_status),
        "revenue": round(revenue, 2),
        "tripsCompletedTotal": len(completed_trips),
        "tripsCompletedByMonth": trips_by_month,
        "transports": len(transports),
        "transportStatus": dict(status_count),
        "transportTypes": dict(Counter(t.get("type") for t in transports)),
        "spots": len(spots),
        "spotStatus": dict(spot_status),
        "hotels": len(hotels),
        "hotelStatus": dict(hotel_status),
        "tours": len(tours),
        "tourStatus": dict(tour_status),
        "pendingApprovals": pending_provider + pending_content,
    })


def _owner_name(owner_id):
    u = get_collection("users").find_one({"_id": owner_id}, {"name": 1, "email": 1})
    if not u:
        return "Unknown"
    return u.get("name") or u.get("email") or "Unknown"


RESOURCE_COLLECTIONS = {"transport": "transports", "spot": "tourist_spots",
                        "hotel": "hotels", "tour": "tours", "restaurant": "restaurants"}


DETAIL_FIELDS = {
    "transport": ("busNumber", "trainNumber", "trainName", "flightNumber",
                  "vehicleNumber", "boardingPoint", "droppingPoint", "boardingTime",
                  "droppingTime", "departureAirport", "arrivalAirport",
                  "totalSeats", "sleeperSeats", "seaterSeats", "route", "fare"),
    "spot": ("category", "city", "address", "entryFee", "openingTime",
             "closingTime", "description", "rating"),
    "hotel": ("category", "city", "state", "address", "starRating", "totalRooms",
              "checkInTime", "checkOutTime", "contactNumber", "email", "amenities", "description"),
    "tour": ("category", "city", "price", "duration", "description"),
    "restaurant": ("restaurantType", "city", "address", "contactNumber", "email",
                   "operatingDays", "description"),
}


def _detail(doc, kind):
    detail = {}
    for f in DETAIL_FIELDS.get(kind, ()):
        if doc.get(f) is not None:
            detail[f] = doc[f]
    if doc.get("documents"):
        detail["documents"] = doc["documents"]
    if doc.get("images"):
        detail["images"] = doc["images"]
    return detail


@admin_bp.route("/api/admin/content-review", methods=["GET"])
@require_admin
def content_review():
    rows = []
    for kind, coll in RESOURCE_COLLECTIONS.items():
        for d in get_collection(coll).find({"status": "PENDING"}):
            rows.append({
                "kind": kind,
                "id": str(d["_id"]),
                "name": d.get("name") or d.get("serviceName") or d.get("trainName") or d.get("busNumber") or "Unnamed",
                "ownerId": d.get("ownerId"),
                "ownerName": _owner_name(d.get("ownerId")),
                "category": d.get("category") or d.get("type") or "",
                "createdAt": (d.get("createdAt") or "")[:19].replace("T", " "),
                "details": _detail(d, kind),
            })
    return jsonify({"pending": rows})


@admin_bp.route("/api/admin/content/<kind>/<resource_id>/review", methods=["POST"])
@require_admin
def review_content(kind, resource_id):
    coll = RESOURCE_COLLECTIONS.get(kind)
    if not coll:
        return jsonify({"error": "Unknown resource kind."}), 400
    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").upper()
    if action not in ("APPROVE", "REJECT"):
        return jsonify({"error": "action must be APPROVE or REJECT."}), 400
    reason = (body.get("reason") or "").strip()
    if action == "REJECT" and not reason:
        return jsonify({"error": "A rejection reason is required."}), 400
    new_status = "APPROVED" if action == "APPROVE" else "REJECTED"
    update = {"status": new_status, "reviewedAt": datetime.utcnow().isoformat()}
    if reason:
        update["rejectionReason"] = reason
    result = get_collection(coll).update_one({"_id": resource_id}, {"$set": update})
    if not result.matched_count:
        return jsonify({"error": "Resource not found."}), 404
    return jsonify({"ok": True, "kind": kind, "id": resource_id,
                    "status": new_status})


@admin_bp.route("/api/admin/availability", methods=["GET"])
@require_admin
def availability():
    """Aggregate availability across guides, hotels, transport and spots so the
    Admin can see live slot/room/seat position at a glance."""
    guides = []
    user_by_id = {}
    for u in get_collection("users").find({"role": "GUIDE"}):
        user_by_id[u["_id"]] = u
        guides.append({"id": str(u["_id"]), "name": u.get("name"), "email": u.get("email"),
                       "locations": (u.get("profile", {}) or {}).get("locations", []),
                       "approvalStatus": u.get("approvalStatus", "APPROVED"),
                       "availableDates": []})

    av_slots = list(get_collection("guide_availability").find({"guideId": {"$in": list(user_by_id.keys())}}))
    by_guide = {}
    for a in av_slots:
        by_guide.setdefault(a["guideId"], []).append(a)
    for g in guides:
        slots = by_guide.get(g["id"], [])
        g["availableDates"] = sorted({str(s.get("date")) for s in slots if s.get("date")})
        g["slotCount"] = sum(len(s.get("slots") or []) for s in slots)

    hotels = []
    for h in get_collection("hotels").find():
        rooms = h.get("roomTypes") or []
        free = sum(max(0, r.get("totalRooms", 0) - r.get("bookedRooms", 0) - r.get("blockedRooms", 0)) for r in rooms)
        hotels.append({"id": str(h["_id"]), "name": h.get("name"), "city": h.get("city"),
                       "status": h.get("status", "APPROVED"), "totalRooms": h.get("totalRooms", 0),
                       "freeRooms": free, "roomTypes": len(rooms)})

    transports = []
    for t in get_collection("transports").find():
        seats = t.get("seatState") or {}
        free = int(seats.get("freeSeats") or 0)
        if not free and t.get("type") in ("BUS", "TRAIN", "FLIGHT"):
            free = int(t.get("totalSeats") or 0) - int(t.get("bookedSeats") or 0)
        transports.append({"id": str(t["_id"]), "type": t.get("type"), "name":
                           t.get("serviceName") or t.get("trainName") or t.get("busNumber"),
                           "route": (t.get("boardingPoint") or t.get("departureAirport") or "—"),
                           "status": t.get("status", "APPROVED"), "freeSeats": max(0, free)})

    spots = []
    for s in get_collection("tourist_spots").find():
        spots.append({"id": str(s["_id"]), "name": s.get("name"), "city": s.get("city"),
                      "category": s.get("category") or "", "status": s.get("status", "APPROVED"),
                      "entryFee": s.get("entryFee"), "openingTime": s.get("openingTime"),
                      "closingTime": s.get("closingTime")})

    return jsonify({"guides": guides, "hotels": hotels,
                    "transports": transports, "spots": spots})''',
    'ml': r'''"""ML service routes: recommender endpoints, content-based similar items,
cost/time prediction, clusters/segments, demand, anomalies, visit times,
personalized trip ranking and the admin train/status entry points."""
from flask import Blueprint, request, jsonify, current_app

from services.mongodb import get_collection
from services.auth import current_user, require_admin
from services.ml import registry, inference

ml_bp = Blueprint("ml", __name__)


def _user():
    try:
        return current_user(allow_demo=False)
    except Exception:
        return None


def _uid(user):
    if not user:
        return None
    return user.get("id") or user.get("_id") or None


@ml_bp.route("/api/ml/status", methods=["GET"])
def status():
    return jsonify({"enabled": True,
                    "models": registry.complete_registry(),
                    "trainedAt": registry.last_trained_at()})


@ml_bp.route("/api/ml/recommend/spots", methods=["GET"])
def recommend_spots():
    user = _uid(_user())
    city = request.args.get("city")
    interests = [i for i in (request.args.get("interests") or "").split(",") if i]
    limit = int(request.args.get("limit") or 10)
    return jsonify(inference.spots(user, limit=limit, city=city, interests=interests))


@ml_bp.route("/api/ml/recommend/hotels", methods=["GET"])
def recommend_hotels():
    user = _uid(_user())
    city = request.args.get("city")
    limit = int(request.args.get("limit") or 8)
    return jsonify(inference.hotels(user, city=city, limit=limit))


@ml_bp.route("/api/ml/recommend/transports", methods=["GET"])
def recommend_transports():
    user = _uid(_user())
    origin = request.args.get("origin") or ""
    destination = request.args.get("destination") or ""
    pref = request.args.get("type")
    limit = int(request.args.get("limit") or 8)
    return jsonify(inference.transports(user, origin, destination, pref, limit))


@ml_bp.route("/api/ml/recommend/guides", methods=["GET"])
def recommend_guides():
    user = _uid(_user())
    location = request.args.get("location")
    interests = [i for i in (request.args.get("interests") or "").split(",") if i]
    limit = int(request.args.get("limit") or 8)
    return jsonify(inference.guides(user, location=location,
                                    interests=interests, limit=limit))


@ml_bp.route("/api/ml/similar", methods=["GET"])
def similar():
    kind = request.args.get("kind")
    target_id = request.args.get("targetId")
    taste = request.args.get("taste")
    limit = int(request.args.get("limit") or 6)
    return jsonify(inference.similar_items(kind, target_id=target_id,
                                           taste_text=taste, limit=limit))


@ml_bp.route("/api/ml/predict/cost", methods=["GET"])
def predict_cost():
    trip_id = request.args.get("tripId")
    trip = None
    if trip_id:
        trip = get_collection("trips").find_one({"_id": trip_id})
        if not trip:
            trip = get_collection("trips").find_one({"tripId": trip_id})
    return jsonify(inference.cost(user=_uid(_user()), trip=trip))


@ml_bp.route("/api/ml/predict/time", methods=["GET"])
def predict_time():
    item_type = request.args.get("itemType")
    origin = request.args.get("origin")
    destination = request.args.get("destination")
    return jsonify(inference.travel_time(item_type, origin, destination))


@ml_bp.route("/api/ml/clusters", methods=["GET"])
def clusters():
    return jsonify(inference.spot_clusters())


@ml_bp.route("/api/ml/segments", methods=["GET"])
def segments():
    return jsonify(inference.user_segments())


@ml_bp.route("/api/ml/affinity", methods=["GET"])
def affinity():
    user = _uid(_user())
    item_id = request.args.get("itemId")
    return jsonify(inference.affinity(user, item_id))


@ml_bp.route("/api/ml/demand", methods=["GET"])
def demand():
    days = int(request.args.get("days") or 7)
    return jsonify(inference.forecast(days=days))


@ml_bp.route("/api/ml/anomalies", methods=["GET"])
@require_admin
def anomalies():
    limit = int(request.args.get("limit") or 30)
    return jsonify(inference.anomalies(limit=limit))


@ml_bp.route("/api/ml/visit-times", methods=["GET"])
def visit_times():
    spot_id = request.args.get("spotId")
    if not spot_id:
        return jsonify({"error": "spotId required."}), 400
    return jsonify(inference.visit_times(spot_id))


@ml_bp.route("/api/ml/trip-rank", methods=["POST"])
def trip_rank():
    payload = request.get_json(silent=True) or {}
    return jsonify(inference.rank_trip(payload.get("plans") or [],
                                       request_data=payload.get("requestData") or {}))


@ml_bp.route("/api/admin/ml/train", methods=["POST"])
@require_admin
def train():
    from services.ml.train import train_all
    try:
        summary = train_all()
        registry.mark_trained(summary["trainedAt"])
        return jsonify({"ok": True, "summary": summary})
    except Exception as exc:
        current_app.logger.exception("ML training failed")
        return jsonify({"error": f"Training failed: {exc}"}), 500''',
    'ratings': r'''"""Ratings + trip-reviews routes (merged from the former separate blueprints).

- Booking ratings: user-only — eligible bookings, create rating, list mine,
  and per-service stats used by catalogue cards.
- Trip reviews: public read of a trip's reviews, login to add one.
"""
from flask import Blueprint, request, jsonify

from services.auth import require_roles, require_login
from config import ROLES
from services import reviews

ratings_bp = Blueprint("ratings", __name__)


@ratings_bp.route("/api/ratings/eligible", methods=["GET"])
@require_roles(ROLES["USER"], ROLES["ADMIN"])
def eligible():
    return jsonify({"bookings": reviews.eligible_bookings(request.current_user)})


@ratings_bp.route("/api/ratings", methods=["GET"])
@require_roles(ROLES["USER"], ROLES["ADMIN"])
def mine():
    return jsonify({"ratings": reviews.my_ratings(request.current_user)})


@ratings_bp.route("/api/ratings", methods=["POST"])
@require_roles(ROLES["USER"], ROLES["ADMIN"])
def create():
    rating, err = reviews.add_rating(request.current_user, request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"rating": rating}), 201


@ratings_bp.route("/api/ratings/service", methods=["GET"])
def service_stats():
    service_type = (request.args.get("type") or "").upper()
    service_id = request.args.get("id")
    if not service_id:
        return jsonify({"error": "id required."}), 400
    return jsonify(reviews.service_stats(service_type, service_id))


@ratings_bp.route("/api/trips/<trip_id>/reviews", methods=["GET"])
def trip_reviews(trip_id):
    return jsonify({"reviews": reviews.get_trip_reviews(trip_id)})


@ratings_bp.route("/api/trips/<trip_id>/review", methods=["POST"])
@require_login
def add_review(trip_id):
    data = request.get_json() or {}
    review, err = reviews.add_trip_review(
        request.current_user, trip_id,
        data.get("rating"), data.get("comment"))
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"review": review}), 201''',
    'analytics': r'''"""Provider dashboards: genuine aggregates computed from the database.

Each provider role sees real numbers for their own catalogue and bookings
(counts, revenue, status breakdowns) — nothing mocked.
"""
from flask import Blueprint, jsonify, request
from services.auth import require_login
from services.mongodb import get_collection

analytics_bp = Blueprint("analytics", __name__)


def _sum(rows, *keys):
    total = 0
    for r in rows:
        for k in keys:
            v = r.get(k)
            if isinstance(v, (int, float)):
                total += v
    return round(total, 2)


@analytics_bp.route("/api/provider/stats", methods=["GET"])
@require_login
def provider_stats():
    user = request.current_user
    role = user["role"]
    uid = user["id"]
    out = {"role": role}

    if role == "TRANSPORT_ADMIN":
        fleet = list(get_collection("transports").find({"ownerId": uid}))
        ids = {str(t["_id"]) for t in fleet}
        bookings = list(get_collection("bookings").find(
            {"type": "TRANSPORT", "transportId": {"$in": list(ids)}}))
        confirmed = [b for b in bookings if b.get("status") == "CONFIRMED"]
        today_str = str(datetime_date())
        trip_ids = {b.get("tripId") for b in bookings if b.get("tripId")}
        completed = 0
        if trip_ids:
            completed = get_collection("trips").count_documents(
                {"_id": {"$in": list(trip_ids)}, "status": "COMPLETED"})
        out.update({
            "fleet": len(fleet),
            "approvedFleet": sum(1 for t in fleet if t.get("status") == "APPROVED"),
            "pendingFleet": sum(1 for t in fleet if t.get("status") == "PENDING"),
            "bookings": len(bookings),
            "confirmedBookings": len(confirmed),
            "upcomingBookings": sum(1 for b in confirmed if (b.get("date") or "") >= today_str),
            "completedTrips": completed,
            "revenue": _sum(confirmed, "total"),
            "seatsBooked": sum(int(b.get("qty") or 1) for b in confirmed),
            "fleetCapacity": sum(
                (int(t.get("totalSeats") or 0) or
                 sum(int(c.get("coachCount") or 0) * int(c.get("capacityPerCoach") or 0)
                     for c in (t.get("coaches") or [])) or
                 sum(int(c.get("seats") or 0) for c in (t.get("classes") or [])) or
                 int(t.get("seatingCapacity") or 0)) for t in fleet),
        })

    elif role == "TOURIST_SPOT_ADMIN":
        spots = list(get_collection("tourist_spots").find({"ownerId": uid}))
        spot_ids = {str(s["_id"]) for s in spots}
        tours = list(get_collection("tours").find({"ownerId": uid}))
        tour_ids = {str(t["_id"]) for t in tours}
        spot_bookings = list(get_collection("bookings").find(
            {"type": "SPOT", "spotId": {"$in": list(spot_ids)}}))
        tour_bookings = list(get_collection("bookings").find(
            {"type": "TOUR", "tourId": {"$in": list(tour_ids)}}))
        out.update({
            "spots": len(spots),
            "approvedSpots": sum(1 for s in spots if s.get("status") == "APPROVED"),
            "pendingSpots": sum(1 for s in spots if s.get("status") == "PENDING"),
            "tours": len(tours),
            "spotBookings": len(spot_bookings),
            "tourBookings": len(tour_bookings),
            "revenue": _sum(spot_bookings, "total") + _sum(tour_bookings, "total"),
            "spotVisits": sum(int(b.get("qty") or 1) for b in spot_bookings),
        })

    elif role == "HOTEL_ADMIN":
        hotels = list(get_collection("hotels").find({"ownerId": uid}))
        hotel_ids = {str(h["_id"]) for h in hotels}
        bookings = list(get_collection("bookings").find(
            {"type": "HOTEL", "hotelId": {"$in": list(hotel_ids)}}))
        confirmed = [b for b in bookings if b.get("status") == "CONFIRMED"]
        total_rooms = sum(int(h.get("totalRooms") or 0) for h in hotels)
        booked_rooms = sum(
            sum(int(rt.get("bookedRooms") or 0) for rt in (h.get("roomTypes") or []))
            for h in hotels)
        out.update({
            "hotels": len(hotels),
            "approvedHotels": sum(1 for h in hotels if h.get("status") == "APPROVED"),
            "pendingHotels": sum(1 for h in hotels if h.get("status") == "PENDING"),
            "totalRooms": total_rooms,
            "roomsOccupied": booked_rooms,
            "occupancyPct": round(booked_rooms / total_rooms * 100, 1) if total_rooms else 0,
            "bookings": len(bookings),
            "confirmedBookings": len(confirmed),
            "revenue": _sum(confirmed, "total"),
        })

    elif role == "GUIDE":
        profile = get_collection("users").find_one({"_id": uid})
        pricing = list(get_collection("guide_pricing").find({"guideId": uid}))
        monthly_hourly = pricing[0].get("pricePerHour") or 0 if pricing else 0
        bookings = list(get_collection("bookings").find({"guideId": uid}))
        confirmed = [b for b in bookings if b.get("status") == "CONFIRMED"]
        upcoming = [b for b in confirmed if (b.get("date") or "") >= str(datetime_date())]
        aday = list(get_collection("guide_availability").find({"guideId": uid}))
        distinct_days = {d.get("date")
                         for a in aday for d in (a.get("days") or []) if d.get("date")}
        out.update({
            "assignments": len(confirmed),
            "completed": sum(1 for b in bookings if b.get("status") == "COMPLETED"),
            "pendingRequests": sum(1 for b in bookings if b.get("status") == "PENDING"),
            "upcoming": len(upcoming),
            "earnings": _sum(confirmed, "total") + _sum([b for b in bookings if b.get("status") == "COMPLETED"], "total"),
            "availableDays": len(distinct_days),
            "pricingPerHour": monthly_hourly,
            "specialty": (profile.get("profile") or {}).get("specialty") or "",
        })

    elif role == "RESTAURANT_ADMIN":
        restaurants = list(get_collection("restaurants").find({"ownerId": uid}))
        rid = {str(r["_id"]) for r in restaurants}
        food = list(get_collection("food_items").find(
            {"restaurantId": {"$in": list(rid)}}))
        food_ids = {str(f["_id"]) for f in food}
        bookings = list(get_collection("bookings").find(
            {"type": "RESTAURANT", "restaurantId": {"$in": list(rid)}}))
        confirmed = [b for b in bookings if b.get("status") == "CONFIRMED"]
        orders = list(get_collection("bookings").find(
            {"type": "FOOD", "foodItemId": {"$in": list(food_ids)}}))
        out.update({
            "restaurants": len(restaurants),
            "foodItems": len(food),
            "availableItems": sum(1 for f in food if f.get("available", True)),
            "bookings": len(bookings),
            "orders": len(orders),
            "confirmedOrders": sum(1 for o in orders if o.get("status") == "CONFIRMED"),
            "revenue": _sum(confirmed, "total") + _sum([o for o in orders if o.get("status") == "CONFIRMED"], "total"),
        })

    elif role == "USER":
        bookings = list(get_collection("bookings").find({"userId": uid}))
        trips = list(get_collection("trips").find({"userId": uid}))
        out.update({
            "bookings": len(bookings),
            "bookedTrips": sum(1 for t in trips if t.get("status") == "BOOKED"),
            "plannedTrips": sum(1 for t in trips if t.get("status") == "PLANNED"),
            "completedTrips": sum(1 for t in trips if t.get("status") == "COMPLETED"),
            "spent": _sum([b for b in bookings
                           if b.get("status") in ("CONFIRMED", "COMPLETED")], "total"),
        })

    return jsonify(out)


def datetime_date():
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m-%d")''',
    'wallet': r'''from flask import Blueprint, request, jsonify
from services.auth import require_login
from services.wallet_service import get_wallet, credit


wallet_bp = Blueprint("wallet", __name__)


def _view(w):
    txns = sorted(w.get("transactions") or [], key=lambda t: t.get("createdAt", ""), reverse=True)
    return {
        "walletId": str(w["_id"]),
        "balance": round(float(w.get("balance") or 0), 2),
        "totalDeposited": round(float(w.get("totalDeposited") or 0), 2),
        "totalSpent": round(float(w.get("totalSpent") or 0), 2),
        "currency": w.get("currency", "INR"),
        "transactions": txns,
    }


@wallet_bp.route("/api/wallet", methods=["GET"])
@require_login
def wallet_view():
    return jsonify(_view(get_wallet(request.current_user["id"])))


@wallet_bp.route("/api/wallet/deposit", methods=["POST"])
@require_login
def wallet_deposit():
    amount = (request.get_json() or {}).get("amount")
    wallet, err = credit(request.current_user["id"], amount, description="Wallet top-up")
    if err:
        return jsonify({"error": err}), 400
    return jsonify(_view(wallet))''',
    'tickets': r'''"""Ticket endpoints: printable PDF ticket download and QR verification.

- GET /api/bookings/<id>/ticket  -> PDF (owner or Admin only)
- GET /api/tickets/verify/<token> -> public, no PII, status-only assertion
"""
from flask import Blueprint, Response, jsonify, request

from services.auth import require_login, is_admin
from services.mongodb import get_collection
from services.ticket_service import (build_ticket_pdf, issue_token, verify_token,
                                     is_trip_token, verify_trip_token)

ticket_bp = Blueprint("tickets", __name__)


@ticket_bp.route("/api/bookings/<bid>/token", methods=["GET"])
@require_login
def booking_token(bid):
    booking = get_collection("bookings").find_one({"_id": bid})
    if not booking:
        return jsonify({"error": "Booking not found."}), 404
    if str(booking.get("userId")) != str(request.current_user.get("id")) \
            and not is_admin(request.current_user):
        return jsonify({"error": "Not authorized."}), 403
    return jsonify({"token": issue_token(booking)})


@ticket_bp.route("/api/bookings/<bid>/ticket", methods=["GET"])
@require_login
def booking_ticket(bid):
    booking = get_collection("bookings").find_one({"_id": bid})
    if not booking:
        return jsonify({"error": "Booking not found."}), 404
    if str(booking.get("userId")) != str(request.current_user.get("id")) \
            and not is_admin(request.current_user):
        return jsonify({"error": "Not authorized to view this ticket."}), 403
    try:
        pdf = build_ticket_pdf(booking)
    except Exception:
        return jsonify({"error": "Could not generate the ticket."}), 500
    ref = booking.get("reference") or "ticket"
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition":
                 'attachment; filename="TripMind-ticket-%s.pdf"' % ref})


@ticket_bp.route("/api/tickets/verify/<token>", methods=["GET"])
def verify_ticket(token):
    token = token or ""
    if is_trip_token(token):
        trip, err = verify_trip_token(token)
        if err:
            return jsonify({"valid": False, "reason": err, "kind": "TRIP"})
        return jsonify({
            "valid": True,
            "kind": "TRIP",
            "status": trip.get("status"),
            "reference": trip.get("reference"),
            "route": "%s -> %s" % ((trip.get("origin") or "-"), (trip.get("destination") or "-")),
            "tripId": str(trip["_id"]),
        })
    booking, err = verify_token(token)
    if err:
        return jsonify({"valid": False, "reason": err, "kind": "BOOKING"})
    return jsonify({
        "valid": True,
        "kind": "BOOKING",
        "status": booking.get("status"),
        "reference": booking.get("reference"),
        "type": booking.get("type"),
        "date": booking.get("date"),
    })''',
}


_PARENT = sys.modules[__name__]
_ALIASES = {}
for _n in _SRC:
    _m = types.ModuleType("routes." + _n)
    _m.__package__ = "routes"
    sys.modules["routes." + _n] = _m
    _ALIASES[_n] = _m
    setattr(_PARENT, _n, _m)
for _n in _SRC:
    _code = compile(_SRC[_n], 'routes.' + _n, 'exec')
    exec(_code, _ALIASES[_n].__dict__)
del _SRC, _PARENT, _ALIASES, _m, _n, _code
