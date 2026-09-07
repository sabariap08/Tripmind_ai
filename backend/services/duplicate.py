"""Global duplicate-data prevention (Phase 1).

Uniqueness is enforced in three defensive layers so a duplicate can never
reach the database even under concurrent requests:

1. MongoDB unique indexes (see services/mongodb.ensure_unique_indexes).
2. Backend field-level checks before inserts / updates (this module).
3. Live availability checks exposed to the frontend
   (GET /api/auth/check-availability).

Canonicalization helpers guarantee one logical value (a case-insensitive
email, a punctuation-insensitive serial number, a digit-only mobile) can be
stored only once regardless of how it is typed.
"""
from services.mongodb import get_collection
from config import ROLES

# Case-insensitive collation used for name-type uniqueness.
CI = {"locale": "en", "strength": 2}

# transport document field -> its transport type
TRANSPORT_NUMBER_FIELDS = {
    "busNumber": "BUS",
    "trainNumber": "TRAIN",
    "flightNumber": "FLIGHT",
    "vehicleNumber": None,  # CAB / AUTO
}

USER_UNIQUE_FIELDS = ("email", "mobile", "identityNumber", "gst")


# --- Canonicalization -------------------------------------------------------

def normalize_email(value):
    return (value or "").strip().lower()


def normalize_mobile(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) >= 12 and digits.startswith("91"):
        digits = digits[-10:]
    elif len(digits) >= 11 and digits.startswith("0"):
        digits = digits[-10:] if digits[-10:].lstrip("0") else digits
    return digits


def normalize_identifier(value):
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def normalize_gst(value):
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def normalize_serial(value):
    """Registration / vehicle serial numbers: uppercase, collapse whitespace,
    keep meaningful punctuation (e.g. TN-37 BY 8140)."""
    return " ".join(str(value or "").upper().split())


def valid_mobile(value):
    digits = normalize_mobile(value)
    return len(digits) == 10 and digits[0] in "6789"


# --- User-level uniqueness --------------------------------------------------

def _taken(collection, query, collation=None, exclude_id=None):
    if exclude_id is not None:
        query = dict(query)
        query["_id"] = {"$ne": exclude_id}
    return collection.find_one(query, {"_id": 1}, collation=collation) is not None


def email_taken(email):
    return _taken(get_collection("users"), {"email": normalize_email(email)})


def mobile_taken(mobile):
    digits = normalize_mobile(mobile)
    if not digits:
        return False
    return _taken(get_collection("users"), {"mobile": digits})


def identity_taken(identity_type, identity_number):
    idn = normalize_identifier(identity_number) if identity_number else ""
    if not idn:
        return False
    return _taken(get_collection("users"),
                  {"identityType": (identity_type or "").strip(), "identityNumber": idn})


def gst_taken(gst):
    key = normalize_gst(gst) if gst else ""
    if not key:
        return False
    return _taken(get_collection("users"), {"gst": key})


def register_duplicate_check(data):
    """Field-level availability scan for a registration payload.

    Returns {"field": ..., "message": ...} on the first collision, else None.
    """
    email = data.get("email")
    if email and email_taken(email):
        return {"field": "email", "message": "An account with this email already exists."}

    mobile = data.get("mobile") or data.get("phone")
    if mobile:
        if not valid_mobile(mobile):
            return {"field": "mobile", "message": "Enter a valid 10-digit mobile number."}
        if mobile_taken(mobile):
            return {"field": "mobile", "message": "This mobile number is already registered."}

    identity_type = (data.get("identityType") or "").strip()
    identity_number = data.get("identityNumber")
    if identity_type and identity_number:
        if identity_taken(identity_type, identity_number):
            return {"field": "identityNumber",
                    "message": "This %s is already registered." % identity_type}

    gst = data.get("gst")
    if gst and gst_taken(gst):
        return {"field": "gst", "message": "This GST number is already registered."}

    return None


# --- Transport / hotel / restaurant uniqueness ------------------------------

def transport_number_taken(field, value, exclude_id=None):
    key = normalize_serial(value)
    if not key:
        return False
    coll = get_collection("transports")
    # Canonical numberKey is the DB-enforced unique field (set by
    # transport_service._build). Fall back to the raw typed field with a
    # case-insensitive collation so legacy documents without numberKey are
    # still caught by the service layer.
    if _taken(coll, {"numberKey": key}, exclude_id=exclude_id):
        return True
    if field in TRANSPORT_NUMBER_FIELDS:
        return _taken(coll, {field: key}, collation=CI, exclude_id=exclude_id)
    return False


def owned_name_taken(collection, owner_id, name, exclude_id=None):
    if not name:
        return False
    return _taken(get_collection(collection),
                  {"ownerId": str(owner_id), "name": str(name).strip()},
                  collation=CI, exclude_id=exclude_id)


def check_available(field, value, user=None, identity_type=""):
    """Resolve a live availability query. Returns True/False or None when the
    field is not a supported availability check."""
    field = (field or "").lower().strip()
    value = (value or "").strip()

    if field == "email":
        return not email_taken(value)
    if field in ("mobile", "phone"):
        if not valid_mobile(value):
            return False
        return not mobile_taken(value)
    if field == "identityNumber":
        if not identity_type:
            identity_type = (user or {}).get("identityType", "") if user else ""
        return not identity_taken(identity_type, value)
    if field == "gst":
        return not gst_taken(value)
    if field in TRANSPORT_NUMBER_FIELDS:
        return not transport_number_taken(field, value)
    if field in ("hotelName", "restaurantName"):
        if not user or not user.get("id"):
            return None
        coll = "hotels" if field == "hotelName" else "restaurants"
        return not owned_name_taken(coll, user["id"], value)
    return None


def normalize_registration_fields(data):
    """Attach canonical unique fields onto a registration payload (in place of
    a separate validator) so services always store the normalized value."""
    if "email" in data:
        data["email"] = normalize_email(data["email"])
    if data.get("mobile") or data.get("phone"):
        data["mobile"] = normalize_mobile(data.get("mobile") or data.get("phone"))
    if data.get("identityNumber"):
        data["identityNumber"] = normalize_identifier(data["identityNumber"])
        data["identityType"] = (data.get("identityType") or "").strip()
    if data.get("gst"):
        data["gst"] = normalize_gst(data["gst"])
    return data


# ---------------------------------------------------------------------------
# Role-specific provider registration field definitions (merged from the former
# services/registration_fields module).
#
# The business details for every provider account are DECLARED AT REGISTRATION
# and never edited again from the dashboard — the dashboard shows them read-only.
# This is the single source of truth for the fields the registration wizard
# collects, so the Main Admin can review exactly the same data during approval.
# ---------------------------------------------------------------------------

WEEK_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday")

HOTEL_CATEGORIES = ("Budget", "Mid-Range", "Luxury", "Boutique", "Resort", "Other")
RESTAURANT_TYPES = ("Fine Dining", "Casual Dining", "Cafe", "Fast Food",
                    "Street Food", "Multi-Cuisine", "Other")
GUIDE_SPECIALTIES = ("Historical", "Cultural", "Adventure", "Food", "Nature",
                     "Shopping", "Night Life", "General")

# Fields shown in the registration wizard for each provider role. Each entry:
#   id, label, required, type (text|number|select|textarea), options, placeholder
# The `gst` field is special-cased by the wizard (live duplicate check, stored
# on the account top level) and is therefore always sent back to the client.
ROLE_FIELDS = {
    ROLES["TRANSPORT_ADMIN"]: [
        {"id": "companyName", "label": "Company / service name", "required": True,
         "placeholder": "e.g. SRL Travels"},
        {"id": "serviceArea", "label": "Primary service area", "required": True,
         "placeholder": "e.g. Coimbatore district"},
        {"id": "companyCity", "label": "City", "required": True,
         "placeholder": "e.g. Coimbatore"},
        {"id": "companyAddress", "label": "Company address", "required": True,
         "placeholder": "Registered office address"},
        {"id": "companyPhone", "label": "Contact number", "required": True,
         "placeholder": "10-digit mobile"},
        {"id": "gst", "label": "GST number", "required": False,
         "placeholder": "15-character GST number (optional)"},
        {"id": "driverCount", "label": "Number of drivers", "type": "number",
         "required": False, "placeholder": "Optional"},
        {"id": "description", "label": "Company description", "type": "textarea",
         "required": False, "placeholder": "Tell travellers about your fleet"},
    ],
    ROLES["TOURIST_SPOT_ADMIN"]: [
        {"id": "organisationName", "label": "Organisation name", "required": True,
         "placeholder": "e.g. Heritage Tamil Nadu"},
        {"id": "organisationCity", "label": "City", "required": True,
         "placeholder": "e.g. Chennai"},
        {"id": "contactNumber", "label": "Contact number", "required": True,
         "placeholder": "10-digit mobile"},
        {"id": "gst", "label": "GST number", "required": False,
         "placeholder": "15-character GST number (optional)"},
    ],
    ROLES["HOTEL_ADMIN"]: [
        {"id": "hotelName", "label": "Hotel name", "required": True,
         "placeholder": "e.g. Chenna Grand Palace"},
        {"id": "hotelCategory", "label": "Hotel category", "type": "select",
         "options": HOTEL_CATEGORIES, "required": True},
        {"id": "starRating", "label": "Star rating", "type": "select",
         "options": ("1", "2", "3", "4", "5", "6", "7"), "required": True},
        {"id": "hotelCity", "label": "City", "required": True,
         "placeholder": "e.g. Chennai"},
        {"id": "hotelAddress", "label": "Address", "required": True,
         "placeholder": "Full property address"},
        {"id": "contactNumber", "label": "Contact number", "required": True,
         "placeholder": "10-digit mobile"},
        {"id": "email", "label": "Contact email", "type": "email", "required": False},
        {"id": "checkInTime", "label": "Check-in time (24h)", "type": "time",
         "required": True, "placeholder": "12:00"},
        {"id": "checkOutTime", "label": "Check-out time (24h)", "type": "time",
         "required": True, "placeholder": "11:00"},
        {"id": "totalRooms", "label": "Total number of rooms", "type": "number",
         "required": True, "placeholder": "e.g. 50"},
        {"id": "gst", "label": "GST number", "required": False,
         "placeholder": "15-character GST number (optional)"},
    ],
    ROLES["RESTAURANT_ADMIN"]: [
        {"id": "restaurantName", "label": "Restaurant name", "required": True,
         "placeholder": "e.g. Annapoorna"},
        {"id": "restaurantType", "label": "Restaurant type", "type": "select",
         "options": RESTAURANT_TYPES, "required": True},
        {"id": "restaurantCity", "label": "City", "required": True,
         "placeholder": "e.g. Chennai"},
        {"id": "restaurantAddress", "label": "Address", "required": True,
         "placeholder": "Full address"},
        {"id": "contactNumber", "label": "Contact number", "required": True,
         "placeholder": "10-digit mobile"},
        {"id": "email", "label": "Contact email", "type": "email", "required": False},
        {"id": "cuisines", "label": "Cuisines", "required": False,
         "placeholder": "e.g. North Indian, South Indian, Chinese"},
        {"id": "gst", "label": "GST number", "required": False,
         "placeholder": "15-character GST number (optional)"},
    ],
    ROLES["GUIDE"]: [
        {"id": "experience", "label": "Experience (years)", "type": "number",
         "required": True, "placeholder": "e.g. 5"},
        {"id": "languages", "label": "Languages spoken", "required": True,
         "placeholder": "Comma separated (e.g. Tamil, English, Hindi)"},
        {"id": "specialty", "label": "Specialty", "type": "select",
         "options": GUIDE_SPECIALTIES, "required": True},
        {"id": "pricePerHour", "label": "Charges per hour (₹)", "type": "number",
         "required": True, "placeholder": "e.g. 500"},
        {"id": "pricePerDay", "label": "Charges per day (₹)", "type": "number",
         "required": True, "placeholder": "e.g. 3000"},
        {"id": "guideCity", "label": "Base location", "required": True,
         "placeholder": "e.g. Mylapore, Chennai"},
        {"id": "description", "label": "About me", "type": "textarea",
         "required": False, "placeholder": "Tell travellers about your experience"},
    ],
}


def role_fields(role):
    """Return the mutable field definitions for a provider role.

    ``gst`` is returned independently so the wizard can keep its live
    duplicate check; it is stored on the account, not in ``registration``.
    """
    fields = [dict(f) for f in ROLE_FIELDS.get(role, [])]
    gst = None
    for f in fields:
        if f.get("id") == "gst":
            gst = f
    if gst:
        fields.remove(gst)
    return fields, gst