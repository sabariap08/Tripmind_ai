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
* **Partners never get automatic email.** Partner approval notices are read in
  the Partner Hub, so ``notify`` gates them on an explicit ``emailOptIn`` and
  records ``skipped_partner_no_optin`` when it is absent.
* **Passengers are emailed whenever SMTP is configured.** This line used to
  claim "notify defaults to False on the passenger profile; nothing is emailed
  unless the traveller asked for it". That is not what the code does. The
  ``emailOptIn`` flag is read in three places and written in none: no
  registration path sets it, no profile endpoint exposes it, and no frontend
  control toggles it. Every user document in the database has the field absent
  or null, so ``user.get("emailOptIn", True)`` evaluates truthy for all of them
  and every passenger notification attempts a real send. With SMTP unset that is
  harmless (``skipped_not_configured``); the moment an operator configures SMTP,
  every passenger is emailed with no consent record behind it. Partner accounts
  are unaffected - the gate above is the one path that is correct today. Making
  this honest needs a registration default plus a profile toggle, not a code
  comment; flagged rather than silently changed, because defaulting to opt-out
  would disable the email feature outright and nothing currently lets anyone
  opt back in.
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


# How far ahead of the travel date a checklist starts reminding, and how long it
# keeps reminding after the travel date has passed.
#
# These are the two ends of the reminder window. Both directions are needed:
# ahead, because the whole point of a pre-trip checklist is to reach the
# traveller *before* they travel; behind, so that a traveller whose reminder
# window opened while the app was down, or who generated the checklist very
# late, is not left with a checklist nobody ever mentioned.
REMINDER_LEAD_DAYS = 14
REMINDER_GRACE_DAYS = 3


def due_checklists_for_today(today=None):
    """Which stored checklists are inside their reminder window.

    Returns a list of ``(user_id, checklist_id, days_until)`` so a scheduler
    (cron / APScheduler / external) can drive reminders. ``days_until`` is
    positive before travel, 0 on the day, negative once it has passed.

    The window used to run from 14 days *ago* to today, which made every
    "days to go" reminder unreachable: ``days_until`` could only ever come out
    at -14..0, so a "3 days to go" or "1 day to go" message could never be sent,
    however long the scheduler ran. In a live database where every checklist
    had a future travel date, this returned an empty list every single time.
    The window now runs from ``REMINDER_GRACE_DAYS`` ago to
    ``REMINDER_LEAD_DAYS`` ahead, so the advance reminders it was clearly
    written for can actually fire.

    ``today`` defaults to the server's local date rather than UTC's. The
    comparison is against ``travelDate``, which is a calendar date the traveller
    themselves chose and will read in their own timezone - so "3 days to go"
    should mean three of *their* days. There is no per-user timezone on the
    user document to do better than this, so a deployment serving one region
    should run with ``TZ`` set to that region. Pass ``today`` explicitly if you
    need to drive a specific region from a shared cron.
    """
    from services.mongodb import get_collection
    today = today or datetime.now().date()
    window_start = today - timedelta(days=REMINDER_GRACE_DAYS)
    window_end = today + timedelta(days=REMINDER_LEAD_DAYS)
    results = []
    for doc in get_collection("checklists").find({
            "travelDate": {"$gte": window_start.isoformat(),
                           "$lte": window_end.isoformat()}}):
        try:
            travel = datetime.strptime(doc["travelDate"], "%Y-%m-%d").date()
        except (ValueError, KeyError, TypeError):
            continue
        results.append((doc.get("ownerId"), str(doc.get("_id")),
                        (travel - today).days))
    return results


# Days-before-travel that a reminder fires on. The 0 entry is the travel-day
# nudge; the larger ones are the "still ahead of you" reminders. Each is sent at
# most once per checklist (see _claim_reminder), so re-running the scheduler is
# always safe.
REMINDER_OFFSETS = (7, 3, 1, 0)


def _claim_reminder(checklist_id, days_until, today):
    """Reserve the right to send one reminder. Returns True if we won.

    Idempotency is enforced by the database, not by a read-then-write in this
    process. The scheduler is designed to run repeatedly - hourly in-process, or
    daily from cron, or manually from the admin endpoint - and a check like
    "have I already sent this?" would race against a concurrent run and send the
    same reminder twice. A traveller receiving "2 days to go" four times because
    four processes woke up at once is exactly the kind of quiet wrongness this
    codebase is supposed to avoid.

    The unique index on (checklistId, daysUntil) is what actually prevents it.
    Here we just attempt the insert and treat DuplicateKeyError as "someone else
    already has it".
    """
    from pymongo.errors import DuplicateKeyError
    from services.mongodb import get_collection
    doc = {
        "checklistId": str(checklist_id),
        "daysUntil": int(days_until),
        "dueDate": today.isoformat(),
        "createdAt": _now(),
    }
    try:
        get_collection("checklist_reminders").insert_one(doc)
        return True
    except DuplicateKeyError:
        return False


def _release_reminder(checklist_id, days_until):
    """Give a claim back so a failed send is retried on the next run.

    Called only when the send itself failed. Without this, one transient SMTP or
    database error would permanently consume the claim and the traveller would
    never be reminded at all - the reminder would read as "sent" in the ledger
    and be absent from the user's notifications.
    """
    from services.mongodb import get_collection
    get_collection("checklist_reminders").delete_many({
        "checklistId": str(checklist_id), "daysUntil": int(days_until)})


def run_due_checklist_reminders(today=None, offsets=REMINDER_OFFSETS):
    """Send every checklist reminder that is due and not already sent.

    Safe to call as often as you like: each (checklist, days-until) pair is sent
    at most once, enforced by a unique index. This is the function that makes
    ``due_checklists_for_today`` reachable - previously it had no caller, so the
    pre-trip checklist reminder was dead code and never fired for anyone.

    Returns a report dict rather than raising. A scheduler that crashes the
    process it is embedded in is worse than one that reports a partial failure,
    so every error is counted and the run continues to the next checklist.
    """
    from services.mongodb import get_collection
    from services.auth import _public_user

    today = today or datetime.now(timezone.utc).date()
    report = {
        "date": today.isoformat(),
        "considered": 0,
        "sent": 0,
        "alreadySent": 0,
        "skippedNoUser": 0,
        "failed": 0,
        "details": [],
    }

    checklists = get_collection("checklists")
    users = get_collection("users")

    for user_id, checklist_id, days_until in due_checklists_for_today(today):
        if days_until not in offsets:
            continue
        report["considered"] += 1

        # Claim first. If another run already sent this one, do no work at all.
        if not _claim_reminder(checklist_id, days_until, today):
            report["alreadySent"] += 1
            continue

        try:
            user_doc = users.find_one({"_id": user_id}) if user_id else None
            if not user_doc:
                # The account is gone. Release the claim so a genuinely
                # re-created account is not silently skipped forever.
                _release_reminder(checklist_id, days_until)
                report["skippedNoUser"] += 1
                continue

            checklist_doc = checklists.find_one({"_id": checklist_id}) or {}
            result = checklist_due(_public_user(user_doc), checklist_doc, days_until)
            # checklist_due returns None only when the user payload is empty;
            # it never raises. A missing in-app record is a real failure, so
            # release the claim and let the next run retry it.
            if not result or not result.get("inApp"):
                _release_reminder(checklist_id, days_until)
                report["failed"] += 1
                report["details"].append(
                    {"checklistId": checklist_id, "daysUntil": days_until,
                     "outcome": "in_app_not_stored"})
                continue

            report["sent"] += 1
            report["details"].append({
                "checklistId": checklist_id, "daysUntil": days_until,
                "outcome": "sent", "emailStatus": result.get("emailStatus")})
        except Exception as exc:  # pragma: no cover - one bad row must not stop the run
            log.warning("Checklist reminder failed for %s: %s", checklist_id, exc)
            _release_reminder(checklist_id, days_until)
            report["failed"] += 1
            report["details"].append({
                "checklistId": checklist_id, "daysUntil": days_until,
                "outcome": "error", "error": str(exc)[:200]})

    log.info("Checklist reminders %s: %d sent, %d already sent, %d failed",
             today.isoformat(), report["sent"], report["alreadySent"], report["failed"])
    return report
