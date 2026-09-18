"""Railway lounge domain (RAILWAY_ADMIN / IRCTC).

Lounges are owned by railway admin accounts. Normal users can browse and
book lounge passes; only RAILWAY_ADMIN (or ADMIN) can create or manage them.
"""
from datetime import datetime
from bson.objectid import ObjectId
from services.mongodb import get_collection
from services.auth import new_user_id, resource_status


def _now():
    return datetime.utcnow().isoformat()


def _to_id(v):
    if isinstance(v, ObjectId):
        return v
    try:
        return ObjectId(str(v))
    except Exception:
        return None


def _public(lounge):
    if not lounge:
        return None
    return {
        "id": str(lounge["_id"]),
        "name": lounge.get("name"),
        "railwayStation": lounge.get("railwayStation"),
        "city": lounge.get("city"),
        "terminal": lounge.get("terminal"),
        "description": lounge.get("description"),
        "images": lounge.get("images") or [],
        "amenities": lounge.get("amenities") or [],
        "pricePerPerson": lounge.get("pricePerPerson"),
        "maxCapacity": lounge.get("maxCapacity"),
        "hours": lounge.get("hours"),
        "status": lounge.get("status"),
        "ownerId": str(lounge.get("ownerId")) if lounge.get("ownerId") else None,
        "createdAt": lounge.get("createdAt"),
        "updatedAt": lounge.get("updatedAt"),
    }


def _clean_lounge(data):
    name = (data.get("name") or "").strip()
    if not name:
        return None, "Lounge name is required."
    station = (data.get("railwayStation") or "").strip()
    if not station:
        return None, "Railway station is required."
    city = (data.get("city") or "").strip()
    if not city:
        return None, "City is required."
    try:
        price = float(data.get("pricePerPerson") or 0)
        capacity = int(data.get("maxCapacity") or 0)
    except (TypeError, ValueError):
        return None, "pricePerPerson / maxCapacity must be valid numbers."
    if price <= 0:
        return None, "pricePerPerson must be greater than zero."
    if capacity <= 0:
        return None, "maxCapacity must be greater than zero."
    cleaned = {
        "name": name,
        "railwayStation": station,
        "city": city,
        "terminal": (data.get("terminal") or "Main Terminus").strip(),
        "description": (data.get("description") or "").strip(),
        "images": [str(i).strip() for i in (data.get("images") or []) if str(i).strip()],
        "amenities": [str(a).strip() for a in (data.get("amenities") or []) if str(a).strip()],
        "pricePerPerson": round(price, 2),
        "maxCapacity": capacity,
        "hours": (data.get("hours") or "").strip(),
    }
    return cleaned, None


def list_lounges(city=None, status=None):
    query = {}
    if city:
        query["city"] = city
    if status:
        query["status"] = status
    cursor = get_collection("lounges").find(query)
    return [_public(l) for l in cursor.sort("name", 1)]


def get_lounge(loungId):
    oid = _to_id(loungId)
    if not oid:
        return None
    return _public(get_collection("lounges").find_one({"_id": oid}))


def create_lounge(data, user):
    cleaned, err = _clean_lounge(data)
    if err:
        return None, err
    doc = dict(cleaned)
    doc.update({
        "_id": new_user_id(),
        "ownerId": user["id"],
        "status": resource_status(user),
        "createdAt": _now(),
        "updatedAt": _now(),
        "bookings": 0,
    })
    get_collection("lounges").insert_one(doc)
    return _public(doc), None


def update_lounge(loungId, data, user):
    oid = _to_id(loungId)
    if not oid:
        return None, "Lounge not found."
    lounge = get_collection("lounges").find_one({"_id": oid})
    if not lounge:
        return None, "Lounge not found."
    cleaned, err = _clean_lounge(data)
    if err:
        return None, err
    lounge.update(cleaned)
    lounge["updatedAt"] = _now()
    get_collection("lounges").update_one({"_id": oid}, {"$set": {**cleaned, "updatedAt": lounge["updatedAt"]}})
    return _public(get_collection("lounges").find_one({"_id": oid})), None


def delete_lounge(loungId, user):
    oid = _to_id(loungId)
    if not oid:
        return False, "Lounge not found."
    get_collection("lounges").delete_one({"_id": oid})
    return True, None


def set_lounge_status(loungId, status, reason=None):
    oid = _to_id(loungId)
    if not oid:
        return None
    get_collection("lounges").update_one(
        {"_id": oid},
        {"$set": {"status": status, "rejectionReason": reason, "updatedAt": _now()}},
    )
    return _public(get_collection("lounges").find_one({"_id": oid}))


def book_lounge(loungId, user_id):
    """Create a lounge pass. Returns a normalized booking-ish dict plus the
    seat/price so the booking_service can persist it as a BOOLEAN-ish resource
    booking. Simple atomic capacity guard included."""
    oid = _to_id(loungId)
    if not oid:
        return None, None, "Lounge not found."
    lounge = get_collection("lounges").find_one({"_id": oid})
    if not lounge:
        return None, None, "Lounge not found."
    if lounge.get("status") != "APPROVED":
        return None, None, "Lounge is not available yet (pending Admin approval)."
    capacity = int(lounge.get("maxCapacity") or 0)
    if capacity <= 0:
        return None, None, "Lounge has no capacity."
    used = int(lounge.get("bookings") or 0)
    if used >= capacity:
        return None, None, "Lounge is at full capacity."
    result = get_collection("lounges").find_one_and_update(
        {"_id": oid, "bookings": {"$lt": capacity}},
        {"$inc": {"bookings": 1}, "$set": {"updatedAt": _now()}},
    )
    if result is None:
        return None, None, "Lounge is at full capacity."
    lounge["bookings"] = used + 1
    price = float(lounge.get("pricePerPerson") or 0)
    return _public(lounge), price, None