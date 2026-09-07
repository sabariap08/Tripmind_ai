"""Booking data layer with server-side, atomic capacity validation.

Entities bookable by users: transport seats, hotel rooms, tours, spots, guides.

Availability is NEVER trusted from the frontend:
- TRANSPORT seats  -> guarded $inc on transports.bookedSeats
- HOTEL rooms      -> guarded $inc on hotels.roomTypes[].bookedRooms
- TOUR seats       -> guarded $inc on tours.bookedParticipants
- GUIDE            -> overlapping-assignment guard + Admin-approval-gated guide

Guide flow creates a REQUEST (pending) for the guide to accept/reject.
"""
from datetime import datetime, timedelta
from bson.objectid import ObjectId
from services.mongodb import get_collection
from services.transport_service import book_seats, release_seats
from services.hotel_service import book_rooms, release_rooms

BOOKING_STATUS = ("CONFIRMED", "PENDING", "REJECTED", "CANCELLED", "COMPLETED")
BOOKABLE_TYPES = ("TRANSPORT", "TOUR", "HOTEL", "GUIDE", "SPOT", "RESTAURANT")


def _id():
    return str(ObjectId())


def _minutes(v):
    """'HH:MM' -> minutes since midnight, or None on bad input."""
    try:
        if not v:
            return None
        parts = [int(x) for x in str(v).split(":")[:2]]
        return parts[0] * 60 + parts[1]
    except (ValueError, TypeError, IndexError):
        return None


def _guide_slot_fits_availability(guide_id, date, details=None):
    """True if the requested slot falls inside the guide's locked availability.

    Weekly availability must be posted (guide_availability, locked=True) before
    a booking can be made on that date. The requested [startTime, endTime] slot
    must fit within one posted slot entirely — server-side truth only.
    """
    details = details or {}
    req_start = _minutes(details.get("startTime"))
    req_end = _minutes(details.get("endTime"))
    if req_start is None or req_end is None:
        return False
    try:
        day = datetime.strptime((date or "").strip(), "%Y-%m-%d")
    except (ValueError, TypeError):
        return False
    week_start = (day - timedelta(days=day.weekday())).strftime("%Y-%m-%d")
    doc = get_collection("guide_availability").find_one(
        {"guideId": guide_id, "weekStart": week_start, "locked": True})
    if not doc:
        return False
    day_entry = next((d for d in doc.get("days", [])
                      if (d.get("date") or "").strip() == (date or "").strip()), None)
    if not day_entry:
        return False
    slots = list(day_entry.get("slots") or [])
    if day_entry.get("from") and day_entry.get("to"):
        slots.append({"from": day_entry["from"], "to": day_entry["to"]})
    for s in slots:
        s_open = _minutes(s.get("from"))
        s_close = _minutes(s.get("to"))
        if s_open is None or s_close is None:
            continue
        if s_open <= req_start and req_end <= s_close:
            return True
    return False


def _duplicate_guard(btype, user, resource_parts, date=""):
    """Composite idempotency check.

    A single passenger can never hold the same bookable resource for the same
    date twice (cancelled/rejected bookings are ignored). Uses a deterministic
    uniqueness key, NOT a global "one booking per user" rule — a passenger can
    still book different services freely.
    """
    key = "|".join([str(user["id"]), btype, (date or "")] + [str(p) for p in resource_parts])
    exists = get_collection("bookings").find_one({
        "uniquenessKey": key,
        "status": {"$nin": ("CANCELLED", "REJECTED")},
    })
    return key, exists


def create_booking(data, user):
    btype = (data.get("type") or "").upper()
    if btype not in BOOKABLE_TYPES:
        return None, f"Unsupported booking type '{btype}'."
    if user["role"] != "USER" and user["role"] != "ADMIN":
        return None, "Only users can create bookings."

    pay_wallet = bool(data.get("payFromWallet")) or bool(data.get("wallet"))
    reference = "TB" + _id()[-6:].upper()
    qty = max(1, int(data.get("qty") or 1))

    transport = None
    spot = None
    hotel = None
    tour = None
    ug_key = None

    if btype == "TRANSPORT":
        transport = get_collection("transports").find_one(
            {"status": "APPROVED", "_id": str(data.get("transportId") or "")})
        if not transport:
            return None, "Transport not found or not approved."
        ug_key, dup = _duplicate_guard(btype, user, [str(transport["_id"])], data.get("date") or "")
        if dup:
            return None, "You already have a booking on this transport service."
        if transport.get("type") in ("CAB", "AUTO"):
            # Charters: a single vehicle is booked for the whole trip, so no
            # per-seat capacity is consumed.
            qty = 1
        else:
            ok, err = book_seats(transport, data.get("seatType"), qty)
            if not ok:
                return None, err

    elif btype == "SPOT":
        spot = get_collection("tourist_spots").find_one(
            {"_id": str(data.get("spotId") or ""), "status": "APPROVED"})
        if not spot:
            return None, "Tourist spot not found or not available."
        ug_key, dup = _duplicate_guard(btype, user, [str(spot["_id"])], data.get("date") or "")
        if dup:
            return None, "You already have a booking for this tourist spot."

    elif btype == "TOUR":
        tour = get_collection("tours").find_one({"_id": str(data.get("tourId") or "")})
        if not tour or tour.get("status") != "APPROVED":
            return None, "Tour not found or not available."
        ug_key, dup = _duplicate_guard(btype, user, [str(tour["_id"])], data.get("date") or "")
        if dup:
            return None, "You already have a booking for this tour."
        ok, err = _book_tour_seats(tour, qty)
        if not ok:
            return None, err

    elif btype == "HOTEL":
        hotel = get_collection("hotels").find_one(
            {"_id": str(data.get("hotelId") or ""), "status": "APPROVED"})
        if not hotel:
            return None, "Hotel not found or not available."
        ug_key, dup = _duplicate_guard(
            btype, user, [str(hotel["_id"]), data.get("roomTypeId") or ""],
            data.get("date") or "")
        if dup:
            return None, "You already have a booking at this hotel for this date."
        ok, err = book_rooms(str(hotel["_id"]), str(data.get("roomTypeId") or ""), qty)
        if not ok:
            return None, err

    elif btype == "GUIDE":
        guide = get_collection("users").find_one(
            {"_id": str(data.get("guideId") or ""), "role": "GUIDE",
             "approvalStatus": "APPROVED", "status": "ACTIVE"})
        if not guide:
            return None, "Guide not found or not approved."
        ug_key, dup = _duplicate_guard(btype, user, [str(guide["_id"])], data.get("date") or "")
        if dup:
            return None, "You already have a booking with this guide for this date."
        if not _guide_slot_fits_availability(str(guide["_id"]), data.get("date"), data.get("details")):
            return None, "Guide is not available for the requested date/time."
        if _guide_has_conflict(str(guide["_id"]), data.get("date"), data.get("details")):
            return None, "Guide is not available for the requested date/time."

    elif btype == "RESTAURANT":
        restaurant = get_collection("restaurants").find_one(
            {"_id": str(data.get("restaurantId") or ""), "status": "APPROVED"})
        if not restaurant:
            return None, "Restaurant not found or not available."
        food_item = get_collection("food_items").find_one(
            {"_id": str(data.get("foodItemId") or ""),
             "restaurantId": str(restaurant["_id"]), "available": True})
        if not food_item:
            return None, "Food item not available."
        ug_key, dup = _duplicate_guard(
            btype, user, [str(restaurant["_id"]), str(food_item["_id"])],
            data.get("date") or "")
        if dup:
            return None, "You already have a booking for this item on this date."

    unit_price = to_float(data.get("unitPrice"))
    cab_total = None
    if btype == "TRANSPORT" and transport is not None and transport.get("type") in ("CAB", "AUTO"):
        # Plan-my-trip budget rule for cabs/autos: nearest = baseFare + distance * pricePerKm.
        fare = transport.get("fare") or {}
        base_fare = float(fare.get("baseFare") or 0)
        price_per_km = float(fare.get("pricePerKm") or fare.get("perKm") or 0)
        minimum = float(fare.get("minimum") or 0) or base_fare
        details = dict(data.get("details") or {})
        distance_km = float(details.get("distanceKm") or 0)
        details.setdefault("distanceKm", distance_km)
        data = dict(data); data["details"] = details
        if distance_km <= 0:
            return None, "A trip distance (distanceKm) is required to quote a cab/auto fare."
        qty = 1
        cab_total = max(minimum, round(base_fare + distance_km * price_per_km, 2))
    if unit_price is None:
        if btype == "TRANSPORT" and transport:
            unit_price = _fare_for(transport)
        elif btype == "SPOT" and spot:
            unit_price = float(spot.get("entryFee") or 0)
        elif btype == "TOUR" and tour:
            unit_price = float(tour.get("cost") or 0)
        elif btype == "HOTEL" and hotel:
            rt = next((r for r in hotel.get("roomTypes", [])
                       if r["id"] == str(data.get("roomTypeId") or "")), None)
            unit_price = float(rt["pricePerNight"]) if rt else 0.0
        elif btype == "GUIDE":
            gp = get_collection("guide_pricing").find_one({"guideId": data.get("guideId")})
            if gp:
                hourly = float(gp.get("pricePerHour") or (gp.get("hourlyCharge") or 0))
                daily = float(gp.get("pricePerDay") or (gp.get("halfDayCharge") or 0))
                d = data.get("details") or {}
                try:
                    s, e = str(d.get("startTime") or ""), str(d.get("endTime") or "")
                    sm = int(s.split(":")[0]) * 60 + int(s.split(":")[1])
                    em = int(e.split(":")[0]) * 60 + int(e.split(":")[1])
                    unit_price = round(hourly * max(1.0, (em - sm) / 60.0), 2)
                except (ValueError, IndexError, AttributeError):
                    unit_price = hourly if hourly else daily / 8
            else:
                unit_price = 0.0
        elif btype == "RESTAURANT" and food_item:
            unit_price = float(food_item.get("price") or 0)
        else:
            unit_price = 0.0
    if cab_total is not None:
        total = cab_total
    else:
        total = round(unit_price * qty, 2)

    status = "PENDING" if btype == "GUIDE" else "CONFIRMED"

    wallet_txn_id = None
    if pay_wallet:
        from services.wallet_service import debit as wallet_debit
        wallet, err = wallet_debit(user["id"], total, f"Booking {reference}", ref=reference)
        if not wallet:
            # Roll back any capacity reserved above so nothing is held without a booking.
            if btype == "TRANSPORT" and transport is not None and transport.get("type") not in ("CAB", "AUTO"):
                release_seats(str(transport["_id"]), qty)
            if btype == "HOTEL":
                release_rooms(str(hotel["_id"]), str(data.get("roomTypeId") or ""), qty)
            if btype == "TOUR":
                get_collection("tours").update_one(
                    {"_id": tour["_id"]}, {"$inc": {"bookedParticipants": -qty}})
            return None, err
        for t in reversed(wallet.get("transactions") or []):
            if t.get("ref") == reference and t.get("type") == "DEBIT":
                wallet_txn_id = t.get("id")
                break

    booking = {
        "_id": _id(),
        "reference": reference,
        "userId": user["id"],
        "type": btype,
        "status": status,
        "qty": qty,
        "unitPrice": unit_price,
        "total": total,
        "date": data.get("date") or datetime.utcnow().strftime("%Y-%m-%d"),
        "passengers": data.get("passengers") or [],
        "details": data.get("details") or {},
        "hotelId": str(hotel["_id"]) if hotel else None,
        "roomTypeId": data.get("roomTypeId") if btype == "HOTEL" else None,
        "transportId": str(transport["_id"]) if transport else None,
        "spotId": str(spot["_id"]) if spot else None,
        "tourId": str(tour["_id"]) if tour else None,
        "guideId": data.get("guideId") if btype == "GUIDE" else None,
        "restaurantId": str(restaurant["_id"]) if restaurant else None,
        "foodItemId": data.get("foodItemId") if btype == "RESTAURANT" else None,
        "foodName": (food_item or {}).get("name") if btype == "RESTAURANT" else None,
        "approvalMessage": data.get("approvalMessage", ""),
        "paymentStatus": "COMPLETED" if pay_wallet else "PENDING",
        "walletPaid": round(total, 2) if pay_wallet else None,
        "walletTxnId": wallet_txn_id,
        "uniquenessKey": ug_key,
        "tripId": data.get("tripId"),
        "createdAt": datetime.utcnow().isoformat(),
    }
    get_collection("bookings").insert_one(booking)
    return booking, None


def _book_tour_seats(tour, qty):
    """Atomic tour capacity booking (guarded $inc)."""
    result = get_collection("tours").find_one_and_update(
        {"_id": tour["_id"],
         "bookedParticipants": {"$lte": int(tour.get("maxParticipants") or 0) - qty}},
        {"$inc": {"bookedParticipants": qty}},
        return_document=True,
    )
    if not result:
        left = max(0, int(tour.get("maxParticipants") or 0) - int(tour.get("bookedParticipants") or 0))
        return False, "Only %d participants remaining for this tour." % left
    return True, None


def _guide_has_conflict(guide_id, date, details=None, exclude=None):
    """True if the guide has a CONFIRMED booking overlapping the requested slot."""
    details = details or {}
    start = (details.get("startTime") or "").strip()
    end = (details.get("endTime") or "").strip()
    try:
        s_min = int(start.split(":")[0]) * 60 + int(start.split(":")[1]) if start else None
        e_min = int(end.split(":")[0]) * 60 + int(end.split(":")[1]) if end else None
    except (ValueError, IndexError, AttributeError):
        s_min = e_min = None
    for b in get_collection("bookings").find(
            {"guideId": guide_id, "status": {"$in": ("CONFIRMED", "PENDING")},
             "date": date or ""}):
        if exclude and str(b["_id"]) == str(exclude):
            continue
        bd = b.get("details") or {}
        try:
            bs = int(str(bd.get("startTime") or "").split(":")[0]) * 60 + \
                 int(str(bd.get("startTime") or "").split(":")[1])
            be = int(str(bd.get("endTime") or "").split(":")[0]) * 60 + \
                 int(str(bd.get("endTime") or "").split(":")[1])
        except (ValueError, IndexError):
            continue
        if s_min is not None and e_min is not None and bs <= e_min and s_min <= be:
            return True
        if s_min is None and b["_id"] != "":
            return True  # day-level conflict when no slot info
    return False


def respond_guide_request(booking_id, guide_id, action, message=""):
    """Guide accepts/rejects a pending tour request."""
    b = get_collection("bookings").find_one({"_id": booking_id})
    if not b or b.get("type") != "GUIDE" or str(b.get("guideId")) != str(guide_id):
        return None, "Guide request not found."
    if b["status"] != "PENDING":
        return None, "Request has already been handled."
    action = (action or "").upper()
    if action == "ACCEPT":
        if _guide_has_conflict(str(guide_id), b.get("date"), b.get("details"),
                               exclude=booking_id):
            get_collection("bookings").update_one(
                {"_id": booking_id}, {"$set": {"status": "REJECTED"}})
            return None, "You already have a conflicting assignment for that slot."
        get_collection("bookings").update_one(
            {"_id": booking_id},
            {"$set": {"status": "CONFIRMED", "guideMessage": message or "Accepted"}})
        b["status"] = "CONFIRMED"
        return b, None
    if action == "REJECT":
        get_collection("bookings").update_one(
            {"_id": booking_id},
            {"$set": {"status": "REJECTED", "guideMessage": message or "Declined by guide"}})
        b["status"] = "REJECTED"
        return b, None
    return None, "Action must be ACCEPT or REJECT."


def _fare_for(transport):
    """Default per-seat fare resolution order: fare -> class price -> coach price."""
    f = transport.get("fare")
    if isinstance(f, dict):
        for key in ("price", "baseFare", "sleeper", "seater"):
            v = to_float(f.get(key))
            if v is not None:
                return v
    for block in ("classes", "coaches"):
        items = transport.get(block) or []
        for it in items:
            v = to_float(it.get("price"))
            if v is not None:
                return v
    return 0.0


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def cancel_booking(booking_id, user):
    b = get_collection("bookings").find_one({"_id": booking_id})
    if not b:
        return None, "Booking not found."
    if user["id"] != b["userId"]:
        from services.auth import is_admin
        if not is_admin(user):
            return None, "Not authorized to cancel this booking."
    if b["status"] in ("CANCELLED", "REJECTED"):
        return b, None
    if b.get("paymentStatus") in ("WALLET", "COMPLETED") and b.get("walletPaid"):
        from services.wallet_service import credit
        credit(b["userId"], float(b["walletPaid"]), f"Refund for booking {b.get('reference')}",
               ref=b.get("reference"))
    if b.get("transportId"):
        release_seats(b["transportId"], b.get("qty") or 1)
    if b.get("hotelId") and b.get("roomTypeId"):
        release_rooms(b["hotelId"], b["roomTypeId"], b.get("qty") or 1)
    if b.get("tourId"):
        get_collection("tours").update_one(
            {"_id": b["tourId"]},
            {"$inc": {"bookedParticipants": -(b.get("qty") or 1)}})
    get_collection("bookings").update_one(
        {"_id": booking_id}, {"$set": {"status": "CANCELLED"}})
    b["status"] = "CANCELLED"
    return b, None


def list_bookings(user):
    return list(get_collection("bookings").find({"userId": user["id"]}).sort("createdAt", -1))


def pay_booking(booking, user):
    """Debit the wallet for a single unpaid booking.

    Returns (updated_booking, err). Idempotent: already-paid bookings are
    returned as-is.
    """
    if not booking:
        return None, "Booking not found."
    if booking.get("paymentStatus") in ("WALLET", "COMPLETED"):
        return booking, None
    amount = float(booking.get("total") or 0)
    if amount <= 0:
        return None, "Booking total must be greater than zero."
    from services.wallet_service import debit
    wallet, err = debit(user["id"], amount,
                        f"Payment for booking {booking.get('reference')}",
                        ref=booking.get("reference"))
    if not wallet:
        return None, err
    txn_id = None
    for t in reversed(wallet.get("transactions") or []):
        if t.get("ref") == booking.get("reference") and t.get("type") == "DEBIT":
            txn_id = t.get("id")
            break
    updated = dict(booking)
    updated["paymentStatus"] = "COMPLETED"
    updated["walletPaid"] = round(amount, 2)
    updated["walletTxnId"] = txn_id
    updated["paidAt"] = datetime.utcnow().isoformat()
    get_collection("bookings").update_one(
        {"_id": booking["_id"]},
        {"$set": {"paymentStatus": "COMPLETED", "walletPaid": round(amount, 2),
                  "walletTxnId": txn_id, "paidAt": updated["paidAt"]}})
    return updated, None


def pay_trip_bookings(trip, user):
    """Attempt to pay every unpaid active booking on a trip from the wallet.

    Returns (updated_bookings, updated_trip, errors).
    """
    updated, errors = [], []
    for b in trip.get("bookings", []) or []:
        if b.get("status") in ("CANCELLED", "REJECTED"):
            updated.append(b)
            continue
        if b.get("paymentStatus") in ("WALLET", "COMPLETED"):
            updated.append(b)
            continue
        paid, err = pay_booking(b, user)
        if err:
            errors.append(f"{b.get('itemTitle') or b.get('reference')}: {err}")
            updated.append(b)
        else:
            updated.append(paid)
    trip["bookings"] = updated
    if errors:
        trip["paymentStatus"] = "FAILED" if all(
            b.get("paymentStatus") not in ("WALLET", "COMPLETED")
            for b in updated if b.get("status") not in ("CANCELLED", "REJECTED")) else "PENDING"
    else:
        trip["paymentStatus"] = "COMPLETED"
    get_collection("trips").update_one(
        {"_id": trip["_id"]},
        {"$set": {"bookings": updated, "paymentStatus": trip["paymentStatus"],
                  "updatedAt": datetime.utcnow().isoformat()}})
    return updated, trip, errors


def guide_bookings(guide_id):
    return list(get_collection("bookings").find(
        {"guideId": str(guide_id), "type": "GUIDE"}).sort("date", 1))


def all_bookings():
    return list(get_collection("bookings").find().sort("createdAt", -1))


def hotel_bookings(owner_id):
    """Guest bookings that landed on hotels owned by the given hotel admin."""
    ids = [str(h["_id"]) for h in
           get_collection("hotels").find({"ownerId": str(owner_id)}, {"_id": 1})]
    if not ids:
        return []
    return list(get_collection("bookings").find(
        {"type": "HOTEL", "hotelId": {"$in": ids}}).sort("createdAt", -1))


# Resource collection + booking reference field per bookable type.
_RESOURCE_BOOKING = {
    "TRANSPORT": ("transports", "transportId"),
    "HOTEL": ("hotels", "hotelId"),
    "TOUR": ("tours", "tourId"),
    "SPOT": ("tourist_spots", "spotId"),
    "RESTAURANT": ("restaurants", "restaurantId"),
}


def provider_bookings(owner_id, btype):
    """Guest bookings on resources owned by a provider (transport admin, hotel
    admin, tourist spot admin). Used for the “Upcoming Passengers” and other
    provider booking views."""
    pair = _RESOURCE_BOOKING.get((btype or "").upper())
    if not pair:
        return []
    coll, ref_field = pair
    ids = [str(r["_id"]) for r in
           get_collection(coll).find({"ownerId": str(owner_id)}, {"_id": 1})]
    if not ids:
        return []
    return list(get_collection("bookings").find(
        {"type": (btype or "").upper(), ref_field: {"$in": ids}})
        .sort("date", 1))


def transport_bookings(owner_id):
    """Guest bookings on transports registered by the given transport admin."""
    return provider_bookings(owner_id, "TRANSPORT")


def switch_transport(trip, user, new_transport_id, seat_type=None, qty=None):
    """AI-assisted transport change for a booked trip.

    Server-side only: validates the new transport is APPROVED and registered,
    applies the same wallet accounting the book flow uses (refund old / debit
    the difference), releases the old seat capacity, cancels the old booking
    and creates the replacement on the SAME trip.

    Returns (updated_trip, new_booking, err).
    """
    if not trip or trip.get("status") not in ("BOOKED", "COMPLETED"):
        return None, None, "Trip must be booked before changing transport."
    traveler_count = int(qty or trip.get("travelers") or 1)

    old = None
    for b in trip.get("bookings", []) or []:
        if (b.get("type") == "TRANSPORT"
                and b.get("status") not in ("CANCELLED", "REJECTED")
                and str(b.get("tripId") or "") == str(trip["_id"])):
            old = b
            break
    if not old:
        return None, None, "No active transport booking found on this trip."

    new_transport = get_collection("transports").find_one(
        {"_id": str(new_transport_id or ""), "status": "APPROVED"})
    if not new_transport:
        return None, None, "Transport not found or not approved."
    if old.get("transportId") == str(new_transport["_id"]):
        return None, None, "That transport is already booked on this trip."

    reserve_qty = 1 if new_transport.get("type") in ("CAB", "AUTO") else traveler_count
    if new_transport.get("type") in ("CAB", "AUTO"):
        pass  # charters consume no per-seat capacity
    else:
        ok, err = book_seats(new_transport, seat_type, reserve_qty)
        if not ok:
            return None, None, err

    new_fare = float(_fare_for(new_transport) or 0)
    old_paid = float(old.get("walletPaid") or 0)

    # Wallet accounting: refund the old booking, then settle the difference.
    from services.wallet_service import credit, debit
    txn_id = None
    if old_paid:
        credit(user["id"], old_paid, f"Refund for switching transport {old.get('reference')}",
               ref=old.get("reference"))
    diff = new_fare - old_paid
    if diff > 0:
        wallet, err = debit(user["id"], diff, f"Transport change on trip {trip['reference']}",
                            ref=trip.get("reference"))
        if not wallet:
            # roll back the seat reservation we just made
            if new_transport.get("type") not in ("CAB", "AUTO"):
                release_seats(str(new_transport["_id"]), reserve_qty)
            return None, None, err
        for t in reversed(wallet.get("transactions") or []):
            if t.get("ref") == trip.get("reference") and t.get("type") == "DEBIT":
                txn_id = t.get("id")
                break
    elif diff < 0:
        credit(user["id"], -diff, f"Savings on transport change for trip {trip.get('reference')}",
               ref=trip.get("reference"))

    reference = "TB" + _id()[-6:].upper()
    new_booking = {
        "_id": _id(),
        "reference": reference,
        "userId": user["id"],
        "type": "TRANSPORT",
        "status": "CONFIRMED",
        "qty": reserve_qty,
        "unitPrice": new_fare,
        "total": round(new_fare * reserve_qty, 2),
        "date": trip.get("startDate") or old.get("date"),
        "passengers": [],
        "details": dict(old.get("details") or {}),
        "transportId": str(new_transport["_id"]),
        "paymentStatus": "COMPLETED" if (old_paid or diff > 0) else "PENDING",
        "walletPaid": round(new_fare, 2) if (old_paid or diff > 0) else None,
        "walletTxnId": txn_id,
        "uniquenessKey": None,
        "tripId": trip["_id"],
        "switchedFrom": old.get("reference"),
        "createdAt": datetime.utcnow().isoformat(),
    }
    # The uniqueness key embeds user+type+date+resource, exactly like a normal
    # booking, so switching to the same transport is detected as a duplicate.
    key, dup = _duplicate_guard("TRANSPORT", user, [str(new_transport["_id"])],
                                new_booking["date"])
    if dup:
        if new_transport.get("type") not in ("CAB", "AUTO"):
            release_seats(str(new_transport["_id"]), reserve_qty)
        return None, None, "You already have a booking on this transport service."
    new_booking["uniquenessKey"] = key

    # Cancel the old booking WITHOUT re-refunding (wallet handled above).
    get_collection("bookings").update_one(
        {"_id": old["_id"]},
        {"$set": {"status": "CANCELLED", "cancelledReason": "Switched by traveller",
                  "switchedTo": reference}})
    if old.get("transportId"):
        release_seats(old["transportId"], int(old.get("qty") or 1))

    get_collection("bookings").insert_one(new_booking)

    updated = []
    for b in trip.get("bookings", []) or []:
        if str(b.get("_id")) == str(old["_id"]):
            b["status"] = "CANCELLED"
            b["cancelledReason"] = "Switched by traveller"
            b["switchedTo"] = reference
        updated.append(b)
    updated.append({**new_booking, "_id": new_booking["_id"]})
    get_collection("trips").update_one(
        {"_id": trip["_id"]},
        {"$set": {"bookings": updated, "updatedAt": datetime.utcnow().isoformat()}})
    trip["bookings"] = updated

    # Keep the selected itinerary honest: point the transport item at the new service.
    selected = next((it for it in trip.get("itineraries", [])
                     if it.get("status") == "SELECTED"), None)
    if selected:
        for item in selected.get("items") or []:
            if item.get("type") in ("BUS", "TRAIN", "FLIGHT", "CAB", "AUTO", "TRANSPORT"):
                item["bookableId"] = "transport:%s" % new_transport["_id"]
                item["title"] = ("%s · %s" % (new_transport.get("type"),
                                              new_transport.get("serviceName", "")))
                item["provider"] = new_transport.get("serviceName", "")
                item["cost"] = new_fare
        get_collection("trips").update_one(
            {"_id": trip["_id"]},
            {"$set": {"itineraries": trip["itineraries"]}})

    return trip, new_booking, None