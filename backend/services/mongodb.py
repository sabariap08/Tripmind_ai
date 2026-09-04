from pymongo import MongoClient
from config import MONGODB_URI, MONGODB_DB_NAME

_client = None
_db = None


def get_db():
    global _client, _db
    if _db is None:
        if not MONGODB_URI:
            raise RuntimeError("MONGODB_URI is not set in environment variables")
        _client = MongoClient(MONGODB_URI)
        _db = _client[MONGODB_DB_NAME]
    return _db


def get_collection(name):
    return get_db()[name]


def ensure_demo_user():
    db = get_db()
    users = db["users"]
    user = users.find_one({"_id": "demo-user-1"})
    if not user:
        users.insert_one({
            "_id": "demo-user-1",
            "name": "Demo Traveler",
            "email": "demo@tripmind.ai",
            "passwordHash": None,
            "demoIdentifier": "demo",
            "preferredCurrency": "INR",
            "preferences": {
                "preferredTransport": None,
                "preferredHotelType": "4-star",
                "foodPreference": "vegetarian",
                "comfortLevel": "BALANCED",
                "maximumLayover": 4,
                "preferredActivities": "sightseeing"
            }
        })
    return "demo-user-1"
