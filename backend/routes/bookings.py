from flask import Blueprint, request, jsonify
from datetime import datetime
from config import ROLES, PROVIDER_ROLES
from services.auth import require_login, require_approved_provider, is_admin
from services.booking_service import (create_booking, cancel_booking, pay_booking,
                                      list_bookings, all_bookings,
                                      respond_guide_request, guide_bookings,
                                      provider_bookings)
from services.mongodb import get_collection

booking_bp = Blueprint("booking", __name__)


@booking_bp.route("/api/bookings", methods=["GET", "POST"])
@require_login
def bookings():
    user = request.current_user
    if request.method == "POST":
        doc, err = create_booking(request.get_json() or {}, user)
        if err:
            return jsonify({"error": err}), 400
        msg = ("Guide request sent. Awaiting guide confirmation."
               if doc["type"] == "GUIDE" else "Booking confirmed.")
        return jsonify({"booking": doc, "message": msg}), 201
    return jsonify({"bookings": list_bookings(user)})


@booking_bp.route("/api/bookings/all", methods=["GET"])
@require_login
def admin_all():
    if not is_admin(request.current_user):
        return jsonify({"error": "Admins only."}), 403
    return jsonify({"bookings": all_bookings()})


@booking_bp.route("/api/bookings/<bid>/pay", methods=["POST"])
@require_login
def pay(bid):
    doc = get_collection("bookings").find_one({"_id": bid})
    if not doc or str(doc.get("userId")) != request.current_user["id"]:
        return jsonify({"error": "Booking not found or not yours."}), 404
    updated, err = pay_booking(doc, request.current_user)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"booking": updated, "message": "Payment completed."})


@booking_bp.route("/api/bookings/<bid>", methods=["DELETE"])
@require_login
def cancel(bid):
    doc, err = cancel_booking(bid, request.current_user)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"booking": doc, "message": "Booking cancelled."})


@booking_bp.route("/api/provider/bookings", methods=["GET"])
@require_approved_provider
def provider_booking_list():
    """Bookings on resources owned by the provider (Transport → Upcoming
    Passengers, Hotel → Hotel Bookings, Tourist Spot → Experience bookings)."""
    btype = (request.args.get("type") or "").upper()
    if btype not in ("TRANSPORT", "HOTEL", "TOUR", "SPOT", "RESTAURANT"):
        return jsonify({"error": "Unsupported booking type."}), 400
    rows = provider_bookings(request.current_user["id"], btype)
    users = {}
    for row in rows:
        uid = str(row.get("userId") or "")
        if uid and uid not in users:
            u = get_collection("users").find_one({"_id": uid}, {"name": 1, "email": 1, "mobile": 1})
            users[uid] = {"name": (u or {}).get("name", ""),
                          "email": (u or {}).get("email", ""),
                          "mobile": (u or {}).get("mobile", "")}
        row["customer"] = users.get(uid, {})
    return jsonify({"bookings": rows})


@booking_bp.route("/api/guide/requests", methods=["GET"])
@require_login
def guide_requests():
    if request.current_user["role"] != ROLES["GUIDE"]:
        return jsonify({"error": "Only guides can view requests."}), 403
    rows = guide_bookings(request.current_user["id"])
    return jsonify({"requests": [b for b in rows if b.get("status") == "PENDING"]})


@booking_bp.route("/api/guide/requests/<bid>", methods=["POST"])
@require_login
def guide_respond(bid):
    if request.current_user["role"] != ROLES["GUIDE"]:
        return jsonify({"error": "Only guides can respond to requests."}), 403
    data = request.get_json() or {}
    doc, err = respond_guide_request(bid, request.current_user["id"],
                                     data.get("action"), data.get("message") or "")
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"booking": doc, "message": "Request handled."})


@booking_bp.route("/api/guide/assignments", methods=["GET"])
@require_login
def guide_assignments():
    if request.current_user["role"] != ROLES["GUIDE"]:
        return jsonify({"error": "Only guides can view assignments."}), 403
    rows = guide_bookings(request.current_user["id"])
    today = datetime.utcnow().strftime("%Y-%m-%d")
    upcoming = [b for b in rows if b.get("status") == "CONFIRMED" and (b.get("date") or "") >= today]
    completed = [b for b in rows if b.get("status") in ("CONFIRMED", "COMPLETED")
                 and (b.get("date") or "") < today]
    return jsonify({"upcoming": upcoming, "completed": completed})