"""Ratings + trip-reviews routes (merged from the former separate blueprints).

- Booking ratings: user-only — eligible bookings, create rating, list mine,
  and per-service stats used by catalogue cards.
- Trip reviews: public read of a trip's reviews, login to add one.
"""
from flask import Blueprint, request, jsonify

from services.auth import require_roles, require_login
from config import ROLES
from services import reviews

ratings_bp = Blueprint("ratings", __name__)


@ratings_bp.route("/api/ratings/eligible", methods=["GET"])
@require_roles(ROLES["USER"], ROLES["ADMIN"])
def eligible():
    return jsonify({"bookings": reviews.eligible_bookings(request.current_user)})


@ratings_bp.route("/api/ratings", methods=["GET"])
@require_roles(ROLES["USER"], ROLES["ADMIN"])
def mine():
    return jsonify({"ratings": reviews.my_ratings(request.current_user)})


@ratings_bp.route("/api/ratings", methods=["POST"])
@require_roles(ROLES["USER"], ROLES["ADMIN"])
def create():
    rating, err = reviews.add_rating(request.current_user, request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"rating": rating}), 201


@ratings_bp.route("/api/ratings/service", methods=["GET"])
def service_stats():
    service_type = (request.args.get("type") or "").upper()
    service_id = request.args.get("id")
    if not service_id:
        return jsonify({"error": "id required."}), 400
    return jsonify(reviews.service_stats(service_type, service_id))


@ratings_bp.route("/api/trips/<trip_id>/reviews", methods=["GET"])
def trip_reviews(trip_id):
    return jsonify({"reviews": reviews.get_trip_reviews(trip_id)})


@ratings_bp.route("/api/trips/<trip_id>/review", methods=["POST"])
@require_login
def add_review(trip_id):
    data = request.get_json() or {}
    review, err = reviews.add_trip_review(
        request.current_user, trip_id,
        data.get("rating"), data.get("comment"))
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"review": review}), 201