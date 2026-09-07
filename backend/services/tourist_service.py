"""Tourist Spot Admin data layer: spots, recommended times, tours,
and the authorized guide-location list.
"""
from datetime import datetime
from bson.objectid import ObjectId
from services.mongodb import get_collection
from services.auth import resource_status


def _id():
    return str(ObjectId())


def _ok(user, owner_id):
    from services.auth import is_admin
    return is_admin(user) or user["id"] == owner_id


def _loc(data):
    loc = data.get("location") or {}
    return {
        "name": defer(data.get("locationName")) or loc.get("name"),
        "address": data.get("address") or loc.get("address"),
        "lat": to_float(data.get("lat")) if data.get("lat") is not None else to_float(loc.get("lat")),
        "lng": to_float(data.get("lng")) if data.get("lng") is not None else to_float(loc.get("lng")),
        "city": defer(data.get("locationCity")) or loc.get("city"),
        "district": defer(data.get("district")) or loc.get("district"),
        "state": defer(data.get("state")) or loc.get("state"),
        "country": defer(data.get("country")) or loc.get("country"),
    }


def _working_days(raw):
    days = []
    for d in raw or []:
        d = str(d).strip()
        if d:
            days.append(d)
    return len(days) and days or None


def defer(x):
    return (x or "").strip()


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def create_spot(data, owner_id):
    spots = get_collection("tourist_spots")
    name = defer(data.get("name"))
    if not name:
        return None, "Spot name is required."

    images = [i for i in (data.get("images") or []) if i]
    if len(images) < 5:
        return None, "Provide at least 5 images for the spot."

    slots = _slots(data.get("recommendedTimes") or data.get("optimalTimes"))
    if len(slots) < 5:
        return None, "Provide at least 5 optimal visiting time slots."

    loc = _loc(data)
    if not loc.get("address"):
        return None, "A location/address is required (use the map picker or fill it in)."

    doc = {
        "_id": _id(),
        "ownerId": owner_id,
        "name": name,
        "city": defer(data.get("city")) or "Chennai",
        "category": (data.get("category") or "").strip() or "HISTORICAL",
        "location": loc,
        "description": data.get("description") or "",
        "entryFee": to_float(data.get("entryFee")),
        "openingTime": data.get("openingTime") or "09:00",
        "closingTime": data.get("closingTime") or "18:00",
        "recommendedTimes": slots,
        "optimalTimes": slots,
        "workingDays": _working_days(data.get("workingDays")) or [],
        "popularity": int(data.get("popularity") or 0),
        "images": images,
        "visitingTravelers": int(data.get("visitingTravelers") or 0),
        "status": resource_status(owner_id),
        "createdAt": datetime.utcnow().isoformat(),
        "updatedAt": datetime.utcnow().isoformat(),
    }
    spots.insert_one(doc)
    return doc, None


def _slots(raw):
    out = []
    for s in raw or []:
        ft = defer(s.get("from"))
        tt = defer(s.get("to"))
        if not ft or not tt:
            continue
        out.append({"from": ft, "to": tt, "note": s.get("note") or ""})
    return out


def update_spot(data, owner_id):
    spots = get_collection("tourist_spots")
    doc = spots.find_one({"_id": data.get("spotId")})
    if not doc:
        return None, "Spot not found."
    if not _ok(owner_id, doc["ownerId"]):
        return None, "Not authorized to edit this spot."
    img = [i for i in (data.get("images") if data.get("images") is not None else doc.get("images") or []) if i]
    if len(img) < 5:
        return None, "A spot must keep at least 5 images."
    slots = _slots(data.get("recommendedTimes") or data.get("optimalTimes"))
    if data.get("recommendedTimes") is not None or data.get("optimalTimes") is not None:
        if len(slots) < 5:
            return None, "A spot must keep at least 5 optimal visiting time slots."
    upd = {
        "name": defer(data.get("name")) or doc["name"],
        "city": defer(data.get("city")) or doc["city"],
        "category": data.get("category") or doc["category"],
        "location": _loc(data),
        "description": data.get("description", doc["description"]),
        "entryFee": to_float(data.get("entryFee")) if data.get("entryFee") is not None else doc["entryFee"],
        "openingTime": data.get("openingTime") or doc["openingTime"],
        "closingTime": data.get("closingTime") or doc["closingTime"],
        "recommendedTimes": slots or doc.get("recommendedTimes", []),
        "optimalTimes": slots or doc.get("optimalTimes", []),
        "workingDays": _working_days(data.get("workingDays")) or doc.get("workingDays") or [],
        "popularity": int(data.get("popularity") or 0),
        "visitingTravelers": int(data.get("visitingTravelers") or 0),
        "images": img,
        "updatedAt": datetime.utcnow().isoformat(),
    }
    spots.update_one({"_id": data["spotId"]}, {"$set": upd})
    return spots.find_one({"_id": data["spotId"]}), None


def list_spots(city=None, approved_only=True):
    q = {}
    if city:
        q["city"] = {"$regex": city, "$options": "i"}
    if approved_only:
        q["status"] = "APPROVED"
    return list(get_collection("tourist_spots").find(q).sort("popularity", -1))


def get_spot(sid):
    return get_collection("tourist_spots").find_one({"_id": sid})


def set_status(sid, status):
    get_collection("tourist_spots").update_one({"_id": sid}, {"$set": {"status": status}})
    return get_spot(sid)


def add_guide_location(owner_id, data):
    """Tourist-spot-aware guide locations are globally managed by tourist
    spot admins; guides can only be assigned locations in this list."""
    gl = get_collection("guide_locations")
    name = defer(data.get("name"))
    if not name:
        return None, "Location name is required."
    doc = {
        "_id": _id(),
        "name": name,
        "city": defer(data.get("city")) or "Chennai",
        "spots": data.get("spots") or [],
        "approved": True,
        "createdBy": owner_id,
        "createdAt": datetime.utcnow().isoformat(),
    }
    if gl.find_one({"$or": [{"name": {"$regex": "^%s$" % name, "$options": "i"}},
                             {"spots": {"$elemMatch": {"$in": data.get("spots") or []}}}]}):
        return None, "This location or spot is already registered."
    gl.insert_one(doc)
    return doc, None


def list_guide_locations(city=None):
    q = {}
    if city:
        q["city"] = {"$regex": city, "$options": "i"}
    return list(get_collection("guide_locations").find(q))


def load_guide_locations():
    return [x["name"] for x in list_guide_locations()]


# --- Tours / Experiences -----------------------------------------------------

def create_tour(data, owner_id):
    """Create a bookable tour/experience under one of the admin's spots."""
    tours = get_collection("tours")
    spot = get_collection("tourist_spots").find_one({"_id": defer(data.get("spotId"))})
    if not spot:
        return None, "Tourist spot not found."
    if not _ok(owner_id, spot.get("ownerId")):
        return None, "Not authorized to add tours to this spot."
    name = defer(data.get("name"))
    if not name:
        return None, "Tour name is required."
    try:
        cost = float(data.get("cost") or 0)
        participants = int(data.get("maxParticipants") or 0)
        duration = float(data.get("duration") or 0)
    except (TypeError, ValueError):
        return None, "Cost, duration and max participants must be numbers."
    if cost <= 0 or participants <= 0 or duration <= 0:
        return None, "Cost, duration and max participants must be positive."
    doc = {
        "_id": _id(),
        "spotId": defer(data.get("spotId")),
        "ownerId": owner_id,
        "name": name,
        "description": data.get("description") or "",
        "duration": duration,
        "cost": cost,
        "maxParticipants": participants,
        "bookedParticipants": int(data.get("bookedParticipants") or 0),
        "availableTimes": _slots(data.get("availableTimes")),
        "includedServices": [str(s).strip() for s in (data.get("includedServices") or []) if str(s).strip()],
        "guideRequired": bool(data.get("guideRequired")),
        "status": resource_status(owner_id),
        "createdAt": datetime.utcnow().isoformat(),
        "updatedAt": datetime.utcnow().isoformat(),
    }
    tours.insert_one(doc)
    return doc, None


def list_tours(spot_id=None, approved_only=True, city=None):
    q = {}
    if spot_id:
        q["spotId"] = spot_id
    if approved_only:
        q["status"] = "APPROVED"
    if city:
        spots = [s["_id"] for s in get_collection("tourist_spots").find(
            {"city": {"$regex": city, "$options": "i"}})]
        q["spotId"] = {"$in": spots}
    return list(get_collection("tours").find(q).sort("createdAt", -1))


def get_tour(tid):
    return get_collection("tours").find_one({"_id": tid})


def set_tour_status(tid, status):
    get_collection("tours").update_one({"_id": tid}, {"$set": {"status": status}})
    return get_tour(tid)