from flask import Blueprint, request, jsonify
from config import ROLES
from services.auth import require_login, require_approved_provider
from services.hotel_service import (create_hotel, update_hotel, get_hotel,
                                    search_hotels, list_my_hotels, occupancy,
                                    set_blocked_rooms, add_room,
                                    STANDARD_AMENITIES, BED_TYPES, HOTEL_CATEGORIES)
from services.booking_service import hotel_bookings

hotel_bp = Blueprint("hotel", __name__)


@hotel_bp.route("/api/hotel/meta", methods=["GET"])
def meta():
    return jsonify({"amenities": list(STANDARD_AMENITIES),
                    "bedTypes": list(BED_TYPES),
                    "categories": list(HOTEL_CATEGORIES)})


@hotel_bp.route("/api/hotels", methods=["POST"])
@require_approved_provider
def add_hotel():
    if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
        return jsonify({"error": "Only hotel admins can add hotels."}), 403
    doc, err = create_hotel(request.current_user, request.get_json() or {})
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"hotel": doc}), 201


@hotel_bp.route("/api/hotels/mine", methods=["GET"])
@require_login
def mine():
    if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
        return jsonify({"error": "Only hotel admins can view their hotels."}), 403
    return jsonify({"hotels": list_my_hotels(request.current_user)})


@hotel_bp.route("/api/hotels/search", methods=["GET"])
@require_login
def search():
    return jsonify({"hotels": search_hotels(
        city=request.args.get("city"),
        category=request.args.get("category"),
        ac=request.args.get("ac"),
        guests=request.args.get("guests"),
        name=request.args.get("name"))})


@hotel_bp.route("/api/hotels/<hid>", methods=["GET", "PUT"])
@require_login
def hotel(hid):
    if request.method == "PUT":
        if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
            return jsonify({"error": "Not authorized to edit hotels."}), 403
        doc, err = update_hotel(request.current_user, hid, request.get_json() or {})
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"hotel": doc})
    doc = get_hotel(hid)
    if not doc:
        return jsonify({"error": "Hotel not found."}), 404
    return jsonify({"hotel": doc})


@hotel_bp.route("/api/hotels/<hid>/occupancy", methods=["GET"])
@require_login
def occ(hid):
    if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
        return jsonify({"error": "Only hotel admins can view occupancy."}), 403
    data, err = occupancy(request.current_user, hid)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(data)


@hotel_bp.route("/api/hotels/<hid>/rooms", methods=["POST"])
@require_approved_provider
def room_add(hid):
    if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
        return jsonify({"error": "Only hotel admins can manage rooms."}), 403
    doc, err = add_room(request.current_user, hid, request.get_json() or {})
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"hotel": doc}), 201


@hotel_bp.route("/api/hotels/<hid>/room-types/<rtid>/block", methods=["POST"])
@require_login
def block(hid, rtid):
    if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
        return jsonify({"error": "Only hotel admins can manage rooms."}), 403
    doc, err = set_blocked_rooms(request.current_user, hid, rtid,
                                 (request.get_json() or {}).get("blocked", 0))
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"hotel": doc})


@hotel_bp.route("/api/hotels/bookings", methods=["GET"])
@require_login
def bookings():
    if request.current_user["role"] != ROLES["HOTEL_ADMIN"]:
        return jsonify({"error": "Only hotel admins can view their bookings."}), 403
    rows = hotel_bookings(request.current_user["id"])
    return jsonify({"bookings": rows})