import uuid
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
