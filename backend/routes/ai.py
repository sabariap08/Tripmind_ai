from flask import Blueprint, request, jsonify
from services.ai_chat import handle_ai_chat

ai_bp = Blueprint("ai", __name__)


@ai_bp.route("/api/ai/chat", methods=["POST"])
def ai_chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Message is required"}), 400

    trip_id = data.get("tripId")
    message = data["message"]
    result = handle_ai_chat(trip_id, message)
    return jsonify(result)
