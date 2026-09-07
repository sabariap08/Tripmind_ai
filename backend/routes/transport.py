from flask import Blueprint, request, jsonify
from config import ROLES, TRANSPORT_TYPES
from services.auth import require_roles, require_login, is_admin, require_approved_provider
from services.transport_service import (create_transport, update_transport,
                                        get_transport, list_transports,
                                        set_status, set_service_profile,
                                        available_transports)
from services.mongodb import get_collection

transport_bp = Blueprint("transport", __name__)


@transport_bp.route("/api/transport/types", methods=["GET"])
def transport_types():
    return jsonify({
        "types": [{"value": k, "label": v["label"], "group": v["group"]}
                  for k, v in TRANSPORT_TYPES.items()],
    })


def _transport_view(owner, user=None, include_docs=False):
    return {
        "transportId": owner["_id"],
        "type": owner["type"],
        "status": owner["status"],
        "serviceName": owner["serviceName"],
        "summary": _summary(owner),
        "details": owner if include_docs else None,
        "canEdit": bool(user and user["id"] == owner["ownerId"]),
    }


def _summary(t):
    if t["type"] == "BUS":
        return f"{t['busNumber']} : {t['boardingPoint']} (Day {t['boardingDay']} {t['boardingTime']}) -> {t['droppingPoint']}"
    if t["type"] == "TRAIN":
        return f"{t['trainNumber']} {t['trainName']} : {t['boardingStation']} -> {t['destinationStation']}"
    if t["type"] == "FLIGHT":
        return f"{t['flightNumber']} : {t['departureAirport']} -> {t['arrivalAirport']}"
    return f"{t['vehicleNumber']} : {t.get('serviceArea', '')}"


@transport_bp.route("/api/transport/services", methods=["GET", "POST"])
@require_approved_provider
def services():
    user = request.current_user
    if request.method == "POST":
        if user["role"] != ROLES["TRANSPORT_ADMIN"]:
            return jsonify({"error": "Only transport admins can manage a service profile."}), 403
        profile = set_service_profile(user["id"], request.get_json() or {})
        return jsonify({"profile": profile})
    u = get_collection("users").find_one({"_id": user["id"]})
    return jsonify({"profile": (u or {}).get("profile", {})})


@transport_bp.route("/api/transport/list", methods=["GET"])
@require_login
def list_all():
    user = request.current_user
    ttype = request.args.get("type")
    is_owner = user["role"] == ROLES["TRANSPORT_ADMIN"]
    owner_id = user["id"] if is_owner else (request.args.get("ownerId") or None)
    docs = list_transports(owner_id=owner_id, ttype=ttype)
    return jsonify({"transports": [_transport_view(d, user, include_docs=bool(is_owner)) for d in docs]})


@transport_bp.route("/api/transport/register", methods=["POST"])
@require_approved_provider
def register():
    user = request.current_user
    if user["role"] != ROLES["TRANSPORT_ADMIN"]:
        return jsonify({"error": "Only transport admins can register transport."}), 403
    data = request.get_json() or {}
    ttype = (data.get("type") or "").upper()
    if ttype not in TRANSPORT_TYPES:
        return jsonify({"error": "Type must be one of %s." % ", ".join(TRANSPORT_TYPES)}), 400
    doc, err = create_transport(ttype, data, request.current_user["id"])
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"transport": _transport_view(doc, request.current_user)}), 201


@transport_bp.route("/api/transport/<tid>", methods=["GET", "PUT"])
@require_login
def detail(tid):
    doc = get_transport(tid)
    if not doc:
        return jsonify({"error": "Transport not found."}), 404
    if request.method == "PUT":
        if request.current_user["role"] != ROLES["TRANSPORT_ADMIN"]:
            return jsonify({"error": "Not authorized."}), 403
        if request.current_user.get("approvalStatus") != "APPROVED":
            return jsonify({"error": "Your provider account must be approved by the Admin."}), 403
        data = request.get_json() or {}
        data["transportId"] = tid
        new, err = update_transport(doc["type"], data, request.current_user["id"])
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"transport": _transport_view(new, request.current_user)})
    return jsonify({"transport": _transport_view(doc, request.current_user, include_docs=True)})


@transport_bp.route("/api/transport/<tid>/status", methods=["POST"])
@require_login
def approve(tid):
    user = request.current_user
    if not is_admin(user):
        return jsonify({"error": "Only admins can approve transports."}), 403
    data = request.get_json() or {}
    status = data.get("status")
    if status not in ("APPROVED", "REJECTED"):
        return jsonify({"error": "Status must be APPROVED or REJECTED."}), 400
    doc = set_status(tid, status, data.get("reason"))
    return jsonify({"transport": _transport_view(doc, user)})


@transport_bp.route("/api/transport/search", methods=["GET"])
def search():
    origin = request.args.get("origin", "").strip()
    destination = request.args.get("destination", "").strip()
    ttype = request.args.get("type")
    docs = available_transports(origin, destination, ttype)
    return jsonify({"transports": [_transport_view(d, include_docs=True) for d in docs]})