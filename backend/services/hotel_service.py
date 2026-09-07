"""Hotel Admin domain: hotel profiles, full room-type inventory, availability,
amenities and atomic, race-safe room booking.

Availability model per room type (single source of truth):
    available = totalRooms - bookedRooms - blockedRooms   (never < 0)
"""
from datetime import datetime
from bson.objectid import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from services.mongodb import get_collection
from services import duplicate
from services.auth import new_user_id, provider_is_approved, resource_status as auth_resource_status

BED_TYPES = ("Single Bed", "Double Bed", "Twin Bed", "King Bed", "Queen Bed",
             "Multiple Beds", "Other")
HOTEL_CATEGORIES = ("Budget", "Mid-Range", "Luxury", "Boutique", "Resort", "Other")
STANDARD_AMENITIES = (
    "Wi-Fi", "Parking", "Restaurant", "Room Service", "AC", "TV", "Breakfast",
    "Swimming Pool", "Gym", "Laundry", "24/7 Front Desk")


def _now():
    return datetime.utcnow().isoformat()


def _clean_room_types(raw, hotel_total):
    """Validate and normalize the room-type inventory (server-side).

    Mandatory rule: sum(roomTypes.count) == totalRooms.
    """
    if not isinstance(raw, list) or not raw:
        return None, "At least one room type is required."
    total = 0
    cleaned = []
    seen = set()
    all_room_numbers = set()
    for rt in raw:
        name = (rt.get("name") or "").strip()
        if not name:
            return None, "Every room type needs a name."
        low = name.lower()
        if low in seen:
            return None, "Duplicate room type name: %s" % name
        seen.add(low)
        try:
            count = int(rt.get("totalRooms") or 0)
            price = float(rt.get("pricePerNight") or 0)
            beds = int(rt.get("numberOfBeds") or 1)
            occupancy = int(rt.get("maxOccupancy") or 1)
        except (TypeError, ValueError):
            return None, "Room type %s has invalid numeric values." % name
        if count <= 0 or price <= 0 or beds <= 0 or occupancy <= 0:
            return None, "Room type %s must have positive count/price/beds/occupancy." % name
        room_numbers = [str(n).strip() for n in (rt.get("roomNumbers") or []) if str(n).strip()]
        if len(room_numbers) != count:
            return None, ("Room type %s must list exactly one room number per room "
                          "(%d rooms, %d room numbers given)." % (name, count, len(room_numbers)))
        dup = all_room_numbers.intersection(set(room_numbers))
        if dup:
            return None, "Duplicate room number across hotel: %s" % ", ".join(sorted(dup))
        seen_nums = set()
        for n in room_numbers:
            if n in seen_nums:
                return None, "Duplicate room number within room type %s: %s" % (name, n)
            seen_nums.add(n)
        all_room_numbers.update(seen_nums)
        total += count
        rt_id = rt.get("id") or new_user_id()
        cleaned.append({
            "id": rt_id,
            "name": name,
            "category": (rt.get("category") or "").strip(),
            "totalRooms": count,
            "bookedRooms": int(rt.get("bookedRooms") or 0),
            "blockedRooms": max(0, int(rt.get("blockedRooms") or 0)),
            "pricePerNight": round(price, 2),
            "ac": bool(rt.get("ac")),
            "bedType": (rt.get("bedType") or "Single Bed").strip(),
            "numberOfBeds": beds,
            "maxOccupancy": occupancy,
            "amenities": [str(a).strip() for a in (rt.get("amenities") or []) if str(a).strip()],
            "images": [str(i).strip() for i in (rt.get("images") or []) if str(i).strip()],
            "roomNumbers": sorted(room_numbers),
        })
    if hotel_total <= 0:
        return None, "Total number of rooms must be a positive number."
    if total != hotel_total:
        return None, ("Room type inventory does not match the hotel total. "
                      "Room types sum to %d but the hotel has %d rooms." % (total, hotel_total))
    return cleaned, None


def _room_available(rt):
    return max(0, rt.get("totalRooms", 0) - rt.get("bookedRooms", 0) - rt.get("blockedRooms", 0))


def _public_room_type(rt):
    out = dict(rt)
    out["availableRooms"] = _room_available(rt)
    return out


def _public_hotel(doc, with_rooms=False):
    rooms = doc.get("roomTypes") or []
    hotel = {
        "id": str(doc["_id"]),
        "ownerId": str(doc.get("ownerId", "")),
        "name": doc.get("name"),
        "description": doc.get("description", ""),
        "address": doc.get("address", ""),
        "city": doc.get("city", ""),
        "state": doc.get("state", ""),
        "country": doc.get("country", ""),
        "lat": doc.get("lat"),
        "lng": doc.get("lng"),
        "contactNumber": doc.get("contactNumber", ""),
        "email": doc.get("email", ""),
        "checkInTime": doc.get("checkInTime", "12:00"),
        "checkOutTime": doc.get("checkOutTime", "11:00"),
        "amenities": doc.get("amenities", []),
        "category": doc.get("category", "Other"),
        "starRating": doc.get("starRating"),
        "images": doc.get("images", []),
        "documents": doc.get("documents", []),
        "totalRooms": doc.get("totalRooms", 0),
        "status": doc.get("status", "APPROVED"),
        "createdAt": doc.get("createdAt"),
    }
    if with_rooms:
        hotel["roomTypes"] = [_public_room_type(r) for r in rooms]
        hotel["availableRooms"] = sum(_room_available(r) for r in rooms)
        hotel["bookedRooms"] = sum(r.get("bookedRooms", 0) for r in rooms)
        hotel["blockedRooms"] = sum(r.get("blockedRooms", 0) for r in rooms)
    return hotel


def create_hotel(user, data):
    if not provider_is_approved(user):
        return None, "Your provider account must be approved by the Admin before you can add hotels."
    try:
        total = int(data.get("totalRooms") or 0)
    except (TypeError, ValueError):
        return None, "Total number of rooms must be a number."
    room_types, err = _clean_room_types(data.get("roomTypes"), total)
    if err:
        return None, err

    doc = {
        "_id": new_user_id(),
        "ownerId": str(user["id"]),
        "name": (data.get("name") or "").strip(),
        "description": (data.get("description") or "").strip(),
        "address": (data.get("address") or "").strip(),
        "city": (data.get("city") or "").strip(),
        "state": (data.get("state") or "").strip(),
        "country": (data.get("country") or "").strip(),
        "lat": data.get("lat"),
        "lng": data.get("lng"),
        "contactNumber": (data.get("contactNumber") or "").strip(),
        "email": (data.get("email") or "").strip(),
        "checkInTime": (data.get("checkInTime") or "12:00").strip(),
        "checkOutTime": (data.get("checkOutTime") or "11:00").strip(),
        "amenities": [str(a).strip() for a in (data.get("amenities") or []) if str(a).strip()],
        "category": (data.get("category") or "Other").strip(),
        "starRating": data.get("starRating"),
        "images": [str(i).strip() for i in (data.get("images") or []) if str(i).strip()],
        "documents": [str(d).strip() for d in (data.get("documents") or []) if str(d).strip()],
        "totalRooms": total,
        "roomTypes": room_types,
        "status": auth_resource_status(user),  # PENDING until Admin approves
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    if not doc["name"] or not doc["city"]:
        return None, "Hotel name and city are required."
    if duplicate.owned_name_taken("hotels", str(user["id"]), doc["name"]):
        return None, "You already have a hotel named '%s'." % doc["name"]
    try:
        get_collection("hotels").insert_one(doc)
    except DuplicateKeyError:
        return None, "You already have a hotel named '%s'." % doc["name"]
    return _public_hotel(doc, with_rooms=True), None


def update_hotel(user, hotel_id, data):
    hotel = get_collection("hotels").find_one({"_id": hotel_id})
    if not hotel:
        return None, "Hotel not found."
    if str(hotel.get("ownerId")) != str(user["id"]):
        return None, "You can only edit your own hotel."
    upd = {k: v for k, v in data.items()
           if k in ("name", "description", "address", "city", "state", "country",
                    "lat", "lng", "contactNumber", "email", "checkInTime",
                    "checkOutTime", "amenities", "category", "starRating",
                    "images", "documents") and v is not None}
    if "totalRooms" in data and data.get("totalRooms") is not None:
        try:
            total = int(data["totalRooms"])
        except (TypeError, ValueError):
            return None, "Total number of rooms must be a number."
        room_types, err = _clean_room_types(data.get("roomTypes", hotel.get("roomTypes")), total)
        if err:
            return None, err
        upd["totalRooms"] = total
        upd["roomTypes"] = room_types
    else:
        total = hotel.get("totalRooms", 0)
        if "roomTypes" in data and data.get("roomTypes") is not None:
            room_types, err = _clean_room_types(data["roomTypes"], total)
            if err:
                return None, err
            upd["roomTypes"] = room_types
    upd["updatedAt"] = _now()
    if upd.get("name") and duplicate.owned_name_taken(
            "hotels", str(user["id"]), upd["name"], exclude_id=hotel_id):
        return None, "You already have a hotel named '%s'." % upd["name"]
    get_collection("hotels").update_one({"_id": hotel_id}, {"$set": upd})
    return _public_hotel(get_collection("hotels").find_one({"_id": hotel_id}), with_rooms=True), None


def set_blocked_rooms(user, hotel_id, room_type_id, blocked):
    hotel = get_collection("hotels").find_one({"_id": hotel_id})
    if not hotel:
        return None, "Hotel not found."
    if str(hotel.get("ownerId")) != str(user["id"]):
        return None, "You can only manage your own hotel."
    try:
        blocked = max(0, int(blocked))
    except (TypeError, ValueError):
        return None, "Blocked rooms must be a number."
    target = next((r for r in hotel.get("roomTypes", []) if r["id"] == room_type_id), None)
    if not target:
        return None, "Room type not found."
    if blocked > target.get("totalRooms", 0):
        blocked = target["totalRooms"]
    # cannot block more than unbooked rooms
    unbooked = target.get("totalRooms", 0) - target.get("bookedRooms", 0)
    result = get_collection("hotels").find_one_and_update(
        {"_id": hotel_id, "roomTypes.id": room_type_id},
        {"$set": {"roomTypes.$.blockedRooms": min(blocked, unbooked)}},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        return None, "Failed to update room availability."
    return _public_hotel(result, with_rooms=True), None


def add_room(user, hotel_id, data):
    """Add ONE room to the hotel inventory.

    Spec: rooms are identified by room number only (no room name) and must be
    unique across the hotel (``hotelId + roomNumber``). The room is attached to
    an existing matching room type (category + bed + AC + price) or creates one.
    """
    hotel = get_collection("hotels").find_one({"_id": hotel_id})
    if not hotel:
        return None, "Hotel not found."
    if str(hotel.get("ownerId")) != str(user["id"]):
        return None, "You can only manage your own hotel."
    room_number = str(data.get("roomNumber") or "").strip()
    if not room_number:
        return None, "Room number is required."
    try:
        price = float(data.get("pricePerNight") or 0)
    except (TypeError, ValueError):
        return None, "Room price must be a number."
    if price <= 0:
        return None, "Room price must be greater than zero."
    category = (data.get("category") or "Other").strip()
    bed_type = (data.get("bedType") or "Single Bed").strip()
    ac = bool(data.get("ac"))
    beds = max(1, int(data.get("numberOfBeds") or 1))
    occupancy = max(1, int(data.get("maxOccupancy") or 1))

    taken = [str(rn).strip() for rt in hotel.get("roomTypes", [])
             for rn in rt.get("roomNumbers", [])
             if str(rn).strip().lower() == room_number.lower()]
    if taken:
        return None, "A room with number '%s' already exists in this hotel." % room_number

    update = None
    for idx, rt in enumerate(hotel.get("roomTypes", [])):
        if (str(rt.get("category") or "").strip() == category
                and str(rt.get("bedType") or "").strip() == bed_type
                and bool(rt.get("ac")) == ac
                and abs(float(rt.get("pricePerNight") or 0) - price) < 0.001):
            rt_id = rt["id"]
            update = get_collection("hotels").find_one_and_update(
                {"_id": hotel_id, "roomTypes.id": rt_id},
                {"$inc": {"roomTypes.$.totalRooms": 1},
                 "$push": {"roomTypes.$.roomNumbers": room_number},
                 "$inc": {"totalRooms": 1},
                 "$set": {"updatedAt": _now()}},
                return_document=ReturnDocument.AFTER,
            )
            break
    if not update:
        rt_id = new_user_id()
        update = get_collection("hotels").find_one_and_update(
            {"_id": hotel_id},
            {"$push": {"roomTypes": {
                "id": rt_id,
                "name": category or ("Room " + room_number),
                "category": category,
                "totalRooms": 1,
                "bookedRooms": 0,
                "blockedRooms": 0,
                "pricePerNight": round(price, 2),
                "ac": ac,
                "bedType": bed_type,
                "numberOfBeds": beds,
                "maxOccupancy": occupancy,
                "amenities": [],
                "images": [],
                "roomNumbers": [room_number],
            }},
             "$inc": {"totalRooms": 1},
             "$set": {"updatedAt": _now()}},
            return_document=ReturnDocument.AFTER,
        )
    if not update:
        return None, "Failed to add the room."
    return _public_hotel(update, with_rooms=True), None


def get_hotel(hotel_id):
    doc = get_collection("hotels").find_one({"_id": hotel_id})
    return _public_hotel(doc, with_rooms=True) if doc else None


def list_my_hotels(user):
    docs = get_collection("hotels").find({"ownerId": str(user["id"])}).sort("createdAt", -1)
    return [_public_hotel(d, with_rooms=True) for d in docs]


def search_hotels(city=None, category=None, ac=None, guests=None, name=None):
    """Public hotel search. Only returns hotels with real availability."""
    query = {"status": "APPROVED"}
    city = (city or "").strip()
    name = (name or "").strip()
    if city:
        query["city"] = {"$regex": city, "$options": "i"}
    if category:
        query["category"] = {"$regex": category, "$options": "i"}
    if name:
        query["name"] = {"$regex": name, "$options": "i"}
    try:
        guests = int(guests) if guests else 0
    except (TypeError, ValueError):
        guests = 0
    results = []
    for doc in get_collection("hotels").find(query):
        types = []
        for rt in doc.get("roomTypes", []):
            avail = _room_available(rt)
            if avail <= 0:
                continue
            if ac is not None and bool(int(ac)) != bool(rt.get("ac")):
                continue
            if guests and rt.get("maxOccupancy", 1) < guests:
                continue
            types.append(_public_room_type(rt))
        if not types:
            continue
        pub = _public_hotel(doc, with_rooms=False)
        pub["roomTypes"] = types
        pub["availableRooms"] = sum(t["availableRooms"] for t in types)
        results.append(pub)
    return results


def occupancy(user, hotel_id):
    hotel = get_collection("hotels").find_one({"_id": hotel_id})
    if not hotel:
        return None, "Hotel not found."
    if str(hotel.get("ownerId")) != str(user["id"]):
        return None, "You can only view your own hotel."
    rows = []
    for rt in hotel.get("roomTypes", []):
        rows.append({
            "roomTypeId": rt["id"],
            "name": rt["name"],
            "category": rt.get("category"),
            "totalRooms": rt.get("totalRooms", 0),
            "bookedRooms": rt.get("bookedRooms", 0),
            "blockedRooms": rt.get("blockedRooms", 0),
            "availableRooms": _room_available(rt),
            "occupied": round(100 * rt.get("bookedRooms", 0) / rt.get("totalRooms", 1), 1),
        })
    return {"hotelId": hotel_id,
            "hotelName": hotel.get("name"),
            "totalRooms": hotel.get("totalRooms", 0),
            "roomTypes": rows}, None


def book_rooms(hotel_id, room_type_id, qty):
    """Atomic room booking. Fails if availability changed between check and
    update (race-safe via guarded $inc)."""
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        return None, "Invalid room quantity."
    if qty <= 0:
        return None, "Room quantity must be at least 1."
    result = get_collection("hotels").find_one_and_update(
        {
            "_id": hotel_id,
            "roomTypes.id": room_type_id,
            # bookedRooms must stay <= total - blocked - qty (availability guard)
            "$expr": {
                "$let": {
                    "vars": {
                        "rt": {"$arrayElemAt": ["$roomTypes",
                                                 {"$indexOfArray": ["$roomTypes.id", room_type_id]}]}
                    },
                    "in": {"$and": [
                        {"$gte": [{"$subtract": [
                            {"$subtract": ["$$rt.totalRooms", "$$rt.bookedRooms"]},
                            "$$rt.blockedRooms"]}, qty]},
                    ]}
                }
            }
        },
        {"$inc": {"roomTypes.$.bookedRooms": qty}},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        return None, "Not enough rooms available for the requested room type."
    return _public_hotel(result, with_rooms=True), None


def release_rooms(hotel_id, room_type_id, qty):
    """Release previously booked rooms (cancellation). Never goes below 0."""
    doc = get_collection("hotels").find_one_and_update(
        {"_id": hotel_id, "roomTypes.id": room_type_id},
        {"$inc": {"roomTypes.$.bookedRooms": -qty}},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        return None, "Failed to release rooms."
    for rt in doc.get("roomTypes", []):
        if rt["id"] == room_type_id and rt.get("bookedRooms", 0) < 0:
            get_collection("hotels").update_one(
                {"_id": hotel_id, "roomTypes.id": room_type_id},
                {"$set": {"roomTypes.$.bookedRooms": 0}})
    return _public_hotel(doc, with_rooms=True), None