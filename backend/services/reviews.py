"""Reviews data layer (merged from the former ratings_service + trip_review_service).

Two kinds of reviews:
- Booking ratings (`ratings`): users rate bookings they actually made (not
  cancelled). Feeds the ML feedback loop (reco._rating_stats + collab).
- Trip reviews (`trip_reviews`): users rate an entire AI-planned trip.

Eligibility is always derived server-side — the API never accepts a rating for
a booking/trip the user doesn't own.
"""
from datetime import datetime
from bson.objectid import ObjectId
from services.mongodb import get_collection

RATEABLE = {"TRANSPORT", "TOUR", "HOTEL", "GUIDE", "SPOT", "RESTAURANT"}


def _id():
    return str(ObjectId())


# --- Booking ratings --------------------------------------------------------

def service_id_of(booking):
    for key in ("transportId", "spotId", "hotelId", "tourId", "guideId", "restaurantId"):
        if booking.get(key):
            return str(booking[key]), key
    return None, None


def eligible_bookings(user):
    """Bookings this user can still rate (not cancelled, not yet rated)."""
    bookings = list(get_collection("bookings").find(
        {"userId": user["id"], "status": {"$nin": ("CANCELLED", "REJECTED")}}
    ).sort("createdAt", -1))
    rated = {r["bookingId"] for r in
             get_collection("ratings").find({"userId": user["id"]}, ["bookingId"])}
    rows = []
    for b in bookings:
        if str(b["_id"]) in rated:
            continue
        sid, key = service_id_of(b)
        if not sid:
            continue
        rows.append({
            "bookingId": str(b["_id"]),
            "reference": b.get("reference"),
            "type": b.get("type"),
            "status": b.get("status"),
            "date": b.get("date"),
            "total": b.get("total"),
            "serviceId": sid,
            "serviceName": _service_name(b, sid, key),
        })
    return rows


def my_ratings(user):
    rows = list(get_collection("ratings").find({"userId": user["id"]})
                .sort("createdAt", -1))
    return [_rating_public(r) for r in rows]


def add_rating(user, data):
    booking_id = str(data.get("bookingId") or "")
    rating = data.get("rating")
    comment = (data.get("comment") or "").strip()[:500]
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return None, "Rating must be a whole number."
    if rating < 1 or rating > 5:
        return None, "Rating must be between 1 and 5."
    if comment and len(comment) < 2:
        return None, "Comment is too short."

    booking = get_collection("bookings").find_one({"_id": booking_id})
    if not booking or str(booking.get("userId")) != user["id"]:
        return None, "Booking not found or not yours."
    if booking.get("status") in ("CANCELLED", "REJECTED"):
        return None, "Cancelled or rejected bookings cannot be rated."
    sid, key = service_id_of(booking)
    if not sid:
        return None, "This booking has no rateable service."
    if booking.get("type") not in RATEABLE:
        return None, f"'{booking.get('type')}' bookings are not rateable."

    if get_collection("ratings").find_one({"bookingId": booking_id}):
        return None, "This booking has already been rated."

    doc = {
        "_id": _id(),
        "userId": user["id"],
        "bookingId": booking_id,
        "reference": booking.get("reference"),
        "serviceType": booking.get("type"),
        "serviceId": sid,
        key: sid,
        "rating": rating,
        "comment": comment,
        "createdAt": datetime.utcnow().isoformat(),
    }
    get_collection("ratings").insert_one(doc)
    return _rating_public(doc), None


def service_stats(service_type, service_id):
    pipeline = [
        {"$match": {"serviceType": service_type, "serviceId": str(service_id)}},
        {"$group": {"_id": None,
                    "avg": {"$avg": "$rating"},
                    "count": {"$sum": 1}}},
    ]
    rows = list(get_collection("ratings").aggregate(pipeline))
    if not rows:
        return {"avg": None, "count": 0}
    return {"avg": round(rows[0]["avg"], 1), "count": rows[0]["count"]}


def _service_name(booking, sid, key):
    coll = {"transportId": "transports", "spotId": "tourist_spots",
            "hotelId": "hotels", "tourId": "tours", "guideId": "users",
            "restaurantId": "restaurants"}.get(key)
    if not coll or not sid:
        return booking.get("type", "")
    d = get_collection(coll).find_one({"_id": sid})
    if not d:
        return booking.get("type", "")
    return d.get("name") or d.get("serviceName") or booking.get("type", "")


def _rating_public(r):
    return {
        "id": str(r["_id"]),
        "bookingId": r.get("bookingId"),
        "reference": r.get("reference"),
        "serviceType": r.get("serviceType"),
        "serviceId": r.get("serviceId"),
        "rating": r.get("rating"),
        "comment": r.get("comment"),
        "createdAt": r.get("createdAt"),
    }


# --- Trip reviews -----------------------------------------------------------

def add_trip_review(user, trip_id, rating, comment=""):
    """Add a review for a booked trip. Returns (review, error)."""
    try:
        rating = int(rating or 0)
    except (TypeError, ValueError):
        return None, "Rating must be a whole number."
    if not (1 <= rating <= 5):
        return None, "Rating must be between 1 and 5."
    comment = (comment or "").strip()[:1000]
    if comment and len(comment) < 3:
        return None, "Comment is too short."

    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip or str(trip.get("userId")) != str(user["id"]):
        return None, "Trip not found or not yours."
    if trip.get("status") not in ("BOOKED", "PLANNED"):
        return None, "You can only review booked or planned trips."
    existing = get_collection("trip_reviews").find_one(
        {"tripId": trip_id, "userId": user["id"]})
    if existing:
        return None, "You have already reviewed this trip."

    review = {
        "_id": _id(),
        "userId": user["id"],
        "userName": user.get("name") or "Anonymous",
        "tripId": trip_id,
        "origin": trip.get("origin"),
        "destination": trip.get("destination"),
        "rating": rating,
        "comment": comment,
        "createdAt": datetime.utcnow().isoformat(),
    }
    get_collection("trip_reviews").insert_one(review)
    return _trip_review_public(review), None


def get_trip_reviews(trip_id):
    rows = list(get_collection("trip_reviews").find({"tripId": trip_id})
                .sort("createdAt", -1))
    return [_trip_review_public(r) for r in rows]


def get_all_reviews(limit=200):
    """All reviews (for AI feedback analysis). Returns plain dicts."""
    rows = list(get_collection("trip_reviews").find().sort("createdAt", -1).limit(limit))
    return [_trip_review_public(r) for r in rows]


def _trip_review_public(r):
    return {
        "id": str(r.get("_id", "")),
        "userId": r.get("userId"),
        "userName": r.get("userName"),
        "tripId": r.get("tripId"),
        "origin": r.get("origin"),
        "destination": r.get("destination"),
        "rating": r.get("rating"),
        "comment": r.get("comment"),
        "createdAt": r.get("createdAt"),
    }