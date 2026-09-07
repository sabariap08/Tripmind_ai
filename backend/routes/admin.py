from collections import Counter
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
                    "transports": transports, "spots": spots})