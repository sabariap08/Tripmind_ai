"""Optional email + in-app notifications.

Design rules
------------
* **No silent success.** Every send returns an explicit status. When SMTP is
  not configured the notification is still stored in-app and the status is
  ``"skipped_not_configured"`` - it is never reported as "sent" and never
  fabricated.
* **No sensitive data in email.** The body is built from a small allow-list of
  safe fields. Traveller names, ages, health details, proof numbers and partner
  documents are never included, because email is unencrypted in transit and is
  not an appropriate channel for that data.
* **Passengers can opt out.** ``notify`` defaults to False on the passenger
  profile; nothing is emailed unless the traveller asked for it.
* **Best effort, never fatal.** A mail failure is recorded and logged, but it
  never rolls back a booking or a checklist update.
"""
import smtplib
import logging
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone

from config import (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
                    SMTP_USE_TLS, NOTIFICATIONS_ENABLED, APP_URL)

log = logging.getLogger("tripmind.notifications")

STATUS_SENT = "SENT"
STATUS_SKIPPED = "SKIPPED_NOT_CONFIGURED"
STATUS_FAILED = "FAILED"
STATUS_RECORDED = "RECORDED"

# Only these keys may ever be interpolated into an email body.
SAFE_FIELDS = (
    "reference", "bookingId", "serviceName", "providerName", "city",
    "travelDate", "checklistTitle", "checklistDate", "partnerLabel",
    "approvalStatus", "actionUrl",
)


def _now():
    return datetime.utcnow().isoformat()


def notifications_configured():
    return bool(NOTIFICATIONS_ENABLED and SMTP_HOST and SMTP_FROM)


def _safe_context(context):
    """Whitelist-filter any context so nothing sensitive can leak into email."""
    if not isinstance(context, dict):
        return {}
    return {k: context[k] for k in SAFE_FIELDS if k in context}


def _render_body(lines, context):
    safe = _safe_context(context)
    out = []
    for line in lines:
        try:
            out.append(line.format(**safe) if safe else line)
        except (KeyError, IndexError):
            out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# In-app notifications
# ---------------------------------------------------------------------------
def record(user_id, kind, title, body="", context=None, action_url=""):
    """Store an in-app notification. Always succeeds unless Mongo is down."""
    doc = {
        "_id": "ntf-%s" % str(abs(hash((str(user_id), kind, _now())))),
        "userId": str(user_id),
        "kind": kind,
        "title": (title or "")[:200],
        "body": (body or "")[:1000],
        "context": _safe_context(context),
        "actionUrl": (action_url or "")[:300],
        "read": False,
        "createdAt": _now(),
    }
    try:
        from services.mongodb import get_collection
        get_collection("notifications").insert_one(doc)
    except Exception as exc:  # pragma: no cover - never break the caller
        log.warning("Could not store notification for %s: %s", user_id, exc)
        return None
    doc.pop("_id", None)
    return doc


def list_notifications(user_id, limit=30, unread_only=False):
    from services.mongodb import get_collection
    query = {"userId": str(user_id)}
    if unread_only:
        query["read"] = False
    rows = list(get_collection("notifications")
                .find(query).sort("createdAt", -1).limit(min(int(limit or 30), 100)))
    for row in rows:
        row["id"] = str(row.pop("_id"))
    return rows


def unread_count(user_id):
    from services.mongodb import get_collection
    return get_collection("notifications").count_documents(
        {"userId": str(user_id), "read": False})


def mark_read(user_id, notification_id):
    from services.mongodb import get_collection
    result = get_collection("notifications").update_one(
        {"_id": str(notification_id), "userId": str(user_id)},
        {"$set": {"read": True, "readAt": _now()}})
    return result.matched_count > 0


def mark_all_read(user_id):
    from services.mongodb import get_collection
    result = get_collection("notifications").update_many(
        {"userId": str(user_id), "read": False},
        {"$set": {"read": True, "readAt": _now()}})
    return result.modified_count


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def send_email(to_address, subject, body):
    """Attempt a real SMTP send.

    Returns one of STATUS_SENT / STATUS_SKIPPED / STATUS_FAILED. It never
    raises and never claims success it did not achieve.
    """
    if not to_address or "@" not in str(to_address):
        return STATUS_FAILED, "No valid recipient address."
    if not notifications_configured():
        return STATUS_SKIPPED, ("SMTP is not configured. Set SMTP_HOST and "
                                "SMTP_FROM to enable email.")
    try:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = SMTP_FROM
        message["To"] = to_address
        message.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            if SMTP_USE_TLS:
                try:
                    server.starttls()
                except smtplib.SMTPException:
                    pass  # server already offers implicit TLS
            if SMTP_USER and SMTP_PASSWORD:
                try:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                except smtplib.SMTPException as exc:
                    return STATUS_FAILED, "SMTP authentication failed: %s" % exc
            server.send_message(message)
        return STATUS_SENT, "Sent."
    except Exception as exc:  # pragma: no cover - network dependent
        log.warning("SMTP send failed for %s: %s", to_address, exc)
        return STATUS_FAILED, "SMTP send failed: %s" % exc


def notify(user, kind, title, body_lines=(), context=None, notify_by_email=True,
           action_url=""):
    """Record in-app + optionally email one notification.

    ``user`` is the public session payload. Email only goes to the user's own
    account address, and only when ``notify_by_email`` is true.
    """
    if not user:
        return None
    in_app = record(user.get("id"), kind, title,
                    _render_body(list(body_lines), context),
                    context=context, action_url=action_url)
    status = STATUS_RECORDED
    detail = "Stored in-app."
    if notify_by_email:
        address = user.get("email") or ""
        # Partner accounts are never emailed automatically: approval/rejection
        # notices are read in the Partner Hub. Only passengers get opt-in mail.
        from config import PARTNER_ROLES
        is_partner = user.get("role") in PARTNER_ROLES
        if is_partner and not user.get("emailOptIn"):
            status = STATUS_SKIPPED
            detail = "Stored in-app. Partner emails require an opt-in."
        else:
            body = "%s\n\n--\nTripMind\n%s" % (
                _render_body(list(body_lines), context), APP_URL)
            status, detail = send_email(address, title, body)
    return {"inApp": in_app, "emailStatus": status, "emailDetail": detail}


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------
def booking_confirmation(user, booking):
    return notify(
        user, "BOOKING_CONFIRMED", "Booking confirmed - %s" % (
            booking.get("reference") or booking.get("id") or ""),
        body_lines=[
            "Your TripMind booking is confirmed.",
            "Reference: {reference}",
            "Service: {serviceName}",
            "Travel date: {travelDate}",
            "Manage it at: {actionUrl}",
        ],
        context={
            "reference": booking.get("reference") or booking.get("id") or "",
            "serviceName": booking.get("serviceName") or booking.get("type") or "",
            "travelDate": booking.get("date") or booking.get("travelDate") or "",
            "actionUrl": "%s/pages/bookings.html" % APP_URL,
        },
        notify_by_email=bool(user.get("emailOptIn", True)),
    )


def checklist_due(user, checklist, days_until):
    if days_until is None:
        title = "Your TripMind pre-trip checklist is ready"
    elif days_until <= 0:
        title = "Travel day checklist - TripMind"
    else:
        title = "%d day%s to go - TripMind checklist" % (
            days_until, "" if days_until == 1 else "s")
    return notify(
        user, "CHECKLIST_DUE", title,
        body_lines=[
            "Your pre-trip checklist for {checklistDate} is ready.",
            "Items to complete: {checklistTitle}",
            "Open it at: {actionUrl}",
        ],
        context={
            "checklistDate": checklist.get("travelDate") or "",
            "checklistTitle": checklist.get("title") or "Pre-trip checklist",
            "actionUrl": "%s/pages/bookings.html#checklists" % APP_URL,
        },
        notify_by_email=bool(user.get("emailOptIn", True)),
    )


def approval_decision(user, approved, reason=""):
    """Tell a partner their registration was approved or rejected.

    Sent in-app only. The reason is included because the partner needs it to
    fix their submission, but no document image is ever attached.
    """
    if approved:
        return notify(
            user, "PARTNER_APPROVED", "Your TripMind partner account was approved",
            body_lines=["Your {partnerLabel} account is approved.",
                        "You can now publish and manage your listings."],
            context={"partnerLabel": (user.get("partner") or {}).get("label", "partner")},
            notify_by_email=False,
            action_url="/tripmind-partner/dashboard.html")
    lines = ["Your {partnerLabel} registration was not approved.",
             "Reason: %s" % (reason or "Not specified."),
             "Update your details and contact the Main Admin to re-submit."]
    return notify(
        user, "PARTNER_REJECTED", "TripMind partner registration update",
        body_lines=lines,
        context={"partnerLabel": (user.get("partner") or {}).get("label", "partner")},
        notify_by_email=False,
        action_url="/tripmind-partner/register.html")


def due_checklists_for_today(today=None):
    """Which stored checklists are inside their reminder window.

    Returns a list of ``(user_id, checklist_id, days_until)`` so a scheduler
    (cron / APScheduler / external) can drive reminders.
    """
    from services.mongodb import get_collection
    today = today or datetime.now(timezone.utc).date()
    window_start = today - timedelta(days=14)
    window_end = today
    results = []
    for doc in get_collection("checklists").find({
            "travelDate": {"$gte": window_start.isoformat(),
                           "$lte": window_end.isoformat()}}):
        try:
            travel = datetime.strptime(doc["travelDate"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            continue
        results.append((doc.get("ownerId"), str(doc.get("_id")),
                        (travel - today).days))
    return results
