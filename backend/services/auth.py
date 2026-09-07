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
from config import ROLES, PROVIDER_ROLES, APPROVAL_STATUSES

SESSION_USER_KEY = "tripmind_user"


def new_user_id():
    return str(ObjectId())


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
    """Provider registration (Transport Admins, Tourist Spot Admins, Hotel
    Admins, Restaurant Admins, Guides). Account is ACTIVE but REMAINS PENDING
    until Admin reviews. The provider cannot publish anything until APPROVED.
    Role-specific registration details (company info, proof documents, images)
    are stored verbatim so the Admin can inspect everything during approval."""
    if role not in PROVIDER_ROLES:
        return None, "Invalid provider role."
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


def login_user(email, password):
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
        if approval_status == "PENDING":
            return None, "Your account is pending Admin approval."
        if approval_status == "REJECTED":
            reason = user.get("approvalReason") or "no reason provided"
            return None, "Your registration was rejected. Reason: %s" % reason
    session[SESSION_USER_KEY] = str(user["_id"])
    session.permanent = True
    session["_permanent"] = True
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
        "identityNumber": user.get("identityNumber", ""),
        "gst": user.get("gst", ""),
        "preferences": user.get("preferences", {}),
    }
    if user.get("role") == ROLES["TRANSPORT_ADMIN"]:
        pub["transportServiceId"] = str(user["_id"])
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
    """Provider content guard: the account must be a provider that Admin has
    explicitly APPROVED. Prevents publishing before approval from reaching
    services regardless of which route is called."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user(allow_demo=False)
        if not user:
            return jsonify({"error": "Authentication required. Please log in."}), 401
        if user["role"] not in PROVIDER_ROLES:
            return jsonify({"error": "Only approved providers can access this resource."}), 403
        if user.get("status") != "ACTIVE" or user.get("approvalStatus") == "SUSPENDED":
            return jsonify({"error": "Your account has been suspended. Please contact the platform administrator."}), 403
        approval = user.get("approvalStatus")
        if approval != "APPROVED":
            if approval == "PENDING":
                return jsonify({"error": "Your provider account is pending Admin approval."}), 403
            if approval == "REJECTED":
                return jsonify({"error": "Your provider account was rejected by the Admin."}), 403
            if approval == "SUSPENDED":
                return jsonify({"error": "Your provider account is suspended by the Admin."}), 403
            return jsonify({"error": "Your provider account is not approved."}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper


def provider_is_approved(user):
    """Backend-side check used by service layers (defense in depth)."""
    if not user:
        return False
    if user.get("role") not in PROVIDER_ROLES:
        return True
    return user.get("approvalStatus") == "APPROVED"