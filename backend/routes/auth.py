from flask import Blueprint, request, jsonify, session
from config import ROLES, PROVIDER_ROLES, APPROVAL_STATUSES, DEV_MODE
from services.auth import (
    register_user, register_provider, login_user, logout_user, current_user,
    require_login, require_admin, is_admin,
)
from services import duplicate
from services.mongodb import get_collection
from datetime import datetime

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    role = (data.get("role") or "").strip().upper()

    dup = duplicate.register_duplicate_check(data)
    if dup:
        return jsonify({"error": dup["message"], "field": dup["field"]}), 409

    if role == ROLES["USER"] or not role:
        user, err = register_user(data, role=ROLES["USER"])
    elif role in PROVIDER_ROLES:
        # Provider registrations start PENDING and wait for Admin approval.
        user, err = register_provider(data, role=role)
    else:
        return jsonify({"error": "Invalid role."}), 400
    if err:
        return jsonify({"error": err}), 400
    msg = ("Account created. Your provider account is pending Admin approval."
           if user["role"] in PROVIDER_ROLES else "Account created. Please log in.")
    return jsonify({"user": user, "message": msg}), 201


@auth_bp.route("/api/auth/check-availability", methods=["GET"])
def check_availability():
    """Live duplicate-data check used by registration wizards and catalog
    forms. Returns {"available": true/false} for a known field."""
    field = request.args.get("field") or ""
    value = request.args.get("value") or ""
    identity_type = request.args.get("identityType") or ""
    user = current_user(allow_demo=False)
    result = duplicate.check_available(field, value, user=user, identity_type=identity_type)
    if result is None:
        return jsonify({"error": "Unknown availability field: %s" % field}), 400
    return jsonify({"field": field, "value": value, "available": result})


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    if not data.get("email") or not data.get("password"):
        return jsonify({"error": "Email and password are required."}), 400
    user, err = login_user(data["email"], data["password"])
    if err:
        return jsonify({"error": err}), 401
    return jsonify({"user": user, "message": "Logged in."})


@auth_bp.route("/api/auth/logout", methods=["POST"])
def logout():
    logout_user()
    return jsonify({"message": "Logged out."})


@auth_bp.route("/api/auth/me", methods=["GET"])
def me():
    user = current_user(allow_demo=False)
    if not user:
        return jsonify({"user": None}), 200
    return jsonify({"user": user})


@auth_bp.route("/api/auth/registration-fields", methods=["GET"])
def registration_fields():
    """Field definitions the registration wizard must collect for a provider
    role (business identity collected once, presented read-only in the portal
    afterwards). Public — the wizard asks before an account exists."""
    from services.duplicate import role_fields, WEEK_DAYS
    role = (request.args.get("role") or "").strip().upper()
    if role not in PROVIDER_ROLES:
        return jsonify({"error": "Unknown provider role."}), 400
    fields, gst = role_fields(role)
    return jsonify({"role": role, "fields": fields, "gst": gst,
                    "weekDays": list(WEEK_DAYS)})


@auth_bp.route("/api/auth/roles", methods=["GET"])
def roles():
    import config as cfg
    return jsonify({
        "roles": list(ROLES.values()),
        "mapsEnabled": bool(cfg.GOOGLE_MAPS_API_KEY),
        # Required to render the client-side Google Maps JS API (prototype).
        "mapsKey": cfg.GOOGLE_MAPS_API_KEY,
    })


@auth_bp.route("/api/users/me", methods=["GET"])
@require_login
def my_profile():
    return jsonify({"user": request.current_user})


@auth_bp.route("/api/users/me", methods=["PATCH"])
@require_login
def update_profile():
    data = request.get_json() or {}
    upd = {}
    for field in ("name", "phone", "preferences"):
        if field in data and data[field] is not None:
            upd[field] = data[field]
    # Keep the canonical unique `mobile` in sync with the user-editable `phone`.
    if ("phone" in data and data["phone"] is not None) or ("mobile" in data and data["mobile"]):
        mobile = duplicate.normalize_mobile(data.get("phone") if data.get("phone") is not None else data.get("mobile"))
        if len(mobile) == 10:
            upd["mobile"] = mobile
    if "profile" in data and isinstance(data["profile"], dict):
        upd["profile"] = data["profile"]
    if upd:
        get_collection("users").update_one(
            {"_id": request.current_user["id"]}, {"$set": upd})
    return jsonify({"message": "Profile updated."})


@auth_bp.route("/api/admin/users", methods=["GET"])
@require_admin
def admin_list_users():
    """List accounts with optional role / approval-status / keyword filters
    (Admin only)."""
    role = (request.args.get("role") or "").strip().upper()
    approval = (request.args.get("approvalStatus") or "").strip().upper()
    status = (request.args.get("status") or "").strip().upper()
    q = (request.args.get("q") or "").strip().lower()
    explicit_approval = bool(approval and approval in APPROVAL_STATUSES)
    query = {}
    if role and role in ROLES.values():
        query["role"] = role
    if explicit_approval:
        query["approvalStatus"] = approval
    if status and status in ("ACTIVE", "INACTIVE"):
        query["status"] = status
    if q:
        query["$or"] = [{"name": {"$regex": q, "$options": "i"}},
                        {"email": {"$regex": q, "$options": "i"}}]
    users = []
    for u in get_collection("users").find(query).sort("createdAt", -1):
        derived = u.get("approvalStatus") or ("APPROVED" if u.get("approved") else "PENDING")
        if not explicit_approval and derived not in ("APPROVED", "SUSPENDED"):
            # All Users lists only accounts reviewed by the Admin — never
            # PENDING registrations or REJECTED accounts. (Server-side truth.)
            continue
        users.append({
            "id": str(u["_id"]),
            "name": u.get("name"),
            "email": u.get("email"),
            "role": u.get("role"),
            "status": u.get("status", "ACTIVE"),
            "approvalStatus": derived,
            "approvalReason": u.get("approvalReason", ""),
            "profile": u.get("profile", {}),
            "registration": u.get("registration", {}),
            "documents": u.get("documents", []),
            "images": u.get("images", []),
            "createdAt": u.get("createdAt"),
        })
    return jsonify({"users": users})


@auth_bp.route("/api/admin/users/<user_id>/approval", methods=["POST"])
@require_admin
def admin_set_approval(user_id):
    """Admin decision on an account.

    status := APPROVED | REJECTED | SUSPENDED | ACTIVE | INACTIVE
    - APPROVED / REJECTED / SUSPENDED are account approval states (any role).
      A SUSPENDED account can no longer log in or use the platform.
    - ACTIVE / INACTIVE toggle the account itself (block/unblock).
    """
    data = request.get_json() or {}
    status = (data.get("status") or "").strip().upper()
    reason = (data.get("reason") or "").strip()
    if status not in ("APPROVED", "REJECTED", "SUSPENDED", "ACTIVE", "INACTIVE"):
        return jsonify({"error": "Invalid decision status."}), 400
    try:
        uid = str(user_id)
        if not uid or len(uid) != 24 or not all(c in "0123456789abcdefABCDEF" for c in uid):
            return jsonify({"error": "Invalid user id."}), 400
    except Exception:
        return jsonify({"error": "Invalid user id."}), 400

    user = get_collection("users").find_one({"_id": uid})
    if not user:
        return jsonify({"error": "User not found."}), 404

    if user.get("role") == ROLES["ADMIN"]:
        # Never allow the Admin to suspend / reject / block a fellow admin —
        # there is no account above the Admin to restore it.
        if status in ("APPROVED", "REJECTED", "SUSPENDED", "INACTIVE"):
            return jsonify({"error": "Administrator accounts cannot be suspended, rejected or blocked."}), 400

    upd = {}
    reviewer = request.current_user.get("name") or request.current_user.get("email")
    now = datetime.utcnow().isoformat()
    if status == "APPROVED":
        upd.update({"approved": True, "approvalStatus": "APPROVED", "approvalReason": "",
                    "approvedAt": now, "approvedBy": reviewer})
    elif status == "REJECTED":
        if not reason:
            return jsonify({"error": "A rejection reason is required."}), 400
        upd.update({"approved": False, "approvalStatus": "REJECTED", "approvalReason": reason,
                    "rejectedAt": now, "rejectedBy": reviewer})
    elif status == "SUSPENDED":
        upd.update({"approved": False, "approvalStatus": "SUSPENDED",
                    "approvalReason": reason or "Suspended by Admin.",
                    "suspendedAt": now, "suspendedBy": reviewer})
    if status == "ACTIVE":
        upd["status"] = "ACTIVE"
    elif status == "INACTIVE":
        upd["status"] = "INACTIVE"
        upd["approvalReason"] = reason or upd.get("approvalReason", "Blocked by Admin.")

    if upd:
        get_collection("users").update_one({"_id": uid}, {"$set": upd})
        updated = get_collection("users").find_one({"_id": uid})
    else:
        updated = user
    pub = {
        "id": str(updated["_id"]),
        "name": updated.get("name"),
        "email": updated.get("email"),
        "role": updated.get("role"),
        "status": updated.get("status", "ACTIVE"),
        "approvalStatus": updated.get("approvalStatus") or ("APPROVED" if updated.get("approved") else "PENDING"),
        "approvalReason": updated.get("approvalReason", ""),
    }
    return jsonify({"message": "Account updated successfully.", "user": pub})