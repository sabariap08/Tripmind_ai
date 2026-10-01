import os
import sys
from urllib.parse import urlencode
from flask import Flask, send_from_directory, redirect
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(__file__))

# The planner logs rupee signs and other non-ASCII text to stdout. On a Windows
# console (cp1252 / cp437) that raises UnicodeEncodeError *inside* the planner,
# which is then reported as "AI plan could not be materialised" and the whole
# itinerary generation fails. Force UTF-8 output so logging can never break the
# request path.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config
from services.auth import current_user, is_partner

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
PARTNER_DIR = os.path.join(FRONTEND_DIR, config.PARTNER_HUB_DIR)

app = Flask(__name__, static_folder=None)
CORS(app, supports_credentials=True)

if config.SECRET_KEY_IS_EPHEMERAL:
    # Not fatal in development, but it must not be invisible. config.py has
    # already written the generated key to backend/.secret_key so restarts keep
    # sessions; this records where the key actually came from.
    app.logger.warning(
        "SECRET_KEY is not set in the environment; using the key generated in "
        "backend/.secret_key (source=%s). Set SECRET_KEY in .env to manage it "
        "yourself.", config.SECRET_KEY_SOURCE
    )

# ------------------------------------------------------------------ UTF-8
# Every textual response leaves this app as UTF-8 with an explicit charset.
# TripMind renders en-dashes, middle dots and rupee signs, so a response that
# arrives without a charset is decoded by the browser using a legacy default
# (Windows-1252 on many desktop setups) and the text turns into mojibake:
# "30 Sept 2026 - 8 Oct 2026" becomes "30 Sept 2026 a- 8 Oct 2026".
# Flask's jsonify already escapes to ASCII, so JSON is safe; the headers are
# pinned here so nothing can regress.
_TEXTUAL = ("text/", "application/json", "application/javascript",
            "application/manifest+json", "image/svg+xml")


@app.after_request
def _force_utf8(response):
    ctype = response.headers.get("Content-Type", "") or ""
    base = ctype.split(";", 1)[0].strip().lower()
    if base in _TEXTUAL or any(base.startswith(p) for p in _TEXTUAL):
        if "charset=" not in ctype.lower():
            response.headers["Content-Type"] = ctype + "; charset=utf-8"
    return response

app.config["SECRET_KEY"] = __import__("config").SECRET_KEY
app.permanent_session_lifetime = __import__("datetime").timedelta(days=7)
# Partner registrations post photos and evidence as data URIs. Cap the body at
# a little over the worst legitimate case (10 photos + documents) so an
# oversized request is refused by the server rather than by hope.
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

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
from routes.partner import partner_bp
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
app.register_blueprint(partner_bp)


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


# ------------------------------------------------------------- Startup wiring
# Index creation used to sit inside ``if __name__ == "__main__":``, which meant
# it only ran for ``python app.py``. The app is actually served with
# ``flask --app app run``, where __name__ is "app" and that block never
# executes. So every uniqueness guarantee in ensure_unique_indexes() - one
# rating per booking, one checklist reminder per (checklist, days-until) - was
# documented but absent in the real deployment, and the application-level
# read-then-write checks were the only thing preventing duplicates.
#
# Both hooks live at import time so they apply on every entry point, and both
# are non-fatal: a database that is briefly unreachable at boot must not stop
# the app from serving, it must be retried on the next start.

def _ensure_indexes():
    from services.mongodb import ensure_unique_indexes
    try:
        errors = ensure_unique_indexes()
    except Exception as exc:
        # No database yet (bad URI, container still booting). Say so loudly,
        # because until the indexes exist the uniqueness invariants are
        # genuinely not enforced.
        app.logger.warning("Could not create indexes at startup: %s", exc)
        return
    for e in errors:
        app.logger.warning("Index creation skipped: %s", e)


_ensure_indexes()

# The scheduler starts on the first served request rather than at import, so
# merely importing this module (a test, a CLI probe, a shell) does not leave a
# reminder thread running behind the caller's back.
_scheduler_started = False


@app.before_request
def _start_scheduler_once():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    try:
        from services import scheduler
        scheduler.start()
    except Exception as exc:  # pragma: no cover - never block a request
        app.logger.warning("Scheduler failed to start: %s", exc)


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(debug=debug, host="0.0.0.0",
            port=int(os.environ.get("PORT", "5000")), use_reloader=False)
