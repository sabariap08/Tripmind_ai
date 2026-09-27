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

SECRET_KEY = os.getenv("SECRET_KEY", "tripmind-dev-secret-key")

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
MAPS_ENABLED = bool(GOOGLE_MAPS_API_KEY)

# WeatherAPI.com key for Smart Packing / Digital Twin weather. Empty = weather
# is reported as unavailable (never fabricated).
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")

DEV_MODE = os.getenv("DEV_MODE", "true").lower() in ("1", "true", "yes")

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

