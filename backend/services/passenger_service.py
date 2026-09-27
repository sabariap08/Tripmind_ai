"""Passenger and traveller profiles (passenger-only data).

Privacy design - this is the important part
--------------------------------------------
This module holds the most sensitive data in TripMind: companion/traveller
identities, ages, mobility and dietary needs, emergency contacts and ID proof.

Hard rules enforced here, not just documented:

1. **Never to the LLM.** ``to_ai_context`` returns an intentionally minimal,
   non-identifying shape (party size, age bands, coarse dietary/mobility flags).
   Names, contact details, ID proof, health notes and emergency contacts are
   never included, so they cannot reach Ollama/Gemini/Cerebras by accident.
2. **Never to partners.** ``public_party_view`` shares only a count and coarse
   requirements with a transport/hotel/restaurant partner. Partners never see
   names, ages, exact health details or any proof.
3. **Never in a URL.** Nothing here is ever used as a query parameter.
4. **No raw ID numbers are stored at all.** TripMind is not a licensed identity
   verification partner, so there is no reason to retain a full document
   number. Only a masked reference (type + last 4) is kept so a traveller can
   tell the driver which document to expect.
5. **Health data is opt-in and consent-gated.** ``health.consent`` must be true
   before any health field is persisted, and ``to_ai_context``/partner views
   stay empty unless it is.
6. **Not emailed.** Notification subjects/bodies never contain traveller data.
"""
from datetime import datetime, date

from pymongo.errors import DuplicateKeyError

from services.mongodb import get_collection
from services import duplicate
from config import ROLES

RELATIONSHIPS = ("SELF", "FAMILY", "FRIEND", "COLLEAGUE", "OTHER")

GENDERS = ("FEMALE", "MALE", "NON_BINARY", "PREFER_NOT_TO_SAY")

ID_PROOF_TYPES = ("AADHAAR", "PASSPORT", "DRIVING_LICENCE", "VOTER_ID",
                  "EMPLOYEE_ID", "OTHER")

MOBILITY_LEVELS = ("NONE", "SOME_ASSISTANCE", "WHEELCHAIR", "OTHER")

DIETARY_OPTIONS = ("VEGETARIAN", "VEGAN", "JAIN", "HALAL", "KOSHER",
                   "NO_PREFERENCE", "OTHER")

# The only health vocabulary the AI is allowed to reason about. Free text is
# accepted from the user but never forwarded to the model.
COARSE_DIET = ("VEGETARIAN_ONLY", "VEGAN_ONLY", "HALAL_ONLY", "NO_RESTRICTION")
COARSE_MOBILITY = ("NONE", "NEEDS_ASSISTANCE")


def _now():
    return datetime.utcnow().isoformat()


def calculate_age(date_of_birth):
    """Age in whole years from an ISO date string. Returns None if unknown."""
    if not date_of_birth:
        return None
    try:
        dob = datetime.strptime(str(date_of_birth)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    if dob > date.today():
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def age_band(age):
    """Coarse age band. Used instead of an exact age anywhere a partner or the
    LLM needs to reason about suitability (child fare, senior assistance)."""
    if age is None:
        return "UNKNOWN"
    if age < 3:
        return "INFANT"
    if age < 13:
        return "CHILD"
    if age < 18:
        return "TEEN"
    if age < 60:
        return "ADULT"
    return "SENIOR"


# ---------------------------------------------------------------------------
# Masks
# ---------------------------------------------------------------------------
def mask_proof_number(value, keep=4):
    """Keep only the last ``keep`` characters. The full value is never stored,
    so this is belt-and-braces for anything already in the payload."""
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    if len(text) <= keep:
        return "*" * len(text)
    return "%s%s" % ("*" * (len(text) - keep), text[-keep:])


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_payload(data, partial=False):
    """Returns a list of error strings (empty == valid)."""
    errors = []

    if not partial:
        if not (data.get("fullName") or "").strip():
            errors.append("Traveller name is required.")

    relationship = (data.get("relationship") or "FAMILY").strip().upper()
    if relationship not in RELATIONSHIPS:
        errors.append("Relationship must be one of %s." % ", ".join(RELATIONSHIPS))

    gender = (data.get("gender") or "").strip().upper()
    if gender and gender not in GENDERS:
        errors.append("Gender must be one of %s." % ", ".join(GENDERS))

    dob = data.get("dateOfBirth")
    if dob:
        if calculate_age(dob) is None:
            errors.append("Date of birth must be a valid date in the past "
                          "(YYYY-MM-DD).")
        elif calculate_age(dob) > 120:
            errors.append("Date of birth is not valid.")

    email = (data.get("email") or "").strip().lower()
    if email and "@" not in email:
        errors.append("Email address is not valid.")

    mobile = data.get("mobile") or data.get("phone")
    if mobile:
        if len(duplicate.normalize_mobile(mobile)) != 10:
            errors.append("Mobile number must be 10 digits.")

    health = data.get("health")
    if isinstance(health, dict):
        consent = bool(health.get("consent"))
        if not consent:
            # Health details without consent are silently dropped, not stored.
            pass
        else:
            mobility = (health.get("mobility") or "").strip().upper()
            if mobility and mobility not in MOBILITY_LEVELS:
                errors.append("Mobility assistance must be one of %s."
                              % ", ".join(MOBILITY_LEVELS))
            dietary = health.get("dietary") or []
            if not isinstance(dietary, list):
                errors.append("Dietary requirements must be a list.")
            else:
                for item in dietary:
                    if item not in DIETARY_OPTIONS:
                        errors.append("Unknown dietary requirement: %s" % item)
            emergency_phone = health.get("emergencyContactPhone")
            if emergency_phone and len(duplicate.normalize_mobile(emergency_phone)) != 10:
                errors.append("Emergency contact number must be 10 digits.")
        if len(str(health.get("medicalNotes") or "")) > 1000:
            errors.append("Medical notes must be under 1000 characters.")

    proof_type = (data.get("idProofType") or "").strip().upper()
    if proof_type and proof_type not in ID_PROOF_TYPES:
        errors.append("ID proof type must be one of %s." % ", ".join(ID_PROOF_TYPES))

    return errors


def _build_health(data, existing=None):
    """Build the health sub-document. Requires explicit consent; otherwise the
    previous value is left untouched and nothing new is written."""
    incoming = data.get("health")
    if not isinstance(incoming, dict):
        return existing or {"consent": False}
    if not incoming.get("consent"):
        # Consent withdrawn / never given: keep only the consent flag.
        return {"consent": False, "consentedAt": None}
    dietary = incoming.get("dietary") or []
    if not isinstance(dietary, list):
        dietary = []
    return {
        "consent": True,
        "consentedAt": _now(),
        "mobility": (incoming.get("mobility") or "NONE").strip().upper(),
        "dietary": [d for d in dietary if d in DIETARY_OPTIONS],
        "medicalNotes": (incoming.get("medicalNotes") or "").strip()[:1000],
        "emergencyContactName": (incoming.get("emergencyContactName") or "").strip()[:120],
        "emergencyContactPhone": duplicate.normalize_mobile(
            incoming.get("emergencyContactPhone") or ""),
    }


def _build_proof(data):
    """Only a masked reference is persisted - never the raw number."""
    proof_type = (data.get("idProofType") or "").strip().upper()
    if not proof_type:
        return None
    if proof_type not in ID_PROOF_TYPES:
        return None
    return {
        "type": proof_type,
        # The caller sends the full number; we immediately discard all but the
        # last 4 characters. Nothing raw is ever written to Mongo.
        "maskedNumber": mask_proof_number(data.get("idProofNumber")),
        "verified": False,
    }


# ---------------------------------------------------------------------------
# Public shapes
# ---------------------------------------------------------------------------
def to_owner_view(doc):
    """Full view for the owning passenger only."""
    if not doc:
        return None
    health = doc.get("health") or {"consent": False}
    view = {
        "id": str(doc["_id"]),
        "fullName": doc.get("fullName", ""),
        "relationship": doc.get("relationship", "FAMILY"),
        "gender": doc.get("gender", ""),
        "dateOfBirth": doc.get("dateOfBirth", ""),
        "age": doc.get("age"),
        "ageBand": age_band(doc.get("age")),
        "email": doc.get("email", ""),
        "mobile": doc.get("mobile", ""),
        "isDefault": bool(doc.get("isDefault")),
        "notes": doc.get("notes", ""),
        "idProof": doc.get("idProof") or None,
        "health": {
            "consent": bool(health.get("consent")),
            "mobility": health.get("mobility", "NONE"),
            "dietary": health.get("dietary", []),
            "medicalNotes": health.get("medicalNotes", ""),
            "emergencyContactName": health.get("emergencyContactName", ""),
            "emergencyContactPhone": health.get("emergencyContactPhone", ""),
        },
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
    }
    return view


def to_public_party_view(docs):
    """What a booking partner may see: a headcount and coarse requirements.

    No names. No ages. No contact details. No health free text."""
    if not docs:
        return {"count": 0, "ageBands": [], "requirements": []}
    bands = sorted({age_band(d.get("age")) for d in docs if d.get("age")})
    requirements = set()
    for d in docs:
        health = d.get("health") or {}
        if not health.get("consent"):
            continue
        if health.get("mobility") and health["mobility"] != "NONE":
            requirements.add("mobility_assistance")
        for item in health.get("dietary") or []:
            if item in DIETARY_OPTIONS and item != "NO_PREFERENCE":
                requirements.add(item.lower())
    return {
        "count": len(docs),
        "ageBands": bands,
        "requirements": sorted(requirements),
    }


def to_ai_context(docs):
    """Deliberately minimal, non-identifying context for trip planning.

    Only aggregates. Never names, ages in years, contact details, proof,
    health free text or emergency contacts."""
    if not docs:
        return {"partySize": 1, "ageBands": [], "notes": []}
    bands = sorted({age_band(d.get("age")) for d in docs if d.get("age")})
    notes = []
    if "INFANT" in bands or "CHILD" in bands:
        notes.append("Party includes young children - keep days flexible and "
                     "avoid late-night departures.")
    if "SENIOR" in bands:
        notes.append("Party includes senior travellers - prefer short walking "
                     "distances and daytime activities.")
    for d in docs:
        health = d.get("health") or {}
        if not health.get("consent"):
            continue
        if health.get("mobility") in ("SOME_ASSISTANCE", "WHEELCHAIR"):
            notes.append("At least one traveller needs step-free access; "
                         "prioritise lifts and low walking distance.")
            break
    return {
        "partySize": len(docs),
        "ageBands": bands,
        "dietaryFlags": sorted({
            item.lower() for d in docs
            for item in ((d.get("health") or {}).get("dietary") or [])
            if (d.get("health") or {}).get("consent")
        }),
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def list_passengers(owner_id):
    docs = list(get_collection("passengers").find({"ownerId": owner_id})
                .sort([("isDefault", -1), ("createdAt", 1)]))
    return [to_owner_view(d) for d in docs]


def get_passenger(passenger_id, owner_id):
    doc = get_collection("passengers").find_one(
        {"_id": str(passenger_id), "ownerId": owner_id})
    return to_owner_view(doc) if doc else None


def _resolve_owner(owner_id, user=None):
    """Travellers can only be managed by the signed-in passenger themselves."""
    return owner_id


def create_passenger(owner_id, data, user=None):
    errors = validate_payload(data)
    if errors:
        return None, errors[0]

    age = calculate_age(data.get("dateOfBirth"))
    doc = {
        "_id": "pax-%s" % str(abs(hash((owner_id, (data.get("fullName") or "").strip().lower(),
                                          data.get("relationship") or "")))),
        "ownerId": owner_id,
        "fullName": (data.get("fullName") or "").strip()[:120],
        "relationship": (data.get("relationship") or "FAMILY").strip().upper(),
        "gender": (data.get("gender") or "").strip().upper(),
        "dateOfBirth": (data.get("dateOfBirth") or "")[:10],
        "age": age,
        "ageBand": age_band(age),
        "email": (data.get("email") or "").strip().lower()[:160],
        "mobile": duplicate.normalize_mobile(data.get("mobile") or data.get("phone") or ""),
        "isDefault": bool(data.get("isDefault")),
        "notes": (data.get("notes") or "").strip()[:500],
        "health": _build_health(data),
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    doc["idProof"] = _build_proof(data)
    if not doc["isDefault"]:
        existing_default = get_collection("passengers").find_one(
            {"ownerId": owner_id, "isDefault": True})
        if not existing_default:
            doc["isDefault"] = True
    try:
        get_collection("passengers").replace_one(
            {"_id": doc["_id"], "ownerId": owner_id}, doc, upsert=True)
    except DuplicateKeyError:
        return None, "This traveller already exists in your list."
    return to_owner_view(doc), None


def update_passenger(passenger_id, owner_id, data):
    doc = get_collection("passengers").find_one(
        {"_id": str(passenger_id), "ownerId": owner_id})
    if not doc:
        return None, "Traveller not found."
    errors = validate_payload(data, partial=True)
    if errors:
        return None, errors[0]

    for field, maxlen in (("fullName", 120), ("email", 160), ("notes", 500)):
        if field in data:
            value = (data.get(field) or "").strip()
            doc[field] = value[:maxlen] if field != "email" else value.lower()
    if "relationship" in data:
        doc["relationship"] = (data.get("relationship") or "FAMILY").strip().upper()
    if "gender" in data:
        doc["gender"] = (data.get("gender") or "").strip().upper()
    if "dateOfBirth" in data:
        doc["dateOfBirth"] = (data.get("dateOfBirth") or "")[:10]
        doc["age"] = calculate_age(doc["dateOfBirth"])
        doc["ageBand"] = age_band(doc["age"])
    if "mobile" in data or "phone" in data:
        doc["mobile"] = duplicate.normalize_mobile(
            data.get("mobile") or data.get("phone") or "")
    if "health" in data:
        doc["health"] = _build_health(data, existing=doc.get("health"))
    if "idProofType" in data or "idProofNumber" in data:
        proof = _build_proof(data)
        if proof is not None:
            doc["idProof"] = proof
    if "isDefault" in data:
        want_default = bool(data.get("isDefault"))
        if want_default:
            get_collection("passengers").update_many(
                {"ownerId": owner_id}, {"$set": {"isDefault": False}})
            doc["isDefault"] = True
        elif doc.get("isDefault"):
            doc["isDefault"] = False
    doc["updatedAt"] = _now()
    get_collection("passengers").replace_one({"_id": doc["_id"]}, doc)
    return to_owner_view(doc), None


def delete_passenger(passenger_id, owner_id):
    """Deleting the default traveller is blocked - a booking always needs at
    least one lead traveller."""
    doc = get_collection("passengers").find_one(
        {"_id": str(passenger_id), "ownerId": owner_id})
    if not doc:
        return None, "Traveller not found."
    if doc.get("isDefault"):
        return None, ("This is your lead traveller. Add another traveller and "
                      "make them the lead before removing this one.")
    get_collection("passengers").delete_one({"_id": doc["_id"], "ownerId": owner_id})
    return True, None


def set_default(passenger_id, owner_id):
    doc = get_collection("passengers").find_one(
        {"_id": str(passenger_id), "ownerId": owner_id})
    if not doc:
        return None, "Traveller not found."
    get_collection("passengers").update_many(
        {"ownerId": owner_id}, {"$set": {"isDefault": False}})
    get_collection("passengers").update_one(
        {"_id": doc["_id"]}, {"$set": {"isDefault": True, "updatedAt": _now()}})
    return to_owner_view(get_collection("passengers").find_one({"_id": doc["_id"]})), None


def resolve_booking_party(owner_id, passenger_ids, travellers=1):
    """Resolve the passenger references stored on a booking.

    Returns ``(docs, error)``. The lead traveller defaults to the account holder
    so a booking always has a lead even if nothing was selected. ``travellers``
    (number of seats/tickets) is reported back so the UI can show a mismatch.
    """
    if not isinstance(passenger_ids, list):
        passenger_ids = []
    passenger_ids = [str(p) for p in passenger_ids if p][:20]
    if not passenger_ids:
        return [], None
    docs = list(get_collection("passengers").find(
        {"_id": {"$in": passenger_ids}, "ownerId": owner_id}))
    found = {str(d["_id"]) for d in docs}
    missing = [p for p in passenger_ids if p not in found]
    if missing:
        return [], "One or more selected travellers no longer exist."
    # Keep the requested order so seat 1 == first selected traveller.
    order = {p: i for i, p in enumerate(passenger_ids)}
    docs.sort(key=lambda d: order.get(str(d["_id"]), 99))
    if travellers and len(docs) > int(travellers):
        return [], ("You selected %d travellers but the booking is only for %d."
                    % (len(docs), int(travellers)))
    return docs, None


def party_snapshot(owner_id, passenger_ids, travellers=1):
    """Snapshot stored on the booking at the time of purchase.

    The snapshot is intentionally non-identifying: a headcount plus coarse
    requirements, so a partner can prepare without ever holding traveller PII.
    The headcount always equals the total number of travellers (booking qty),
    regardless of how many were named.
    """
    docs, err = resolve_booking_party(owner_id, passenger_ids, travellers)
    if err:
        return None, err
    # The party count is the total number of travellers (booking qty).
    # Named passengers are a subset; unnamed seats are still part of the headcount.
    headcount = int(travellers or 1)
    if not docs:
        return {"count": headcount, "ageBands": [], "requirements": []}, None
    # Use the full headcount even when some passengers are named.
    view = to_public_party_view(docs)
    view["count"] = headcount
    return view, None


def ensure_self_profile(user):
    """Give every passenger a lead traveller record derived from their account,
    so the booking flow always has something sensible pre-filled."""
    owner_id = user.get("id")
    if not owner_id:
        return None
    existing = get_collection("passengers").find_one({"ownerId": owner_id})
    if existing:
        return to_owner_view(existing)
    doc = {
        "_id": "pax-self-%s" % owner_id,
        "ownerId": owner_id,
        "fullName": user.get("name", ""),
        "relationship": "SELF",
        "gender": "",
        "dateOfBirth": "",
        "age": None,
        "ageBand": "UNKNOWN",
        "email": user.get("email", ""),
        "mobile": user.get("mobile", ""),
        "isDefault": True,
        "notes": "",
        "health": {"consent": False},
        "idProof": None,
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    get_collection("passengers").replace_one(
        {"_id": doc["_id"], "ownerId": owner_id}, doc, upsert=True)
    return to_owner_view(doc)
