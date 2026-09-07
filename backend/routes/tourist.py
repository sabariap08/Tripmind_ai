from flask import Blueprint, request, jsonify
from config import ROLES
from services.auth import (require_roles, require_login, is_admin,
                           require_approved_provider)
from services.tourist_service import (create_spot, update_spot, get_spot,
                                      list_spots, set_status,
                                      add_guide_location, list_guide_locations,
                                      create_tour, list_tours, get_tour,
                                      set_tour_status)
from services.mongodb import get_collection
from services.guide_service import browse_guides

tourist_bp = Blueprint("tourist", __name__)


@tourist_bp.route("/api/spots", methods=["GET"])
def spots():
    city = request.args.get("city")
    return jsonify({"spots": list_spots(city=city)})


@tourist_bp.route("/api/spots", methods=["POST"])
@require_approved_provider
def add_spot():
    if request.current_user["role"] != ROLES["TOURIST_SPOT_ADMIN"]:
        return jsonify({"error": "Only tourist spot admins can add spots."}), 403
    doc, err = create_spot(request.get_json() or {}, request.current_user["id"])
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"spot": doc}), 201


@tourist_bp.route("/api/spots/<sid>", methods=["GET", "PUT"])
@require_login
def spot(sid):
    if request.method == "PUT":
        if request.current_user["role"] != ROLES["TOURIST_SPOT_ADMIN"]:
            return jsonify({"error": "Not authorized."}), 403
        data = request.get_json() or {}
        data["spotId"] = sid
        doc, err = update_spot(data, request.current_user["id"])
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"spot": doc})
    doc = get_spot(sid)
    if not doc:
        return jsonify({"error": "Spot not found."}), 404
    return jsonify({"spot": doc})


@tourist_bp.route("/api/tours", methods=["GET", "POST"])
@require_login
def tours():
    if request.method == "POST":
        if request.current_user["role"] != ROLES["TOURIST_SPOT_ADMIN"]:
            return jsonify({"error": "Only tourist spot admins can add tours."}), 403
        if request.current_user.get("approvalStatus") != "APPROVED":
            return jsonify({"error": "Your provider account must be approved by the Admin."}), 403
        data = request.get_json() or {}
        doc, err = create_tour(data, request.current_user["id"])
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"tour": doc}), 201
    return jsonify({"tours": list_tours(
        spot_id=request.args.get("spotId"),
        city=request.args.get("city"))})


@tourist_bp.route("/api/tours/<tid>", methods=["GET"])
@require_login
def tour_detail(tid):
    doc = get_tour(tid)
    if not doc or doc.get("status") != "APPROVED":
        return jsonify({"error": "Tour not found."}), 404
    return jsonify({"tour": doc})


@tourist_bp.route("/api/spots/<sid>/status", methods=["POST"])
@require_login
def approve_spot(sid):
    user = request.current_user
    if not is_admin(user):
        return jsonify({"error": "Only admins can approve spots."}), 403
    status = (request.get_json() or {}).get("status")
    if status not in ("APPROVED", "REJECTED"):
        return jsonify({"error": "Status must be APPROVED or REJECTED."}), 400
    return jsonify({"spot": set_status(sid, status)})


@tourist_bp.route("/api/guide-locations", methods=["GET", "POST"])
@require_login
def guide_locations():
    user = request.current_user
    if request.method == "POST":
        if user["role"] != ROLES["TOURIST_SPOT_ADMIN"]:
            return jsonify({"error": "Only tourist spot admins can add guide locations."}), 403
        if user.get("approvalStatus") != "APPROVED":
            return jsonify({"error": "Your provider account must be approved by the Admin."}), 403
        doc, err = add_guide_location(user["id"], request.get_json() or {})
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"location": doc}), 201
    return jsonify({"locations": list_guide_locations(city=request.args.get("city"))})


@tourist_bp.route("/api/guides/browse", methods=["GET"])
def browse():
    return jsonify({"guides": browse_guides(
        location=request.args.get("location"),
        date=request.args.get("date"))})