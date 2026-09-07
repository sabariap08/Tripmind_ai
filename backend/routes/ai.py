from flask import Blueprint, request, jsonify
from services.ai_chat import handle_ai_chat
from services.assistant import handle_assistant_message, execute_action
from services.groq_service import call_ai, is_ai_available
from services.reviews import get_all_reviews
from services.route_mindmap import get_journey_flow
from services.mongodb import get_collection
from services.auth import require_login, current_user

ai_bp = Blueprint("ai", __name__)


def _owned_trip(trip_id, user_id):
    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return None
    if str(trip.get("userId")) != str(user_id):
        return None
    return trip


@ai_bp.route("/api/mindmap/flow", methods=["GET"])
def journey_flow():
    frm = (request.args.get("from") or "Coimbatore").strip()
    to = (request.args.get("to") or "Chennai").strip()
    flow = get_journey_flow(frm, to)
    return jsonify(flow)


@ai_bp.route("/api/ai/chat", methods=["POST"])
@require_login
def ai_chat():
    user = request.current_user
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Message is required"}), 400

    trip_id = data.get("tripId")
    message = data["message"]
    if trip_id and not _owned_trip(trip_id, user.get("id")):
        return jsonify({"error": "Trip not found"}), 404
    result = handle_ai_chat(trip_id, message)
    return jsonify(result)


@ai_bp.route("/api/assistant/chat", methods=["POST"])
@require_login
def assistant_chat():
    user = request.current_user
    data = request.get_json()
    if not data or not (data.get("message") or "").strip():
        return jsonify({"error": "Message is required"}), 400
    trip_id = data.get("tripId")
    if trip_id and not _owned_trip(trip_id, user.get("id")):
        return jsonify({"error": "Trip not found"}), 404
    result = handle_assistant_message(user, data["message"].strip(), trip_id)
    return jsonify(result)


@ai_bp.route("/api/assistant/action", methods=["POST"])
@require_login
def assistant_action():
    """Executes a confirmed assistant proposal. Every mutation is re-validated
    for ownership and current state before it runs."""
    user = request.current_user
    data = request.get_json()
    action_type = data.get("type") if isinstance(data, dict) else None
    params = data.get("params") if isinstance(data, dict) else None
    if action_type not in ("change_transport", "pay_trip", "remove_place"):
        return jsonify({"error": "Unsupported action."}), 400
    payload, status = execute_action(user, action_type, params)
    return jsonify(payload), status


@ai_bp.route("/api/ai/feedback-analysis", methods=["POST"])
@require_login
def feedback_analysis():
    """AI analysis of all trip reviews (structured output, no DB mutation).

    Returns {summary, sentiment, themes, suggestions, rawReviewCount}.
    """
    from services.auth import is_admin
    if not is_admin(request.current_user):
        return jsonify({"error": "Admins only."}), 403
    if not is_ai_available():
        return jsonify({
            "summary": "AI not configured. Showing placeholder analysis.",
            "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
            "themes": [],
            "suggestions": [],
            "rawReviewCount": 0,
        })

    reviews = get_all_reviews(limit=300)
    if not reviews:
        return jsonify({
            "summary": "No reviews yet.",
            "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
            "themes": [],
            "suggestions": [],
            "rawReviewCount": 0,
        })

    review_text = "\n".join(
        f"Rating {r['rating']}/5: {r['comment']} ({r.get('origin','?')}→{r.get('destination','?')})"
        for r in reviews
    )

    system = (
        "You are TripMind AI, a travel analytics engine. "
        "You receive anonymised user reviews of AI-planned trips. "
        "Return ONLY a JSON object (no markdown, no explanation) with this schema: "
        '{"summary":"<1-2 sentence overall summary>",'
        '"sentiment":{"positive":<int>,"neutral":<int>,"negative":<int>},'
        '"themes":[{"theme":"<name>","count":<int>,"sentiment":"positive|neutral|negative"}],'
        '"suggestions":["<actionable improvement>"]}'
    )
    prompt = (
        f"Here are {len(reviews)} user reviews (rating out of 5 + free comment):\n\n"
        f"{review_text}\n\n"
        "Analyse them and return the JSON object described in the system instructions."
    )
    try:
        raw = call_ai(prompt, system)
        import json
        parsed = json.loads(raw)
        parsed["rawReviewCount"] = len(reviews)
        parsed.setdefault("summary", parsed.get("overall_summary") or parsed.get("summary_text") or "See themes and suggestions below.")
        parsed.setdefault("sentiment", {"positive": 0, "neutral": 0, "negative": 0})
        parsed.setdefault("themes", [])
        parsed.setdefault("suggestions", [])
        return jsonify(parsed)
    except Exception:
        return jsonify({
            "summary": "Unable to analyse reviews at this time.",
            "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
            "themes": [],
            "suggestions": [],
            "rawReviewCount": len(reviews),
        })
