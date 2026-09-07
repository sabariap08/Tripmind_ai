"""Restaurant Admin module: restaurant profiles and food items.

Ownership model: a RESTAURANT_ADMIN manages restaurants whose ``ownerId`` is
their own account id. Food items belong to a restaurant by ``restaurantId``.

Approval model: only the RESTAURANT_ADMIN *account* requires Main Admin
approval. Once approved, the provider can create restaurants and food items
directly (no per-item Main Admin approval), matching the Transport/Hotel rule.
"""
from datetime import datetime
from pymongo.errors import DuplicateKeyError
from services.mongodb import get_collection
from services import duplicate

FOOD_CATEGORIES = ("VEG", "NON_VEG", "VEGAN", "BEVERAGE", "DESSERT", "OTHER")


def _now():
    return datetime.utcnow().isoformat()


def _public_restaurant(d):
    return {
        "id": str(d["_id"]),
        "ownerId": str(d.get("ownerId")) if d.get("ownerId") else None,
        "name": d.get("name"),
        "restaurantType": d.get("restaurantType") or "",
        "city": d.get("city") or "",
        "address": d.get("address") or "",
        "lat": d.get("lat"),
        "lng": d.get("lng"),
        "contactNumber": d.get("contactNumber") or "",
        "email": d.get("email") or "",
        "description": d.get("description") or "",
        "operatingDays": d.get("operatingDays") or [],
        "openingHours": d.get("openingHours") or [],
        "cuisines": d.get("cuisines") or [],
        "images": d.get("images") or [],
        "status": d.get("status", "APPROVED"),
        "createdAt": d.get("createdAt"),
    }


def _public_food(f):
    return {
        "id": str(f["_id"]),
        "restaurantId": str(f.get("restaurantId")),
        "name": f.get("name"),
        "price": f.get("price", 0),
        "prepTimeMinutes": f.get("prepTimeMinutes") or 0,
        "category": f.get("category") or "OTHER",
        "description": f.get("description") or "",
        "available": f.get("available", True),
        "image": f.get("image"),
        "createdAt": f.get("createdAt"),
    }


def _own_restaurant(owner_id, rid):
    return get_collection("restaurants").find_one(
        {"_id": str(rid), "ownerId": owner_id})


def create_restaurant(owner_id, data):
    from services.auth import new_user_id
    name = (data.get("name") or "").strip()
    if not name:
        return None, "Restaurant name is required."
    doc = {
        "_id": new_user_id(),
        "ownerId": owner_id,
        "name": name,
        "restaurantType": (data.get("restaurantType") or "").strip(),
        "city": (data.get("city") or "").strip(),
        "address": (data.get("address") or "").strip(),
        "lat": data.get("lat"),
        "lng": data.get("lng"),
        "contactNumber": (data.get("contactNumber") or "").strip(),
        "email": (data.get("email") or "").strip(),
        "description": (data.get("description") or "").strip(),
        "operatingDays": data.get("operatingDays") or [],
        "openingHours": data.get("openingHours") or [],
        "cuisines": data.get("cuisines") or [],
        "images": data.get("images") or [],
        "status": "APPROVED",
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    if duplicate.owned_name_taken("restaurants", owner_id, name):
        return None, "You already have a restaurant named '%s'." % name
    try:
        get_collection("restaurants").insert_one(doc)
    except DuplicateKeyError:
        return None, "You already have a restaurant named '%s'." % name
    return _public_restaurant(doc), None


def list_restaurants(user, city=None, q=None):
    query = {"status": "APPROVED"}
    if city:
        query["city"] = {"$regex": city.strip(), "$options": "i"}
    if q:
        query["$or"] = [
            {"name": {"$regex": q.strip(), "$options": "i"}},
            {"cuisines": {"$regex": q.strip(), "$options": "i"}},
        ]
    rows = []
    for d in get_collection("restaurants").find(query).sort("createdAt", -1):
        pub = _public_restaurant(d)
        if user and user.get("role") == "RESTAURANT_ADMIN" and str(d.get("ownerId")) == str(user.get("id", "")):
            pub["mine"] = True
        rows.append(pub)
    return rows


def my_restaurants(owner_id):
    rows = []
    for d in get_collection("restaurants").find(
            {"ownerId": owner_id}).sort("createdAt", -1):
        rows.append(_public_restaurant(d))
    return rows


def update_restaurant(owner_id, rid, data):
    doc = _own_restaurant(owner_id, rid)
    if not doc:
        return None, None, "Restaurant not found in your catalogue."
    allowed = ("name", "restaurantType", "city", "address", "lat", "lng", "contactNumber",
               "email", "description", "operatingDays", "openingHours", "cuisines", "images")
    upd = {k: data[k] for k in allowed if k in data and data[k] is not None}
    if "name" in upd and upd["name"] and duplicate.owned_name_taken(
            "restaurants", owner_id, upd["name"], exclude_id=str(rid)):
        return None, None, "You already have a restaurant named '%s'." % upd["name"]
    upd["updatedAt"] = _now()
    get_collection("restaurants").update_one({"_id": str(rid)}, {"$set": upd})
    return _public_restaurant(get_collection("restaurants").find_one({"_id": str(rid)})), True, None


def list_food_items(rid, user=None, only_available=True):
    query = {"restaurantId": str(rid)}
    if only_available:
        query["available"] = True
    if user and user.get("role") == "RESTAURANT_ADMIN" and _own_restaurant(user.get("id"), rid):
        query.pop("available", None)
    rows = []
    for f in get_collection("food_items").find(query).sort("createdAt", -1):
        rows.append(_public_food(f))
    return rows


def add_food_item(owner_id, rid, data):
    doc = _own_restaurant(owner_id, rid)
    if not doc:
        return None, "Restaurant not found in your catalogue."
    name = (data.get("name") or "").strip()
    image = data.get("image")
    if not name:
        return None, "Food item name is required."
    if not image:
        return None, "A food image is required."
    price = data.get("price")
    try:
        price = round(float(price), 2)
    except (TypeError, ValueError):
        return None, "A valid price is required."
    category = (data.get("category") or "OTHER").upper()
    if category not in FOOD_CATEGORIES:
        category = "OTHER"
    f = {
        "_id": get_collection("food_items").insert_one({}).inserted_id,
        "restaurantId": str(rid),
        "name": name,
        "price": price,
        "prepTimeMinutes": int(data.get("prepTimeMinutes") or 0),
        "category": category,
        "description": (data.get("description") or "").strip(),
        "available": bool(data.get("available", True)),
        "image": image,
        "createdAt": _now(),
    }
    get_collection("food_items").update_one({"_id": f["_id"]}, {"$set": f})
    return _public_food(f), None


def update_food_item(owner_id, rid, fid, data):
    doc = _own_restaurant(owner_id, rid)
    if not doc:
        return None, None, "Restaurant not found in your catalogue."
    item = get_collection("food_items").find_one(
        {"_id": str(fid), "restaurantId": str(rid)})
    if not item:
        return None, None, "Food item not found."
    upd = {}
    if "name" in data and data["name"] is not None:
        name = str(data["name"]).strip()
        if not name:
            return None, None, "Food item name is required."
        upd["name"] = name
    if "image" in data and data["image"]:
        upd["image"] = data["image"]
    if "price" in data and data["price"] is not None:
        try:
            upd["price"] = round(float(data["price"]), 2)
        except (TypeError, ValueError):
            return None, None, "Invalid price."
    if "description" in data and data["description"] is not None:
        upd["description"] = str(data["description"]).strip()
    if "prepTimeMinutes" in data and data["prepTimeMinutes"] is not None:
        upd["prepTimeMinutes"] = int(data["prepTimeMinutes"] or 0)
    if "available" in data and data["available"] is not None:
        upd["available"] = bool(data["available"])
    if "category" in data and data["category"]:
        cat = str(data["category"]).upper()
        upd["category"] = cat if cat in FOOD_CATEGORIES else "OTHER"
    upd["updatedAt"] = _now()
    get_collection("food_items").update_one(
        {"_id": str(fid)}, {"$set": upd})
    return _public_food(get_collection("food_items").find_one({"_id": str(fid)})), True, None


def delete_food_item(owner_id, rid, fid):
    doc = _own_restaurant(owner_id, rid)
    if not doc:
        return "Restaurant not found in your catalogue."
    result = get_collection("food_items").delete_one(
        {"_id": str(fid), "restaurantId": str(rid)})
    if not result.deleted_count:
        return "Food item not found."
    return None