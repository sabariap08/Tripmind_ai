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
        ("lounges", [("ownerId", 1), ("name", 1)], {"unique": True, "collation": _CI}),
        ("bookings", [("uniquenessKey", 1)], {"unique": True, "sparse": True}),
        # One checklist per owner + booking, so a double-clicked "generate"
        # can never fork the traveller's list.
        ("checklists", [("ownerId", 1), ("bookingId", 1)], {"unique": True}),
        # Passengers are owner-scoped; the composite index backs every list and
        # the "selected travellers still exist" check on a booking.
        ("passengers", [("ownerId", 1), ("createdAt", 1)], {}),
    ]
    for coll_name, keys, opts in specs:
        try:
            get_collection(coll_name).create_index(keys, **opts)
        except Exception as exc:  # pragma: no cover - startup resilience
            errors.append("%s (%s): %s" % (coll_name, keys, exc))

    # Read indexes for the notification feed. Not unique: duplicates are a
    # cosmetic annoyance, never a correctness problem, so a failure here must
    # not be as loud as a uniqueness violation.
    for coll_name, keys in [("notifications", [("userId", 1), ("createdAt", -1)]),
                            ("notifications", [("userId", 1), ("read", 1)]),
                            ("bookings", [("userId", 1), ("date", 1)])]:
        try:
            get_collection(coll_name).create_index(keys)
        except Exception as exc:  # pragma: no cover - startup resilience
            errors.append("%s (%s): %s" % (coll_name, keys, exc))
    return errors
