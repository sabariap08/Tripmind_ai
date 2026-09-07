"""Restaurant module routes (RESTAURANT_ADMIN role).

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
    return _public_restaurant(d) if d else None