import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "tripmind")

AI_PROVIDER = os.getenv("AI_PROVIDER", "mock")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "llama-3.3-70b-versatile")

APP_URL = os.getenv("APP_URL", "http://localhost:5000")

SECRET_KEY = os.getenv("SECRET_KEY", "tripmind-dev-secret-key")

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
MAPS_ENABLED = bool(GOOGLE_MAPS_API_KEY)

DEV_MODE = os.getenv("DEV_MODE", "true").lower() in ("1", "true", "yes")

# Role constants (single source of truth)
ROLES = {
    "ADMIN": "ADMIN",
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

# Roles that must pass Admin approval before operating on the platform.
PROVIDER_ROLES = {ROLES["TRANSPORT_ADMIN"], ROLES["TOURIST_SPOT_ADMIN"],
                  ROLES["HOTEL_ADMIN"], ROLES["RESTAURANT_ADMIN"],
                  ROLES["GUIDE"]}

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

