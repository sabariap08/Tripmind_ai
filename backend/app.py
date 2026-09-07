import os
import sys
from flask import Flask, send_from_directory
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(__file__))

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

app = Flask(__name__, static_folder=None)
CORS(app, supports_credentials=True)
app.config["SECRET_KEY"] = __import__("config").SECRET_KEY
app.permanent_session_lifetime = __import__("datetime").timedelta(days=7)

from routes.trips import trips_bp
from routes.ai import ai_bp
from routes.auth import auth_bp
from routes.transport import transport_bp
from routes.tourist import tourist_bp
from routes.guides import guide_bp
from routes.hotel import hotel_bp
from routes.restaurant import restaurant_bp
from routes.bookings import booking_bp
from routes.admin import admin_bp
from routes.ml import ml_bp
from routes.ratings import ratings_bp
from routes.analytics import analytics_bp
from routes.wallet import wallet_bp
from routes.tickets import ticket_bp
app.register_blueprint(trips_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(transport_bp)
app.register_blueprint(tourist_bp)
app.register_blueprint(guide_bp)
app.register_blueprint(hotel_bp)
app.register_blueprint(restaurant_bp)
app.register_blueprint(booking_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(ml_bp)
app.register_blueprint(ratings_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(wallet_bp)
app.register_blueprint(ticket_bp)


@app.route("/")
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:path>")
def serve_static(path):
    if path.startswith("api/"):
        return {"error": "API endpoint not found."}, 404
    file_path = os.path.join(FRONTEND_DIR, path)
    if os.path.isfile(file_path):
        return send_from_directory(FRONTEND_DIR, path)
    return send_from_directory(FRONTEND_DIR, "index.html")


if __name__ == "__main__":
    from services.mongodb import ensure_unique_indexes
    errors = ensure_unique_indexes()
    if errors:
        for e in errors:
            print("WARN: index creation skipped:", e)
    app.run(debug=True, host="0.0.0.0", port=5000)
