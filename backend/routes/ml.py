"""ML service routes: recommender endpoints, content-based similar items,
cost/time prediction, clusters/segments, demand, anomalies, visit times,
personalized trip ranking and the admin train/status entry points."""
from flask import Blueprint, request, jsonify, current_app

from services.mongodb import get_collection
from services.auth import current_user, require_admin
from services.ml import registry, inference

ml_bp = Blueprint("ml", __name__)


def _user():
    try:
        return current_user(allow_demo=False)
    except Exception:
        return None


def _uid(user):
    if not user:
        return None
    return user.get("id") or user.get("_id") or None


@ml_bp.route("/api/ml/status", methods=["GET"])
def status():
    return jsonify({"enabled": True,
                    "models": registry.complete_registry(),
                    "trainedAt": registry.last_trained_at()})


@ml_bp.route("/api/ml/recommend/spots", methods=["GET"])
def recommend_spots():
    user = _uid(_user())
    city = request.args.get("city")
    interests = [i for i in (request.args.get("interests") or "").split(",") if i]
    limit = int(request.args.get("limit") or 10)
    return jsonify(inference.spots(user, limit=limit, city=city, interests=interests))


@ml_bp.route("/api/ml/recommend/hotels", methods=["GET"])
def recommend_hotels():
    user = _uid(_user())
    city = request.args.get("city")
    limit = int(request.args.get("limit") or 8)
    return jsonify(inference.hotels(user, city=city, limit=limit))


@ml_bp.route("/api/ml/recommend/transports", methods=["GET"])
def recommend_transports():
    user = _uid(_user())
    origin = request.args.get("origin") or ""
    destination = request.args.get("destination") or ""
    pref = request.args.get("type")
    limit = int(request.args.get("limit") or 8)
    return jsonify(inference.transports(user, origin, destination, pref, limit))


@ml_bp.route("/api/ml/recommend/guides", methods=["GET"])
def recommend_guides():
    user = _uid(_user())
    location = request.args.get("location")
    interests = [i for i in (request.args.get("interests") or "").split(",") if i]
    limit = int(request.args.get("limit") or 8)
    return jsonify(inference.guides(user, location=location,
                                    interests=interests, limit=limit))


@ml_bp.route("/api/ml/similar", methods=["GET"])
def similar():
    kind = request.args.get("kind")
    target_id = request.args.get("targetId")
    taste = request.args.get("taste")
    limit = int(request.args.get("limit") or 6)
    return jsonify(inference.similar_items(kind, target_id=target_id,
                                           taste_text=taste, limit=limit))


@ml_bp.route("/api/ml/predict/cost", methods=["GET"])
def predict_cost():
    trip_id = request.args.get("tripId")
    trip = None
    if trip_id:
        trip = get_collection("trips").find_one({"_id": trip_id})
        if not trip:
            trip = get_collection("trips").find_one({"tripId": trip_id})
    return jsonify(inference.cost(user=_uid(_user()), trip=trip))


@ml_bp.route("/api/ml/predict/time", methods=["GET"])
def predict_time():
    item_type = request.args.get("itemType")
    origin = request.args.get("origin")
    destination = request.args.get("destination")
    return jsonify(inference.travel_time(item_type, origin, destination))


@ml_bp.route("/api/ml/clusters", methods=["GET"])
def clusters():
    return jsonify(inference.spot_clusters())


@ml_bp.route("/api/ml/segments", methods=["GET"])
def segments():
    return jsonify(inference.user_segments())


@ml_bp.route("/api/ml/affinity", methods=["GET"])
def affinity():
    user = _uid(_user())
    item_id = request.args.get("itemId")
    return jsonify(inference.affinity(user, item_id))


@ml_bp.route("/api/ml/demand", methods=["GET"])
def demand():
    days = int(request.args.get("days") or 7)
    return jsonify(inference.forecast(days=days))


@ml_bp.route("/api/ml/anomalies", methods=["GET"])
@require_admin
def anomalies():
    limit = int(request.args.get("limit") or 30)
    return jsonify(inference.anomalies(limit=limit))


@ml_bp.route("/api/ml/visit-times", methods=["GET"])
def visit_times():
    spot_id = request.args.get("spotId")
    if not spot_id:
        return jsonify({"error": "spotId required."}), 400
    return jsonify(inference.visit_times(spot_id))


@ml_bp.route("/api/ml/trip-rank", methods=["POST"])
def trip_rank():
    payload = request.get_json(silent=True) or {}
    return jsonify(inference.rank_trip(payload.get("plans") or [],
                                       request_data=payload.get("requestData") or {}))


@ml_bp.route("/api/admin/ml/train", methods=["POST"])
@require_admin
def train():
    from services.ml.train import train_all
    try:
        summary = train_all()
        registry.mark_trained(summary["trainedAt"])
        return jsonify({"ok": True, "summary": summary})
    except Exception as exc:
        current_app.logger.exception("ML training failed")
        return jsonify({"error": f"Training failed: {exc}"}), 500