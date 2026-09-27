"""Role-specific Partner Hub registration schema (server-side source of truth).

The frontend NEVER hardcodes districts, role lists, field definitions or
verification requirements. It renders whatever ``GET /api/partner/meta`` returns,
which is built from this module plus ``config``.

Design rules enforced here:
  * Every operational role has its own field set, weekly schedule shape,
    verification document list and conditional logic.
  * Every verification document is classified as one of
    ``MANDATORY`` / ``CONDITIONAL`` / ``OPTIONAL`` / ``NOT_APPLICABLE`` and
    carries the source it was derived from.
  * Nothing is invented. Where a legal threshold could not be verified from an
    official source it is recorded with ``verified: False`` and surfaced in the
    UI as "needs confirmation", never as a hard requirement.

Research notes that changed the implementation (kept here so the next
maintainer does not re-introduce the common wrong assumptions):

  * Tamil Nadu has **38 districts** (Revenue & Disaster Management Department
    Economic Policy Note 2025-26: "The State is divided into 38 Districts";
    corroborated by the Tamil Nadu Government Lok Bhavan district list).
  * There is **no single "hotel licence"** in Tamil Nadu. A hotel is a composite
    of GST registration, municipal trade licence, fire NOC and, above a size
    threshold, TNPCB consent to operate.
  * The **Tamil Nadu Fire and Rescue Services Act, 2025 is NOT in force** - it
    commences only on a date the Government may appoint by notification, and no
    commencement notification exists. Fire compliance is therefore built
    against the **Tamil Nadu Fire Service Act, 1985 + Fire Service Rules, 1990**
    administered by TNSWP. The 2025 Act is tracked as watch-list only.
  * A tourist spot does **not** need a general state licence to admit paying
    visitors. There is no universal mandatory "tourist spot licence" in TN.
  * A tour guide does **not** need a statutory licence in Tamil Nadu. The
    Ministry of Tourism's Approved Tourist Guide recognition is voluntary.
  * **E-way bills do not apply to passenger road transport** (freight only), so
    GST TCS via e-way bill is not a passenger-operator requirement.
"""
import base64
import re

from config import (
    ROLES, PARTNER_ROLE_MAP, TAMIL_NADU_DISTRICTS,
    MIN_PARTNER_IMAGES, MAX_IMAGES_PER_PARTNER,
    MAX_IMAGE_BYTES, ALLOWED_IMAGE_MIME, MAX_DATA_URI_CHARS,
)

# Evidence documents are held in the registration payload, so they get a
# tighter per-file budget than a photo and a smaller total allowance.
MAX_DOCUMENT_BYTES = 3 * 1024 * 1024
MAX_DOCUMENT_DATA_URI_CHARS = 4 * 1024 * 1024
ALLOWED_DOCUMENT_MIME = ("application/pdf", "image/jpeg", "image/png", "image/webp")

MANDATORY = "MANDATORY"
CONDITIONAL = "CONDITIONAL"
OPTIONAL = "OPTIONAL"
NOT_APPLICABLE = "NOT_APPLICABLE"

WEEK_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday")

HOTEL_CATEGORIES = ("Budget", "Mid-Range", "Luxury", "Boutique", "Resort", "Other")
RESTAURANT_TYPES = ("Fine Dining", "Casual Dining", "Cafe", "Fast Food",
                    "Street Food", "Multi-Cuisine", "Other")
GUIDE_SPECIALTIES = ("Historical", "Cultural", "Adventure", "Food", "Nature",
                     "Shopping", "Religious", "General")
GUIDE_LANGUAGES = ("Tamil", "English", "Hindi", "Malayalam", "Telugu",
                   "Kannada", "Bengali", "Marathi", "Gujarati", "French",
                   "German", "Japanese", "Arabic", "Other")
TRANSPORT_OPERATING_MODES = ("BUS", "CAB", "AUTO")
# TRAIN is intentionally excluded: train inventory is restricted to the
# authorised IRCTC account and can never be self-registered by a partner.
HOTEL_AMENITIES = ("WiFi", "Parking", "Restaurant", "Gym", "Pool", "Spa",
                   "Air Conditioning", "Laundry", "Wheelchair Accessible",
                   "Pet Friendly", "Family Rooms", "Airport Shuttle")

_SRC = {
    "fssai": "FSSAI (Food Safety and Standards) Regulations - fssai.gov.in",
    "gst": "GST Notification 2/2017 (registration thresholds) - cbic-gst.gov.in",
    "tn_fire_1985": "Tamil Nadu Fire Service Act, 1985 + Fire Service Rules, 1990 (TNSWP) - tn.gov.in",
    "tn_fire_2025": "Tamil Nadu Fire and Rescue Services Act, 2025 (Act 37 of 2025) - NOT YET IN FORCE (S.1(3) commencement by notification)",
    "tnpcb": "Tamil Nadu Pollution Control Board consent categories - ocmms.tnpcb.tn.gov.in",
    "municipal": "Local municipal corporation / local body trade licence - respective TN local body",
    "shops_est": "Tamil Nadu Shops and Establishments Act, 1948 - tn.gov.in",
    "rc": "Motor Vehicles Act, 1988 - registration certificate & fitness certificate (parivahan)",
    "insurance": "Motor Vehicles (Third Party Insurance) Act - commercial vehicle policy",
    "puc": "Centre/State pollution control board - PUC / emissions certificate",
    "permit": "Tamil Nadu State Transport / tourist vehicle permit - TNSTC / transport department",
    "licence": "Motor Vehicles Act, 1988 - driver driving licence with commercial badge",
    "railway": "Indian Railways / IRCTC - rail scheduling and inventory operated solely by Indian Railways",
    "mot_guides": "Ministry of Tourism - Approved Tourist Guide recognition scheme (voluntary)",
    "tn_tourism": "Tamil Nadu Tourism Development Corporation - recognition of tourist places",
    "guide_practical": "Industry/practitioner norm - no statutory Tamil Nadu guide licence found",
    "not_verified": "Could not be verified from an official source - confirm before relying on it",
}


# ---------------------------------------------------------------------------
# Weekly operating schedule
# ---------------------------------------------------------------------------
# Every listing role publishes opening/closing times per weekday. Closed days
# are allowed (a guide may not work Mondays; a restaurant may close on a
# festival). Times are "HH:MM" 24-hour strings.
SCHEDULE = {
    "id": "weeklySchedule",
    "label": "Weekly operating hours",
    "help": "Set the hours a traveller can book or reach you. Leave a day closed if you do not operate.",
    "days": list(WEEK_DAYS),
    "required": True,
    "fields": [
        {"id": "open", "label": "Opens", "type": "time"},
        {"id": "close", "label": "Closes", "type": "time"},
        {"id": "closed", "label": "Closed", "type": "boolean"},
    ],
}


# ---------------------------------------------------------------------------
# Location (shared by every role)
# ---------------------------------------------------------------------------
LOCATION = {
    "id": "location",
    "label": "Business location",
    "required": True,
    "help": "Search for your property, then confirm the district. The pin and "
            "address are filled from Google Maps - we never guess them.",
    "fields": [
        {"id": "address", "label": "Full address", "type": "text", "required": True},
        {"id": "district", "label": "District", "type": "select",
         "options": list(TAMIL_NADU_DISTRICTS), "required": True,
         "help": "All 38 Tamil Nadu districts."},
        {"id": "city", "label": "City / town", "type": "text", "required": True},
        {"id": "placeId", "label": "Google Maps place ID", "type": "hidden",
         "required": True,
         "help": "Captured automatically from the Google Maps place search."},
        {"id": "lat", "label": "Latitude", "type": "hidden", "required": True},
        {"id": "lng", "label": "Longitude", "type": "hidden", "required": True},
    ],
}


IMAGES = {
    "id": "images",
    "label": "Photos",
    "required": True,
    "min": MIN_PARTNER_IMAGES,
    "max": MAX_IMAGES_PER_PARTNER,
    "maxBytes": MAX_IMAGE_BYTES,
    "accept": list(ALLOWED_IMAGE_MIME),
    "help": "Upload at least %d clear photos (JPEG, PNG or WebP, under %d KB each). "
            "Travellers book from these, so show the actual premises."
            % (MIN_PARTNER_IMAGES, MAX_IMAGE_BYTES // 1024),
}


# ---------------------------------------------------------------------------
# Per-role business fields
# ---------------------------------------------------------------------------
def _f(fid, label, required=True, type_="text", **kw):
    out = {"id": fid, "label": label, "required": bool(required), "type": type_}
    out.update(kw)
    return out


ROLE_FIELDS = {
    ROLES["TRANSPORT_ADMIN"]: [
        _f("companyName", "Company / service name", placeholder="e.g. SRL Travels"),
        _f("transportModes", "What do you operate?", type_="multiselect",
           options=list(TRANSPORT_OPERATING_MODES), required=True,
           help="Buses, cabs and auto rickshaws. Trains are added only by IRCTC."),
        _f("fleetSize", "Number of vehicles", type_="number", required=False,
           placeholder="e.g. 12"),
        _f("baseCity", "Base city", required=True, placeholder="e.g. Coimbatore"),
        _f("serviceArea", "Districts served", required=True,
           placeholder="e.g. Coimbatore, Chennai, Salem"),
        _f("companyPhone", "Contact number", type_="tel", required=True,
           placeholder="10-digit mobile"),
        _f("gst", "GST number", required=False, placeholder="15-character GSTIN",
           help="Mandatory if your annual turnover is above the GST threshold."),
        _f("description", "About your fleet", type_="textarea", required=False),
    ],
    ROLES["HOTEL_ADMIN"]: [
        _f("propertyName", "Property name", placeholder="e.g. Chenna Grand Palace"),
        _f("hotelCategory", "Category", type_="select",
           options=list(HOTEL_CATEGORIES)),
        _f("starRating", "Star rating", type_="select",
           options=("1", "2", "3", "4", "5", "6", "7"), required=False,
           help="Optional. Leave blank if you have not been classified."),
        _f("propertyType", "Property type", type_="select", required=True,
           options=("Hotel", "Homestay", "Resort", "Hostel", "Guest House", "Service Apartment", "Other")),
        _f("totalRooms", "Number of rooms", type_="number", required=True,
           placeholder="e.g. 50",
           help="This drives the fire NOC and pollution-board thresholds below."),
        _f("checkInTime", "Check-in time", type_="time", required=True),
        _f("checkOutTime", "Check-out time", type_="time", required=True),
        _f("baseCity", "City", required=True),
        _f("contactPhone", "Contact number", type_="tel", required=True),
        _f("contactEmail", "Contact email", type_="email", required=False),
        _f("amenities", "Amenities", type_="multiselect",
           options=list(HOTEL_AMENITIES), required=False),
        _f("gst", "GST number", required=False, placeholder="15-character GSTIN"),
        _f("description", "About your property", type_="textarea", required=False),
    ],
    ROLES["RESTAURANT_ADMIN"]: [
        _f("restaurantName", "Restaurant name", placeholder="e.g. Annapoorna"),
        _f("restaurantType", "Restaurant type", type_="select",
           options=list(RESTAURANT_TYPES)),
        _f("cuisines", "Cuisines served", required=False,
           placeholder="e.g. South Indian, Chettinad"),
        _f("seatingCapacity", "Seating capacity", type_="number", required=True,
           placeholder="e.g. 60"),
        _f("baseCity", "City", required=True),
        _f("contactPhone", "Contact number", type_="tel", required=True),
        _f("contactEmail", "Contact email", type_="email", required=False),
        _f("gst", "GST number", required=False, placeholder="15-character GSTIN",
           help="Mandatory above the GST threshold; a restaurant supplying both "
                "food and services is treated as a mixed supply."),
        _f("fssaiNumber", "FSSAI licence number", required=False,
           placeholder="14-digit FSSAI number",
           help="Supply your FSSAI number if you already hold one. New operators "
                "are approved by the Main Admin first."),
        _f("description", "About your restaurant", type_="textarea", required=False),
    ],
    ROLES["TOURIST_SPOT_ADMIN"]: [
        _f("spotName", "Attraction name", placeholder="e.g. Chenna Thousand Lights"),
        _f("spotCategory", "Category", type_="select", required=True,
           options=("Historical Site", "Monument", "Museum", "Temple", "Beach",
                    "Hill Station", "Waterfall", "Dam", "Park", "Wildlife Sanctuary",
                    "Theme Park", "Art Gallery", "Other")),
        _f("entryFee", "Entry fee (₹)", type_="number", required=False,
           placeholder="0 if free",
           help="Charging visitors may need separate approval - the Main Admin "
                "will confirm during review."),
        _f("guidedOnly", "Guided entry only", type_="boolean", required=False),
        _f("baseCity", "City", required=True),
        _f("contactPhone", "Contact number", type_="tel", required=True),
        _f("contactEmail", "Contact email", type_="email", required=False),
        _f("gst", "GST number", required=False, placeholder="15-character GSTIN"),
        _f("description", "About this attraction", type_="textarea", required=False),
    ],
    ROLES["GUIDE"]: [
        _f("guideName", "Full name", placeholder="As per your ID"),
        _f("experienceYears", "Years of experience", type_="number", required=True,
           placeholder="e.g. 5"),
        _f("languages", "Languages", type_="multiselect", required=True,
           options=list(GUIDE_LANGUAGES)),
        _f("specialties", "Specialities", type_="multiselect", required=True,
           options=list(GUIDE_SPECIALTIES)),
        _f("baseCity", "Base city", required=True),
        _f("contactPhone", "Contact number", type_="tel", required=True),
        _f("contactEmail", "Contact email", type_="email", required=False),
        _f("pricePerDay", "Charge per day (₹)", type_="number", required=True,
           placeholder="e.g. 2500"),
        _f("pricePerHour", "Charge per hour (₹)", type_="number", required=False),
        _f("description", "Your guiding experience", type_="textarea", required=False),
    ],
}


# ---------------------------------------------------------------------------
# Verification documents
# ---------------------------------------------------------------------------
def _d(did, label, requirement, source, **kw):
    out = {"id": did, "label": label, "requirement": requirement, "source": source}
    out.update(kw)
    return out


def _hotel_documents():
    """Hotel documents are genuinely conditional on property size."""
    return [
        _d("gst_certificate", "GST registration certificate", CONDITIONAL,
           _SRC["gst"],
           condition="Only when annual turnover is above the GST registration "
           "threshold. A property below the threshold is exempt, not "
           "non-compliant, and must not be rejected for this.",
           verified=False,
           note="Threshold is well established; confirm the current value "
           "before rejecting a registration on this basis."),

        _d("trade_licence", "Municipal trade / shops and commercial licence",
           MANDATORY, _SRC["municipal"]),
        _d("fire_noc", "Fire NOC (TNSWP Fire Service)", CONDITIONAL,
           _SRC["tn_fire_1985"],
           condition="Required depending on occupancy and building height.",
           alsoWatch=_SRC["tn_fire_2025"]),
        _d("pollution_consent", "TNPCB consent to operate", CONDITIONAL,
           _SRC["tnpcb"],
           condition="Red: wastewater ≥100 KLD or ≥100 rooms. "
                     "Orange: >20 and <100 rooms with wastewater >10 and <100 KLD "
                     "and a coal/oil-fired boiler. Green: ≤20 rooms, no boiler. "
                     "White: intimation to SPCB suffices, no consent needed."),
        _d("classification_certificate", "Tamil Nadu tourism classification",
           OPTIONAL, _SRC["tn_tourism"],
           help="Voluntary star classification. Leave blank if unclassified."),
    ]


ROLE_DOCUMENTS = {
    ROLES["TRANSPORT_ADMIN"]: [
        _d("rc", "Vehicle registration certificate (RC)", MANDATORY, _SRC["rc"],
           help="One document per registered vehicle, or a consolidated list."),
        _d("fitness_certificate", "Fitness certificate", MANDATORY, _SRC["rc"]),
        _d("insurance", "Commercial motor insurance policy", MANDATORY,
           _SRC["insurance"]),
        _d("puc", "PUC / emissions certificate", MANDATORY, _SRC["puc"]),
        _d("permit", "State transport / tourist vehicle permit", CONDITIONAL,
           _SRC["permit"],
           condition="Required for buses and commercial tourist vehicles. "
                     "Self-drive cabs/auto operating point-to-point may not need "
                     "a route permit - the Main Admin confirms."),
        _d("driver_licence", "Driver licence with commercial badge", MANDATORY,
           _SRC["licence"]),
        _d("gst_certificate", "GST registration certificate", CONDITIONAL,
           _SRC["gst"],
           condition="Annual turnover above the GST registration threshold."),
    ],
    ROLES["HOTEL_ADMIN"]: _hotel_documents(),
    ROLES["RESTAURANT_ADMIN"]: [
        _d("fssai_licence", "FSSAI licence or registration", MANDATORY,
           _SRC["fssai"],
           condition="Every food business operator must hold an FSSAI licence or "
                     "registration. Registration applies to small operators; a "
                     "licence is required above the turnover threshold.",
           verified=False,
           note="Confirm the current turnover threshold with FSSAI before "
                "rejecting on this basis."),
        _d("trade_licence", "Municipal trade licence", MANDATORY, _SRC["municipal"]),
        _d("shops_establishment", "Shops and Establishments registration",
           CONDITIONAL, _SRC["shops_est"],
           condition="Applies once you employ staff."),
        _d("gst_certificate", "GST registration certificate", CONDITIONAL,
           _SRC["gst"],
           condition="A restaurant supplying food plus services is a mixed "
                     "supply, so the higher goods threshold applies.",
           verified=False),
        _d("fire_noc", "Fire NOC (TNSWP Fire Service)", CONDITIONAL,
           _SRC["tn_fire_1985"],
           condition="Required depending on seating capacity and premises.",
           alsoWatch=_SRC["tn_fire_2025"]),
        _d("liquor_licence", "Liquor licence", CONDITIONAL, _SRC["not_verified"],
           condition="Only if you serve alcohol.",
           verified=False),
    ],
    ROLES["TOURIST_SPOT_ADMIN"]: [
        _d("ownership_proof", "Proof of ownership / lease / management contract",
           MANDATORY, _SRC["municipal"],
           help="You must show you are authorised to operate the site."),
        _d("tourism_recognition", "TN Tourism recognition of tourist place",
           OPTIONAL, _SRC["tn_tourism"],
           help="There is NO general mandatory state licence to operate a "
                "tourist spot for paying visitors in Tamil Nadu. Recognition is "
                "a benefit programme, not a precondition."),
        _d("fire_noc", "Fire NOC (TNSWP Fire Service)", CONDITIONAL,
           _SRC["tn_fire_1985"],
           condition="Required for large assembly buildings.",
           alsoWatch=_SRC["tn_fire_2025"]),
        _d("wildlife_clearance", "Wildlife / forest department clearance",
           CONDITIONAL, _SRC["not_verified"],
           condition="Only for sites inside or adjacent to protected areas.",
           verified=False),
    ],
    ROLES["GUIDE"]: [
        _d("identity_proof", "Government photo ID", MANDATORY, _SRC["municipal"]),
        _d("address_proof", "Address proof", MANDATORY, _SRC["municipal"]),
        _d("guide_recognition", "Ministry of Tourism Approved Tourist Guide card",
           OPTIONAL, _SRC["mot_guides"],
           help="Recognition is voluntary. There is NO statutory Tamil Nadu guide "
                "licence; a valid ID plus experience is what is actually needed."),
        _d("professional_evidence", "Experience / training evidence",
           CONDITIONAL, _SRC["guide_practical"],
           condition="Ask for employer letters or tour-company credentials when "
                     "claiming senior experience."),
    ],
}


# ---------------------------------------------------------------------------
# Public metadata payload
# ---------------------------------------------------------------------------
def role_meta(role):
    """Everything the registration wizard needs for one role."""
    fields = list(ROLE_FIELDS.get(role, []))
    include_location = role in PARTNER_ROLE_MAP and role != ROLES["GUIDE"]
    include_schedule = role != ROLES["GUIDE"]
    include_images = role != ROLES["GUIDE"]
    return {
        "role": role,
        "slug": PARTNER_ROLE_MAP[role]["slug"],
        "label": PARTNER_ROLE_MAP[role]["label"],
        "blurb": PARTNER_ROLE_MAP[role]["blurb"],
        "fields": fields,
        "location": dict(LOCATION) if include_location else None,
        "schedule": dict(SCHEDULE) if include_schedule else None,
        "images": dict(IMAGES) if include_images else None,
        "documents": [dict(d) for d in ROLE_DOCUMENTS.get(role, [])],
        "requiresApproval": True,
    }


def partner_meta():
    roles = []
    for role in PARTNER_ROLE_MAP:
        roles.append({
            "role": role,
            "slug": PARTNER_ROLE_MAP[role]["slug"],
            "label": PARTNER_ROLE_MAP[role]["label"],
            "blurb": PARTNER_ROLE_MAP[role]["blurb"],
        })
    return {
        "roles": roles,
        "districts": list(TAMIL_NADU_DISTRICTS),
        "districtCount": len(TAMIL_NADU_DISTRICTS),
        "weekDays": list(WEEK_DAYS),
        "schemas": {role: role_meta(role) for role in PARTNER_ROLE_MAP},
        "images": dict(IMAGES),
        "limits": {
            "minImages": MIN_PARTNER_IMAGES,
            "maxImages": MAX_IMAGES_PER_PARTNER,
            "maxImageBytes": MAX_IMAGE_BYTES,
            "maxDataUriChars": MAX_DATA_URI_CHARS,
            "accept": list(ALLOWED_IMAGE_MIME),
        },
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _is_blank(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _valid_time(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return False
    try:
        hh, mm = int(value[:2]), int(value[3:])
    except ValueError:
        return False
    return 0 <= hh <= 23 and 0 <= mm <= 59


def validate_schedule(schedule):
    """Weekly hours must be well formed and open days must not close before they
    open. An entirely empty schedule is allowed and treated as 'not published'."""
    if _is_blank(schedule):
        return []
    if not isinstance(schedule, dict):
        return ["Weekly operating hours must be an object keyed by weekday."]
    errors = []
    for day, window in schedule.items():
        if day not in WEEK_DAYS:
            continue
        if not isinstance(window, dict):
            errors.append("%s: invalid hours entry." % day)
            continue
        if window.get("closed"):
            continue
        open_t, close_t = window.get("open"), window.get("close")
        if _is_blank(open_t) and _is_blank(close_t):
            continue
        if not _valid_time(open_t):
            errors.append("%s: opening time must be a valid HH:MM time." % day)
        if not _valid_time(close_t):
            errors.append("%s: closing time must be a valid HH:MM time." % day)
        if _valid_time(open_t) and _valid_time(close_t) and close_t <= open_t:
            errors.append("%s: closing time must be later than opening time." % day)
    return errors


def validate_location(location, required=True):
    if _is_blank(location):
        return [] if not required else ["Business location is required."]
    if not isinstance(location, dict):
        return ["Business location must be an object."]
    errors = []
    if required and _is_blank(location.get("address")):
        errors.append("Full address is required.")
    if required and _is_blank(location.get("city")):
        errors.append("City / town is required.")
    district = (location.get("district") or "").strip()
    if required and not district:
        errors.append("District is required.")
    elif district and district not in TAMIL_NADU_DISTRICTS:
        errors.append("District must be one of the %d Tamil Nadu districts."
                      % len(TAMIL_NADU_DISTRICTS))
    # A place must be chosen on the map so we never store a made-up location.
    if required and _is_blank(location.get("placeId")):
        errors.append("Select your location on the Google Maps picker.")
    if not _is_blank(location.get("lat")):
        try:
            lat = float(location.get("lat"))
        except (TypeError, ValueError):
            errors.append("Latitude is not a number.")
        else:
            if not -90 <= lat <= 90:
                errors.append("Latitude is out of range.")
    if not _is_blank(location.get("lng")):
        try:
            lng = float(location.get("lng"))
        except (TypeError, ValueError):
            errors.append("Longitude is not a number.")
        else:
            if not -180 <= lng <= 180:
                errors.append("Longitude is out of range.")
    return errors


def _decoded_size(uri):
    """Real decoded byte length of a data URI, or None if it will not decode.

    Counting characters is not enough: base64 expands 3 bytes into 4
    characters, so a header check alone would let a 12 MB upload through a
    limit that reads like 400 KB.
    """
    try:
        header, _, payload = uri.partition(",")
        if not payload or "base64" not in header.lower():
            return None
        # Validate the alphabet and padding before measuring, so a malformed
        # payload is reported as undecodable rather than a plausible size.
        if re.fullmatch(r"[A-Za-z0-9+/=\s]+", payload) is None:
            return None
        padded = payload + "=" * (-len(payload.rstrip("=")) % 4)
        return len(base64.b64decode(padded, validate=False))
    except Exception:
        return None


def _valid_data_uri(uri):
    if not isinstance(uri, str) or not uri.startswith("data:"):
        return False
    if len(uri) > MAX_DATA_URI_CHARS:
        return False
    header = uri[:64].split(",", 1)[0]
    for mime in ALLOWED_IMAGE_MIME:
        if header.startswith("data:%s" % mime):
            break
    else:
        return False
    size = _decoded_size(uri)
    if size is None:
        return False
    if size == 0:
        return False
    if size > MAX_IMAGE_BYTES:
        return False
    # A declared type that contradicts the magic bytes is a spoofing attempt.
    return _sniff_image_mime(uri) is None or _sniff_image_mime(uri) == header[5:].split(";")[0]


def _sniff_image_mime(uri):
    """Read the real container type from the first bytes of a data URI."""
    try:
        header, _, payload = uri.partition(",")
        if "base64" not in header.lower():
            return None
        head = base64.b64decode(payload[:64] + "=" * (-len(payload[:64].rstrip("=")) % 4),
                                validate=False)
    except Exception:
        return None
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_images(images, required=True):
    if images is None:
        images = []
    if not isinstance(images, list):
        return ["Photos must be uploaded as a list."]
    errors = []
    usable = [i for i in images if _is_blank(i) is False]
    if required and len(usable) < MIN_PARTNER_IMAGES:
        errors.append("Upload at least %d photos of your premises or service."
                      % MIN_PARTNER_IMAGES)
    if len(usable) > MAX_IMAGES_PER_PARTNER:
        errors.append("Upload at most %d photos." % MAX_IMAGES_PER_PARTNER)
    for index, uri in enumerate(usable, start=1):
        if not _valid_data_uri(uri):
            errors.append("Photo %d is not an accepted image (JPEG, PNG or WebP, "
                          "under %d KB)." % (index, MAX_IMAGE_BYTES // 1024))
    return errors


def validate_documents(documents, required_ids=()):
    """Check the uploaded evidence.

    Documents arrive as ``{id, type, data}`` records. This validates the
    per-file size and type so a registration cannot be used as free file
    storage, and reports any mandatory id that was not supplied with actual data.
    """
    if documents is None:
        documents = []
    if not isinstance(documents, list):
        return ["Documents must be uploaded as a list."]
    errors = []
    supplied = set()
    supplied_with_data = set()
    for index, doc in enumerate(documents, start=1):
        if not isinstance(doc, dict):
            errors.append("Document %d is not in the expected format." % index)
            continue
        did = str(doc.get("id") or "").strip()
        if did:
            supplied.add(did)
        data = doc.get("data")
        if _is_blank(data):
            continue
        supplied_with_data.add(did)
        if not isinstance(data, str) or not data.startswith("data:"):
            errors.append("Document %d is not an accepted upload." % index)
            continue
        if len(data) > MAX_DOCUMENT_DATA_URI_CHARS:
            errors.append("Document %d is larger than %d KB."
                          % (index, MAX_DOCUMENT_BYTES // 1024))
            continue
        declared = data[:64].split(",", 1)[0][5:].split(";")[0].lower()
        if declared not in ALLOWED_DOCUMENT_MIME:
            errors.append("Document %d must be a PDF, JPEG, PNG or WebP file."
                          % index)
            continue
        size = _decoded_size(data)
        if not size:
            errors.append("Document %d could not be read." % index)
        elif size > MAX_DOCUMENT_BYTES:
            errors.append("Document %d is larger than %d KB."
                          % (index, MAX_DOCUMENT_BYTES // 1024))
    for did in required_ids or ():
        if did not in supplied_with_data:
            errors.append("Required document '%s' must include file data." % did)
            break
    return errors



def validate_registration(role, data):
    """Validate a Partner Hub registration payload.

    Returns a list of human-readable error strings (empty == valid). The Main
    Admin approval queue shows these, and the client surfaces the same list.
    """
    if role not in PARTNER_ROLE_MAP:
        return ["Unknown partner role."]

    errors = []
    registration = data.get("registration") or {}
    if not isinstance(registration, dict):
        return ["Registration details must be an object."]

    for field in ROLE_FIELDS.get(role, []):
        if not field.get("required"):
            continue
        value = registration.get(field["id"])
        if field.get("type") == "multiselect":
            if _is_blank(value) or not isinstance(value, list) or not value:
                errors.append("%s is required." % field["label"])
            continue
        if _is_blank(value):
            errors.append("%s is required." % field["label"])
            continue
        if field.get("type") == "number":
            try:
                if float(value) < 0:
                    errors.append("%s cannot be negative." % field["label"])
            except (TypeError, ValueError):
                errors.append("%s must be a number." % field["label"])
        if field.get("type") == "email" and "@" not in str(value):
            errors.append("%s must be a valid email address." % field["label"])

    errors += validate_location(registration.get("location"),
                                required=ROLE_FIELDS[role] is not None
                                and role_meta(role)["location"] is not None)
    errors += validate_schedule(registration.get("weeklySchedule"))
    errors += validate_images(data.get("images"),
                              required=role_meta(role)["images"] is not None)

    documents = data.get("documents")
    if documents is None:
        documents = []
    if not isinstance(documents, list):
        errors.append("Verification documents must be uploaded as a list.")
        documents = []

    required_docs = [d for d in ROLE_DOCUMENTS.get(role, [])
                     if d["requirement"] == MANDATORY]
    provided = set()
    for doc in documents:
        if isinstance(doc, dict) and doc.get("type"):
            provided.add(doc["type"])
    for doc in required_docs:
        if doc["id"] not in provided:
            errors.append("%s is required before the Main Admin can approve "
                          "your account." % doc["label"])

    # Per-file type and size checks, so the evidence list cannot be used as
    # free file storage for the account record.
    errors += validate_documents(documents)

    return errors


def verification_summary(role):
    """Grouped counts for the UI: how many mandatory / conditional / optional."""
    docs = ROLE_DOCUMENTS.get(role, [])
    return {
        "mandatory": [d["label"] for d in docs if d["requirement"] == MANDATORY],
        "conditional": [d["label"] for d in docs if d["requirement"] == CONDITIONAL],
        "optional": [d["label"] for d in docs if d["requirement"] == OPTIONAL],
        "unverified": [d["label"] for d in docs if d.get("verified") is False],
    }
