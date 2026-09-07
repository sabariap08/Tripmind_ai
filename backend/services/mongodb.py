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


# Case-insensitive collation for name-style uniqueness (owner + name).
_CI = {"locale": "en", "strength": 2}


def ensure_unique_indexes():
    """Create the platform-wide uniqueness indexes (Phase 1, duplicate-data
    prevention). Idempotent and safe to call on every startup.

    Sparse indexes are used for optional identity fields so legacy documents
    (created before these fields existed) are not affected.
    """
    errors = []
    specs = [
        ("users", [("email", 1)], {"unique": True, "sparse": True}),
        ("users", [("mobile", 1)], {"unique": True, "sparse": True}),
        ("users", [("identityType", 1), ("identityNumber", 1)],
         {"unique": True, "sparse": True}),
        ("users", [("gst", 1)], {"unique": True, "sparse": True}),
        ("transports", [("numberKey", 1)], {"unique": True, "sparse": True}),
        ("transports", [("busNumber", 1)], {"unique": True, "sparse": True}),
        ("transports", [("trainNumber", 1)], {"unique": True, "sparse": True}),
        ("transports", [("flightNumber", 1)], {"unique": True, "sparse": True}),
        ("transports", [("vehicleNumber", 1)], {"unique": True, "sparse": True}),
        ("hotels", [("ownerId", 1), ("name", 1)], {"unique": True, "collation": _CI}),
        ("restaurants", [("ownerId", 1), ("name", 1)], {"unique": True, "collation": _CI}),
        ("guide_locations", [("name", 1)], {"unique": True, "collation": _CI}),
    ]
    for coll_name, keys, opts in specs:
        try:
            get_collection(coll_name).create_index(keys, **opts)
        except Exception as exc:  # pragma: no cover - startup resilience
            errors.append("%s (%s): %s" % (coll_name, keys, exc))
    return errors
