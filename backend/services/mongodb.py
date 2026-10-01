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
        # One rating per booking, enforced by the database.
        #
        # services/reviews.add_rating already refuses a second rating for a
        # booking, but that check is a read-then-write: two requests that
        # arrive together both see "not rated yet" and both insert, so a
        # double-clicked submit, or a retry after a slow response, produced two
        # ratings for one booking. That double-counts in service_stats, because
        # the average is taken over raw documents rather than per booking.
        #
        # The index makes the invariant true regardless of application timing.
        # It is built unique, so if duplicate ratings already exist from before
        # this index existed, creation fails and is reported as a startup
        # warning rather than silently skipped - the duplicates still need
        # removing by hand, and pretending otherwise would hide a wrong average.
        ("ratings", [("bookingId", 1)], {"unique": True, "sparse": True}),
        # Backs service_stats' match stage and my_ratings' per-user listing.
        ("ratings", [("serviceType", 1), ("serviceId", 1)], {}),
        ("ratings", [("userId", 1), ("createdAt", -1)], {}),
        # One checklist reminder per (checklist, days-until) pair, ever.
        #
        # The scheduler can run hourly in-process, daily from cron, or on demand
        # from the admin endpoint, and more than one of those can be awake at the
        # same time. A "have I sent this already?" check in Python loses that
        # race, so the uniqueness is enforced here instead: a duplicate insert
        # is how a run knows another run already handled that reminder. Without
        # this index the same "2 days to go" email goes out once per scheduler
        # tick for the whole window.
        ("checklist_reminders", [("checklistId", 1), ("daysUntil", 1)],
         {"unique": True}),
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
