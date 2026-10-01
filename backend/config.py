import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "tripmind")

AI_PROVIDER = os.getenv("AI_PROVIDER", "mock")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "llama-3.3-70b-versatile")

# Google Gemini AI — primary planning/chat backend (replaces the legacy
# Groq-based integration).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

# Cerebras AI — fastest OpenAI-compatible backend (tried first).
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")

APP_URL = os.getenv("APP_URL", "http://localhost:5000")

DEV_MODE = os.getenv("DEV_MODE", "true").lower() in ("1", "true", "yes")

# ------------------------------------------------------------------ Scheduler
# Pre-trip checklist reminders used to be unreachable: notification_service
# computed which checklists were due (due_checklists_for_today) and then nothing
# ever called it, so no traveller was ever reminded. This is the in-process
# scheduler that closes that gap.
#
# It is a plain daemon thread rather than APScheduler/cron because:
#   * it keeps the deployment story at "start the app and it works" - there is
#     no second process to remember to install and no crontab to keep in sync;
#   * every job it runs is idempotent, so being woken twice, or running in two
#     workers, is safe by construction rather than by hoping.
#
# If you would rather run the reminders from system cron (or a Kubernetes
# CronJob), set SCHEDULER_ENABLED=false and call instead:
#     python scripts/run_scheduled_jobs.py
# Both routes go through the same idempotent job functions.
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() in ("1", "true", "yes")

# How often the worker wakes up. Reminders are keyed by (checklist, days-until)
# and claimed with a unique index, so a shorter interval costs one cheap indexed
# query per tick and never a duplicate email. The default is hourly, which is
# well inside the 24-hour granularity any reminder wording implies.
SCHEDULER_INTERVAL_SECONDS = int(
    os.getenv("SCHEDULER_INTERVAL_SECONDS", "3600") or "3600")

# Delay before the first run. Zero would mean the thread hits MongoDB during
# application start-up, before the indexes in ensure_unique_indexes() exist -
# and the reminders ledger depends on one of them. Waiting lets start-up finish.
SCHEDULER_INITIAL_DELAY_SECONDS = int(
    os.getenv("SCHEDULER_INITIAL_DELAY_SECONDS", "30") or "30")

# ---------------------------------------------------------------------------
# ML auto-retrain
# ---------------------------------------------------------------------------
# Models accumulate samples as trips are booked (/api/admin/ml/train still works
# for an on-demand run), but nothing rebuilt them, so every model sat at
# version 0 with the parameters it shipped with. This makes the scheduler
# rebuild them once the sample count has moved far enough to matter.
#
# Off by default. Retraining reads every historical sample and writes new
# parameters, so it is a deliberate act; enable it with ML_AUTOTRAIN_ENABLED=true
# where a background rebuild is wanted.
ML_AUTOTRAIN_ENABLED = os.getenv(
    "ML_AUTOTRAIN_ENABLED", "false").lower() in ("1", "true", "yes")

# Never retrain on a tick where nothing new arrived. Training below this sample
# count would republish the same parameters under a new version number, which
# makes the version history lie about what changed.
ML_AUTOTRAIN_MIN_SAMPLES = int(
    os.getenv("ML_AUTOTRAIN_MIN_SAMPLES", "50") or "50")

# And never retrain more often than this, regardless of how many samples piled
# up. A single day of heavy booking should not trigger a retrain per tick.
ML_AUTOTRAIN_MIN_INTERVAL_SECONDS = int(
    os.getenv("ML_AUTOTRAIN_MIN_INTERVAL_SECONDS", "21600") or "21600")

# Session cookie signing key.
#
# This used to fall back to a hard-coded literal, which meant every deployment
# that forgot to set SECRET_KEY silently shared one publicly known key - anyone
# could forge a session cookie and authenticate as any user, including an
# admin.
#
# Resolution order:
#   1. SECRET_KEY from the environment - used as-is.
#   2. A previously generated key in backend/.secret_key - so restarting the
#      dev server does not log everybody out.
#   3. A freshly generated key, written to that file.
# The hard-coded literal is never used: it is the one value an attacker already
# knows. Outside DEV_MODE the app refuses to boot without an explicit
# SECRET_KEY rather than generate a key that would differ between instances.
_DEV_SECRET_FALLBACK = "tripmind-dev-secret-key"
_GENERATED_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   ".secret_key")


def _read_generated_key():
    try:
        with open(_GENERATED_KEY_FILE, "r", encoding="utf-8") as handle:
            value = handle.read().strip()
        return value or None
    except OSError:
        return None


def _write_generated_key(value):
    try:
        with open(_GENERATED_KEY_FILE, "w", encoding="utf-8") as handle:
            handle.write(value)
        os.chmod(_GENERATED_KEY_FILE, 0o600)
    except OSError:
        # Read-only checkout: still usable for this process, it just will not
        # survive a restart. Losing sessions is better than refusing to boot.
        pass


def _resolve_secret_key():
    raw = (os.getenv("SECRET_KEY") or "").strip()
    if raw and raw != _DEV_SECRET_FALLBACK:
        return raw, "env"
    if not DEV_MODE:
        # Refuse to boot in production with a guessable key rather than serve
        # traffic that is trivially forgeable.
        raise RuntimeError(
            "SECRET_KEY must be set to a unique random value when DEV_MODE is "
            "false. Generate one with: python -c \"import secrets;"
            "print(secrets.token_urlsafe(48))\""
        )
    existing = _read_generated_key()
    if existing:
        return existing, "generated-file"
    value = "%s-%s" % (_DEV_SECRET_FALLBACK, os.urandom(16).hex())
    _write_generated_key(value)
    return value, "generated-new"


SECRET_KEY, SECRET_KEY_SOURCE = _resolve_secret_key()
# True when the key was generated locally rather than supplied by the operator,
# which app.py reports so the situation is never silent.
SECRET_KEY_IS_EPHEMERAL = SECRET_KEY_SOURCE != "env"

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
MAPS_ENABLED = bool(GOOGLE_MAPS_API_KEY)

# WeatherAPI.com key for Smart Packing / Digital Twin weather. Empty = weather
# is reported as unavailable (never fabricated).
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")

# Role constants (single source of truth)
ROLES = {
    "ADMIN": "ADMIN",
    "RAILWAY_ADMIN": "RAILWAY_ADMIN",
    "TRANSPORT_ADMIN": "TRANSPORT_ADMIN",
    "TOURIST_SPOT_ADMIN": "TOURIST_SPOT_ADMIN",
    "HOTEL_ADMIN": "HOTEL_ADMIN",
    "RESTAURANT_ADMIN": "RESTAURANT_ADMIN",
    "GUIDE": "GUIDE",
    "USER": "USER",
}

# Transport types supported by the platform (single source of truth).
# Used by the registration forms, registration validation and catalogue
# search. The keys are stored on the transport documents.
TRANSPORT_TYPES = {
    "BUS": {"label": "Bus", "group": "Road"},
    "TRAIN": {"label": "Train", "group": "Rail"},
    "FLIGHT": {"label": "Flight", "group": "Air"},
    "CAB": {"label": "Cab", "group": "Road"},
    "AUTO": {"label": "Auto Rickshaw", "group": "Road"},
}

# Roles that must pass Main Admin approval before operating on the platform.
# RAILWAY_ADMIN is deliberately excluded from public registration: railway
# inventory is operated solely by Indian Railways / IRCTC and can only be added
# through the internal privileged account (see IRCTC_ADMIN_EMAIL).
PROVIDER_ROLES = {ROLES["TRANSPORT_ADMIN"], ROLES["TOURIST_SPOT_ADMIN"],
                  ROLES["HOTEL_ADMIN"], ROLES["RESTAURANT_ADMIN"],
                  ROLES["GUIDE"]}

# The single IRCTC-authorised account permitted to add or manage TRAIN services
# (and railway lounges). Enforced server-side on every train mutation.
# Overridable only so a local demo environment can provision a matching
# account - production must keep the default.
IRCTC_ADMIN_EMAIL = os.getenv("IRCTC_ADMIN_EMAIL", "irctc@tripmind.com").strip().lower()
RAILWAY_ADMIN_ROLE = ROLES["RAILWAY_ADMIN"]

# TripMind Partner Hub (/tripmind-partner) — the single provider-facing
# experience for every operational (non-passenger) role.
#
# Each entry describes how the role appears in the hub and whether it may be
# self-registered publicly. Main Admin (ADMIN) is intentionally NOT listed: it
# operates the hub, it does not live in it, and it can never be self-registered.
# RAILWAY_ADMIN is also not listed because train inventory is restricted to the
# authorised IRCTC account above.
PARTNER_ROLE_MAP = {
    ROLES["TRANSPORT_ADMIN"]: {
        "slug": "transport",
        "label": "Bus, Cab & Auto Operator",
        "blurb": "Operate buses, cabs and auto rickshaws across Tamil Nadu.",
        "selfRegister": True,
    },
    ROLES["HOTEL_ADMIN"]: {
        "slug": "hotel",
        "label": "Hotel, Homestay & Resort",
        "blurb": "List rooms and properties for TripMind travellers.",
        "selfRegister": True,
    },
    ROLES["RESTAURANT_ADMIN"]: {
        "slug": "restaurant",
        "label": "Restaurant & Cafe",
        "blurb": "Accept TripMind dining reservations.",
        "selfRegister": True,
    },
    ROLES["TOURIST_SPOT_ADMIN"]: {
        "slug": "tourist-spot",
        "label": "Tourist Spot, Attraction & Museum",
        "blurb": "List attractions, museums and guides-only heritage sites.",
        "selfRegister": True,
    },
    ROLES["GUIDE"]: {
        "slug": "guide",
        "label": "Tour Guide",
        "blurb": "Offer licensed sightseeing and itinerary services.",
        "selfRegister": True,
    },
}

# Partner Hub membership = every self-registerable operational role.
PARTNER_ROLES = set(PARTNER_ROLE_MAP)

# Roles that own a public listing on the platform (i.e. a searchable entity in
# addition to the account). Used to decide which dashboards/sections render.
PARTNER_LISTING_ROLES = {
    ROLES["TRANSPORT_ADMIN"], ROLES["HOTEL_ADMIN"],
    ROLES["RESTAURANT_ADMIN"], ROLES["TOURIST_SPOT_ADMIN"],
}

# ------------------------------------------------------------------
# Tamil Nadu districts (server-side single source of truth)
# ------------------------------------------------------------------
# 38 districts, per the Tamil Nadu Government (Lok Bhavan) district list and the
# Revenue & Disaster Management Department Economic Policy Note 2025-26
# ("The State is divided into 38 Districts"). The frontend never hardcodes a
# district list; it renders whatever GET /api/partner/meta returns.
TAMIL_NADU_DISTRICTS = (
    "Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Cuddalore",
    "Dharmapuri", "Dindigul", "Erode", "Kallakurichi", "Kancheepuram",
    "Karur", "Krishnagiri", "Madurai", "Mayiladuthurai", "Nagapattinam",
    "Kanyakumari", "Namakkal", "Perambalur", "Pudukkottai", "Ramanathapuram",
    "Ranipet", "Salem", "Sivaganga", "Tenkasi", "Thanjavur", "Theni",
    "Thiruvallur", "Thiruvarur", "Thoothukudi", "Tiruchirappalli",
    "Tirunelveli", "Tirupathur", "Tiruppur", "Tiruvannamalai",
    "The Nilgiris", "Vellore", "Viluppuram", "Virudhunagar",
)

# ------------------------------------------------------------------
# Partner media + verification limits
# ------------------------------------------------------------------
# Images are stored inline as data URIs on the user document, so the limits are
# deliberately conservative to stay under MongoDB's 16 MB document ceiling.
MIN_PARTNER_IMAGES = 5
MAX_IMAGE_BYTES = 400 * 1024          # 400 KB per image
MAX_IMAGES_PER_PARTNER = 10
ALLOWED_IMAGE_MIME = ("image/jpeg", "image/png", "image/webp")
MAX_DATA_URI_CHARS = 600 * 1024        # ~450 KB of base64 payload

# ------------------------------------------------------------------
# Optional email / notification delivery
# ------------------------------------------------------------------
# Empty SMTP config = notifications are recorded in-app and the send is skipped.
# No message is ever fabricated or reported as "sent" when unconfigured.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")
NOTIFICATIONS_ENABLED = bool(SMTP_HOST and SMTP_FROM)

# URL prefix of the Partner Hub. Every Partner Hub page lives under it and the
# Flask app serves them from frontend/tripmind-partner/.
PARTNER_HUB_PREFIX = "/tripmind-partner"
PARTNER_HUB_DIR = "tripmind-partner"

# Partner Hub pages that may be opened without a signed-in partner account.
PARTNER_PUBLIC_PAGES = {"index.html", "login.html", "register.html", "forbidden.html"}

# Approval states for provider accounts / services.
APPROVAL_STATUSES = ("PENDING", "APPROVED", "REJECTED", "SUSPENDED")
ACCOUNT_STATUSES = ("ACTIVE", "INACTIVE")

ML_ENABLED = os.getenv("ML_ENABLED", "true").lower() in ("1", "true", "yes")

DEMO_USER_ID = "demo-user-1"

ML_CITY_INDEX = {
    "coimbatore": 0, "chennai": 1, "mumbai": 2, "delhi": 3, "bangalore": 4,
    "bengaluru": 4, "kolkata": 5, "hyderabad": 6, "goa": 7, "jaipur": 8,
    "new york": 10, "london": 11, "dubai": 12, "singapore": 13, "tokyo": 14,
    "paris": 15, "bangkok": 16, "sydney": 17,
}

