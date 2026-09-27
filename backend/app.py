import os
import sys
from urllib.parse import urlencode
from flask import Flask, send_from_directory, redirect
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(__file__))

import config
from services.auth import current_user, is_partner

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
PARTNER_DIR = os.path.join(FRONTEND_DIR, config.PARTNER_HUB_DIR)

app = Flask(__name__, static_folder=None)
CORS(app, supports_credentials=True)
app.config["SECRET_KEY"] = __import__("config").SECRET_KEY
app.permanent_session_lifetime = __import__("datetime").timedelta(days=7)

from routes.trips import trips_bp
from routes.ai import ai_bp
from routes.auth import auth_bp
from routes.transport import transport_bp
from routes.lounge import lounge_bp
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
app.register_blueprint(lounge_bp)
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


# ---------------------------------------------------------------- Partner Hub
# TripMind Partner Hub lives at /tripmind-partner and is a genuinely separate
# experience: its own landing, login and registration pages, and its own
# provider-only pages behind it. Protection is server side (never a frontend
# redirect), so a signed-in passenger who types a Partner Hub URL by hand is
# refused here before any page is served. Every API call the hub makes is
# additionally guarded by services/auth.require_* in the route layer.
#
#   /tripmind-partner                     landing (public)
#   /tripmind-partner/login               partner sign in (public)
#   /tripmind-partner/register            partner registration (public)
#   /tripmind-partner/dashboard           partner only
#   /tripmind-partner/buses               partner only
#   /tripmind-partner/boarding-points     partner only
#   /tripmind-partner/bookings            partner only
#   /tripmind-partner/profile             partner only


def _partner_page(name):
    return send_from_directory(PARTNER_DIR, name)


def _partner_login_redirect(target):
    return redirect("%s/login?%s" % (config.PARTNER_HUB_PREFIX, urlencode({"next": target})))


def _safe_next(value):
    """Only ever follow a Partner Hub path back after sign in."""
    if not value or not isinstance(value, str):
        return ""
    if not value.startswith(config.PARTNER_HUB_PREFIX + "/") and value != config.PARTNER_HUB_PREFIX:
        return ""
    return value


@app.route(config.PARTNER_HUB_PREFIX)
@app.route(config.PARTNER_HUB_PREFIX + "/")
def partner_hub_landing():
    return _partner_page("index.html")


@app.route(config.PARTNER_HUB_PREFIX + "/<path:page>")
def partner_hub_page(page):
    # The hub owns its own stylesheet and scripts (css/partner.css, js/*.js)
    # and every hub page requests them relative to itself, so they arrive here
    # as nested paths. They are assets, not pages, so they are served before
    # the page logic below. send_from_directory refuses anything that escapes
    # PARTNER_DIR, and the leading-dot check keeps the folder private.
    if "/" in page:
        if not page.startswith(".") and os.path.isfile(os.path.join(PARTNER_DIR, page)):
            return send_from_directory(PARTNER_DIR, page)
        return {"error": "Not found."}, 404

    name = page if page.endswith(".html") else page + ".html"
    if name.startswith("."):
        return {"error": "Not found."}, 404
    if name not in config.PARTNER_PUBLIC_PAGES and not os.path.isfile(os.path.join(PARTNER_DIR, name)):
        return _partner_page("index.html")
    if name in config.PARTNER_PUBLIC_PAGES:
        return _partner_page(name)

    # Protected page: a partner session is required. The approval gate itself
    # lives in the API layer (services/auth.require_approved_provider), so a
    # partner whose approval was revoked loses data access even with a live
    # session cookie.
    user = current_user(allow_demo=False)
    if not user:
        return _partner_login_redirect("%s/%s" % (config.PARTNER_HUB_PREFIX, name))
    if not is_partner(user):
        return _partner_page("forbidden.html")
    return _partner_page(name)


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
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(debug=debug, host="0.0.0.0",
            port=int(os.environ.get("PORT", "5000")), use_reloader=False)
