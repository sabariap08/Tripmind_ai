"""Provider dashboards: genuine aggregates computed from the database.

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
    return datetime.utcnow().strftime("%Y-%m-%d")