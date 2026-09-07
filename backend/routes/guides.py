from flask import Blueprint, request, jsonify
from config import ROLES
from services.auth import require_roles, require_login, require_approved_provider
from services.guide_service import (guide_profile, update_guide_profile,
                                    set_availability, set_pricing,
                                    browse_guides)

guide_bp = Blueprint("guide", __name__)


@guide_bp.route("/api/guide/profile", methods=["GET", "PUT"])
@require_approved_provider
def profile():
    uid = request.current_user["id"]
    if request.method == "PUT":
        if request.current_user["role"] != ROLES["GUIDE"]:
            return jsonify({"error": "Only guides can manage their profile."}), 403
        update_guide_profile(uid, request.get_json() or {})
    return jsonify(guide_profile(uid))


@guide_bp.route("/api/guide/availability", methods=["POST"])
@require_approved_provider
def availability():
    if request.current_user["role"] != ROLES["GUIDE"]:
        return jsonify({"error": "Only guides can set availability."}), 403
    doc, err = set_availability(request.current_user["id"], request.get_json() or {})
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"availability": doc})


@guide_bp.route("/api/guide/pricing", methods=["POST"])
@require_approved_provider
def pricing():
    if request.current_user["role"] != ROLES["GUIDE"]:
        return jsonify({"error": "Only guides can set pricing."}), 403
    doc, err = set_pricing(request.current_user["id"], request.get_json() or {})
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"pricing": doc})


@guide_bp.route("/api/guides", methods=["GET"])
def browse():
    return jsonify({"guides": browse_guides(
        location=request.args.get("location"),
        date=request.args.get("date"))})