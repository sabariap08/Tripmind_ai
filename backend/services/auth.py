"""Authentication + Role-Based Access Control.

Uses Flask signed-cookie sessions (no extra dependency). Passwords are hashed
with werkzeug. Every API operates on a real authenticated account; there is no
anonymous demo-user fallback.
"""
from functools import wraps
from flask import session, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from bson.objectid import ObjectId
from pymongo.errors import DuplicateKeyError
from services.mongodb import get_collection
from services import duplicate
from services import partner_schema
from config import (ROLES, PROVIDER_ROLES, PARTNER_ROLES, APPROVAL_STATUSES,
                    IRCTC_ADMIN_EMAIL)

SESSION_USER_KEY = "tripmind_user"


def new_user_id():
    return str(ObjectId())


def mask_sensitive(value, keep=2):
    """Mask an identity/registration number for display.

    Proof numbers and identity numbers are stored in full but are never echoed
    back to the browser. The Main Admin approval queue reads the raw document
    from Mongo directly instead of relying on the public session payload.
    """
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    if len(text) <= keep * 2:
        return "*" * len(text)
    return "%s%s%s" % (text[:keep], "*" * (len(text) - keep * 2), text[-keep:])


def _base_user(data, role):
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip()

    if not email or not password or not name:
        return None, None, "Name, email and password are required."
    if len(password) < 8:
        return None, None, "Password must be at least 8 characters."
    if get_collection("users").find_one({"email": email}):
        return None, None, "An account with this email already exists."
    payload = {
        "name": name,
        "email": email,
        "passwordHash": generate_password_hash(password),
        "role": role,
    }
    # Canonical identity fields (unique indexes in services/mongodb).
    mobile = duplicate.normalize_mobile(data.get("mobile") or data.get("phone"))
    if len(mobile) == 10:
        payload["mobile"] = mobile
    identity_type = (data.get("identityType") or "").strip()
    identity_number = duplicate.normalize_identifier(data.get("identityNumber"))
    if identity_type and identity_number:
        payload["identityType"] = identity_type
        payload["identityNumber"] = identity_number
    gst = duplicate.normalize_gst(data.get("gst")) if data.get("gst") else ""
    if len(gst) >= 5:
        payload["gst"] = gst
    prefs = data.get("preferences")
    if isinstance(prefs, dict) and prefs:
        payload["preferences"] = prefs
    return payload, None, None


def register_user(data, role=ROLES["USER"]):
    """Public registration for Normal Users. No manual Admin approval required."""
    payload, _, err = _base_user(data, role)
    if err:
        return None, err
    user = {
        "_id": new_user_id(),
        **payload,
        "status": "ACTIVE",
        "approved": True,
        "approvalStatus": "APPROVED",
        "profile": {},
        "createdAt": datetime.utcnow().isoformat(),
    }
    try:
        get_collection("users").insert_one(user)
    except DuplicateKeyError:
        return None, "An account with this email, mobile or identity detail already exists."
    user.pop("passwordHash", None)
    return user, None


def register_provider(data, role):
    """Partner Hub registration for every operational role.

    The account is created PENDING and can never reach a dashboard or a
    publishing API until the Main Admin approves it. Role-specific business
    fields, weekly hours, Google Maps location, photos and verification
    documents are validated server-side and stored verbatim so the Main Admin
    reviews exactly what was submitted.
    """
    if role not in PROVIDER_ROLES:
        # RAILWAY_ADMIN is intentionally unreachable here: train inventory is
        # restricted to the internal authorised IRCTC account.
        return None, "Invalid partner role."

    # Validate the role-specific payload BEFORE creating the account.
    errors = partner_schema.validate_registration(role, data)
    if errors:
        return None, errors[0]

    payload, _, err = _base_user(data, role)
    if err:
        return None, err
    registration = data.get("registration")
    if isinstance(registration, dict) and registration:
        registration = {k: v for k, v in registration.items() if v is not None}
    else:
        registration = {}
    documents = data.get("documents") or []
    images = data.get("images") or []
    profile = data.get("profile")
    merged_profile = {"scope": ""}
    if isinstance(profile, dict):
        merged_profile.update(profile)
    user = {
        "_id": new_user_id(),
        **payload,
        "status": "ACTIVE",
        "approved": False,
        "approvalStatus": "PENDING",
        "approvalReason": "",
        "registration": registration,
        "documents": documents,
        "images": images,
        "profile": merged_profile,
        "createdAt": datetime.utcnow().isoformat(),
    }
    try:
        get_collection("users").insert_one(user)
    except DuplicateKeyError:
        return None, "An account with this email, mobile or identity detail already exists."
    user.pop("passwordHash", None)
    return user, None


def login_user(email, password, remember=False):
    """Sign a user in.

    ``remember`` controls the lifetime of the signed session cookie:
    True  -> persistent cookie that survives a browser restart
             (app.permanent_session_lifetime, 7 days).
    False -> browser-session cookie, discarded when the browser closes.
    The cookie is always a Flask *signed* cookie holding only the user id,
    never a password.
    """
    users = get_collection("users")
    user = users.find_one({"email": (email or "").strip().lower()})
    if not user or not check_password_hash(user.get("passwordHash", ""), password or ""):
        return None, "Invalid email or password."
    if user.get("status") != "ACTIVE":
        return None, "Account is not active."
    approval_status = user.get("approvalStatus")
    if approval_status == "SUSPENDED":
        return None, "Your account has been suspended. Please contact the platform administrator."
    if user.get("role") in PROVIDER_ROLES and approval_status != "APPROVED":
        # Fail closed. A provider document with a missing/unknown approval state
        # must NOT be able to sign in - that was a real hole in the old code,
        # which silently fell through to success.
        if approval_status == "PENDING":
            return None, "Your account is pending Main Admin approval."
        if approval_status == "REJECTED":
            reason = user.get("approvalReason") or "no reason provided"
            return None, "Your registration was rejected. Reason: %s" % reason
        return None, ("Your account is not approved. Please contact the platform "
                      "administrator.")
    session[SESSION_USER_KEY] = str(user["_id"])
    session.permanent = bool(remember)
    session["_permanent"] = bool(remember)
    return _public_user(user), None


def logout_user():
    session.pop(SESSION_USER_KEY, None)


def _public_user(user):
    pub = {
        "id": str(user["_id"]),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role", ROLES["USER"]),
        "approved": user.get("approved", True),
        "approvalStatus": user.get("approvalStatus", "APPROVED" if user.get("approved") else "PENDING"),
        "status": user.get("status", "ACTIVE"),
        "profile": user.get("profile", {}),
        "registration": user.get("registration", {}),
        "documents": user.get("documents", []),
        "images": user.get("images", []),
        "approvalReason": user.get("approvalReason", ""),
        "rejectedAt": user.get("rejectedAt"),
        "rejectedBy": user.get("rejectedBy"),
        "approvedAt": user.get("approvedAt"),
        "approvedBy": user.get("approvedBy"),
        "mobile": user.get("mobile", ""),
        "identityType": user.get("identityType", ""),
        # Masked in the session payload. The Main Admin approval queue reads the
        # raw document from Mongo so the real value never travels to a browser.
        "identityNumber": mask_sensitive(user.get("identityNumber")),
        "gst": user.get("gst", ""),
        "preferences": user.get("preferences", {}),
    }
    if user.get("role") in (ROLES["TRANSPORT_ADMIN"], ROLES["RAILWAY_ADMIN"]):
        pub["transportServiceId"] = str(user["_id"])
    if user.get("role") in PARTNER_ROLES:
        meta = partner_schema.role_meta(user["role"])
        pub["partner"] = {
            "slug": meta["slug"],
            "label": meta["label"],
            "requiresApproval": True,
        }
    return pub


def current_user(allow_demo=True):
    """Return the logged-in user (public shape) or None. The legacy demo-user
    fallback has been removed: every API must operate on a real account."""
    uid = session.get(SESSION_USER_KEY)
    if uid:
        user = get_collection("users").find_one({"_id": uid})
        if user:
            return _public_user(user)
        session.pop(SESSION_USER_KEY, None)
    return None


def require_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user(allow_demo=False)
        if not user:
            return jsonify({"error": "Authentication required. Please log in."}), 401
        if user.get("approvalStatus") == "SUSPENDED" or user.get("status") != "ACTIVE":
            session.pop(SESSION_USER_KEY, None)
            return jsonify({"error": "Your account has been suspended. Please contact the platform administrator."}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper


def require_roles(*roles):
    """RBAC guard: deny when the user's role is not in the allowed set."""
    allowed = set(roles)

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = current_user(allow_demo=False)
            if not user:
                return jsonify({"error": "Authentication required. Please log in."}), 401
            if user.get("approvalStatus") == "SUSPENDED" or user.get("status") != "ACTIVE":
                session.pop(SESSION_USER_KEY, None)
                return jsonify({"error": "Your account has been suspended. Please contact the platform administrator."}), 403
            if user["role"] not in allowed:
                return jsonify({"error": "You do not have access to this resource."}), 403
            request.current_user = user
            return f(*args, **kwargs)
        return wrapper
    return decorator


def is_admin(user):
    return bool(user) and user["role"] == ROLES["ADMIN"]


def is_partner(user):
    """TripMind Partner Hub membership.

    Every operational role lives in the hub now - bus/cab/auto operators,
    hotels, restaurants, tourist spots and guides. A plain passenger is never a
    partner, and Main Admin is not a partner either (it operates the hub rather
    than appearing in it). RAILWAY_ADMIN is excluded because train inventory
    belongs to the authorised IRCTC account only."""
    return bool(user) and user.get("role") in PARTNER_ROLES


def is_irctc_admin(user):
    """True only for the single authorised IRCTC account.

    Train creation/management is gated on the *email*, not just the role, so a
    railway account created some other way cannot inject train inventory.
    """
    if not user:
        return False
    if user.get("role") != ROLES["RAILWAY_ADMIN"]:
        return False
    return (user.get("email") or "").strip().lower() == IRCTC_ADMIN_EMAIL


def resource_status(owner_id):
    """Initial status for a newly-registered resource (transport/hotel/spot/tour).

    Spec: provider-created resources are PENDING until the Admin approves them;
    anything created by an ADMIN account is auto-approved.
    """
    if isinstance(owner_id, dict):
        return "APPROVED" if owner_id.get("role") == ROLES["ADMIN"] else "PENDING"
    u = get_collection("users").find_one({"_id": owner_id}, {"role": 1})
    return "APPROVED" if u and u.get("role") == ROLES["ADMIN"] else "PENDING"


def require_admin(f):
    return require_roles(ROLES["ADMIN"])(f)


def require_approved_provider(f):
    """Provider content guard: the account must be a provider the Main Admin has
    explicitly APPROVED. Prevents publishing before approval from reaching
    services regardless of which route is called.

    The authorised IRCTC account is the single exception and is admitted only
    when its email matches IRCTC_ADMIN_EMAIL."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user(allow_demo=False)
        if not user:
            return jsonify({"error": "Authentication required. Please log in."}), 401
        if user["role"] not in PROVIDER_ROLES and not is_irctc_admin(user):
            return jsonify({"error": "Only approved partners can access this resource."}), 403
        if user.get("status") != "ACTIVE" or user.get("approvalStatus") == "SUSPENDED":
            return jsonify({"error": "Your account has been suspended. Please contact the platform administrator."}), 403
        if is_irctc_admin(user):
            request.current_user = user
            return f(*args, **kwargs)
        approval = user.get("approvalStatus")
        if approval != "APPROVED":
            if approval == "PENDING":
                return jsonify({"error": "Your partner account is pending Main Admin approval."}), 403
            if approval == "REJECTED":
                return jsonify({"error": "Your partner account was rejected by the Main Admin."}), 403
            if approval == "SUSPENDED":
                return jsonify({"error": "Your partner account is suspended by the Main Admin."}), 403
            return jsonify({"error": "Your partner account is not approved."}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper


def provider_is_approved(user):
    """Backend-side check used by service layers (defense in depth)."""
    if not user:
        return False
    if is_irctc_admin(user):
        return True
    if user.get("role") not in PROVIDER_ROLES:
        return True
    return user.get("approvalStatus") == "APPROVED"