"""Ticket endpoints: printable PDF ticket download and QR verification.

- GET /api/bookings/<id>/ticket  -> PDF (owner or Admin only)
- GET /api/tickets/verify/<token> -> public, no PII, status-only assertion
"""
from flask import Blueprint, Response, jsonify, request

from services.auth import require_login, is_admin
from services.mongodb import get_collection
from services.ticket_service import (build_ticket_pdf, issue_token, verify_token,
                                     is_trip_token, verify_trip_token)

ticket_bp = Blueprint("tickets", __name__)


@ticket_bp.route("/api/bookings/<bid>/token", methods=["GET"])
@require_login
def booking_token(bid):
    booking = get_collection("bookings").find_one({"_id": bid})
    if not booking:
        return jsonify({"error": "Booking not found."}), 404
    if str(booking.get("userId")) != str(request.current_user.get("id")) \
            and not is_admin(request.current_user):
        return jsonify({"error": "Not authorized."}), 403
    return jsonify({"token": issue_token(booking)})


@ticket_bp.route("/api/bookings/<bid>/ticket", methods=["GET"])
@require_login
def booking_ticket(bid):
    booking = get_collection("bookings").find_one({"_id": bid})
    if not booking:
        return jsonify({"error": "Booking not found."}), 404
    if str(booking.get("userId")) != str(request.current_user.get("id")) \
            and not is_admin(request.current_user):
        return jsonify({"error": "Not authorized to view this ticket."}), 403
    try:
        pdf = build_ticket_pdf(booking)
    except Exception:
        return jsonify({"error": "Could not generate the ticket."}), 500
    ref = booking.get("reference") or "ticket"
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition":
                 'attachment; filename="TripMind-ticket-%s.pdf"' % ref})


@ticket_bp.route("/api/tickets/verify/<token>", methods=["GET"])
def verify_ticket(token):
    token = token or ""
    if is_trip_token(token):
        trip, err = verify_trip_token(token)
        if err:
            return jsonify({"valid": False, "reason": err, "kind": "TRIP"})
        return jsonify({
            "valid": True,
            "kind": "TRIP",
            "status": trip.get("status"),
            "reference": trip.get("reference"),
            "route": "%s -> %s" % ((trip.get("origin") or "-"), (trip.get("destination") or "-")),
            "tripId": str(trip["_id"]),
        })
    booking, err = verify_token(token)
    if err:
        return jsonify({"valid": False, "reason": err, "kind": "BOOKING"})
    return jsonify({
        "valid": True,
        "kind": "BOOKING",
        "status": booking.get("status"),
        "reference": booking.get("reference"),
        "type": booking.get("type"),
        "date": booking.get("date"),
    })