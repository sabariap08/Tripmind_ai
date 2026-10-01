"""End-to-end checks for the checklist reminder scheduler.

What "it works" has to mean here
--------------------------------
The feature was previously unreachable, so the interesting failures are not
"does the function return a dict" but:

1. A due reminder actually produces a stored in-app notification.
2. Running the scheduler again does NOT produce a second one. The claim is
   meant to be enforced by a unique index, so this is really a check that the
   index exists, not just that the code has a read-then-write guard.
3. A missing user releases the claim instead of consuming it forever - otherwise
   the reminder is "sent" in the ledger and absent from the traveller's inbox.
4. A failed send also releases the claim, so the next run retries.
5. Checklists outside the offsets are left alone.
6. The scheduler thread actually starts, and starting twice is a no-op.

Every check restores the database in a ``finally`` block: these run against the
real Mongo, and a test that leaves a notification behind is a bug that shows up
as "why did this traveller get an extra reminder".

Run from ``backend/``::

    python scripts/test_checklist_reminders.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.mongodb import get_collection  # noqa: E402
from services import notification_service as ns  # noqa: E402

PASSED = 0
FAILED = []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        print("  ok   %s" % name)
    else:
        FAILED.append(name)
        print("  FAIL %s %s" % (name, detail))


# ---------------------------------------------------------------- fixtures
def make_user(uid, email_opt_in=False):
    """Create a throwaway user. emailOptIn off so no SMTP is attempted."""
    get_collection("users").insert_one({
        "_id": uid,
        "name": "Reminder Test",
        "email": "%s@example.invalid" % uid,
        "mobile": "",
        "role": "USER",
        "approved": True,
        "status": "ACTIVE",
        "emailOptIn": email_opt_in,
        "createdAt": "2026-01-01T00:00:00.000000",
    })


def make_checklist(cid, owner, days_from_today):
    travel = (date.today() + timedelta(days=days_from_today)).isoformat()
    get_collection("checklists").insert_one({
        "_id": cid,
        "ownerId": owner,
        "bookingId": "bk-reminder-test",
        "bookingReference": "RMT123",
        "title": "Pre-trip checklist for Testville",
        "travelDate": travel,
        "context": {"city": "Testville", "transportType": "BUS", "partySize": 2},
        "items": [{"text": "Check your documents", "category": "DOCUMENTS"}],
        "source": "TEMPLATE",
        "createdAt": "2026-01-01T00:00:00.000000",
    })
    return travel


def cleanup(uid, cid):
    """Undo everything make_user/make_checklist wrote.

    Called in a ``finally`` on every check: these run against the real database,
    and a test that leaves a notification behind shows up later as "why did this
    traveller get an extra reminder".
    """
    get_collection("notifications").delete_many({"context.checklistId": cid})
    get_collection("notifications").delete_many(
        {"kind": "CHECKLIST_DUE", "userId": uid})
    get_collection("checklist_reminders").delete_many({"checklistId": cid})
    get_collection("checklists").delete_many({"_id": cid})
    get_collection("users").delete_many({"_id": uid})


def notif_count(uid):
    return get_collection("notifications").count_documents(
        {"userId": uid, "kind": "CHECKLIST_DUE"})


# ------------------------------------------------------------------- checks
def check_index_exists():
    print("\n[index] the uniqueness guarantee is in the database")
    # Drive the real creation path rather than assuming it ran. In production
    # this is app.py's _ensure_indexes(); here it is the same function, so this
    # checks that the spec entry exists and actually builds the index - not
    # merely that some earlier process happened to leave it behind.
    from services.mongodb import ensure_unique_indexes
    errors = ensure_unique_indexes()
    check("ensure_unique_indexes() reported no errors", not errors,
          "errors=%s" % errors)

    info = get_collection("checklist_reminders").index_information()
    found = None
    for name, spec in info.items():
        keys = list(spec.get("key", []))
        if keys == [("checklistId", 1), ("daysUntil", 1)]:
            found = spec
            break
    check("composite unique index present", found is not None,
          "indexes found: %s" % sorted(info))
    if found:
        check("that index is unique", bool(found.get("unique")),
              "unique=%s" % found.get("unique"))


def check_send_and_idempotency():
    print("\n[send] a due reminder fires, and fires exactly once")
    uid, cid = "rem-test-send", "chk-rem-test-send"
    cleanup(uid, cid)
    try:
        make_user(uid)
        travel = make_checklist(cid, uid, days_from_today=3)

        due = ns.due_checklists_for_today()
        check("due_checklists_for_today finds the 3-day checklist",
              any(c == cid for _, c, _ in due),
              "due=%s" % [(u, c, d) for u, c, d in due if c == cid])

        report = ns.run_due_checklist_reminders()
        check("run reported it as sent", report["sent"] >= 1,
              "report=%s" % {k: v for k, v in report.items() if k != "details"})
        check("notification stored in-app", notif_count(uid) == 1,
              "count=%d" % notif_count(uid))

        # Second run: must be a no-op. This is the assertion that matters - a
        # scheduler that runs hourly for 14 days must not send 14 emails.
        report2 = ns.run_due_checklist_reminders()
        check("second run sends nothing", report2["sent"] == 0,
              "report2=%s" % {k: v for k, v in report2.items() if k != "details"})
        check("second run counts it as already sent",
              report2["alreadySent"] >= 1, "alreadySent=%d" % report2["alreadySent"])
        check("still exactly one notification", notif_count(uid) == 1,
              "count=%d" % notif_count(uid))

        rows = list(get_collection("checklist_reminders").find({"checklistId": cid}))
        check("ledger holds one row per (checklist, days-until)", len(rows) == 1,
              "rows=%s" % [dict(r) for r in rows])
    finally:
        cleanup(uid, cid)


def check_offsets_respected():
    print("\n[offsets] only the configured days-to-go get a reminder")
    uid, cid = "rem-test-offset", "chk-rem-test-offset"
    cleanup(uid, cid)
    try:
        make_user(uid)
        # 5 days out: inside the 14-day window, but not in REMINDER_OFFSETS.
        make_checklist(cid, uid, days_from_today=5)
        report = ns.run_due_checklist_reminders()
        check("no reminder for an off-offset day", notif_count(uid) == 0,
              "count=%d report=%s" % (notif_count(uid),
                                      {k: v for k, v in report.items()
                                       if k != "details"}))
        check("nothing claimed for an off-offset day",
              get_collection("checklist_reminders").count_documents(
                  {"checklistId": cid}) == 0)
    finally:
        cleanup(uid, cid)


def check_missing_user_releases_claim():
    print("\n[recover] a vanished account does not eat its own reminder")
    uid, cid = "rem-test-ghost", "chk-rem-test-ghost"
    cleanup(uid, cid)
    try:
        # Checklist owned by an account that does not exist.
        make_checklist(cid, uid, days_from_today=1)
        report = ns.run_due_checklist_reminders()
        check("reported as skipped-no-user", report["skippedNoUser"] == 1,
              "report=%s" % {k: v for k, v in report.items() if k != "details"})
        check("claim was released, not consumed",
              get_collection("checklist_reminders").count_documents(
                  {"checklistId": cid}) == 0)

        # The account appears afterwards. It must get the reminder.
        make_user(uid)
        report2 = ns.run_due_checklist_reminders()
        check("reminder sent once the account exists",
              notif_count(uid) == 1 and report2["sent"] == 1,
              "count=%d report=%s" % (notif_count(uid),
                                      {k: v for k, v in report2.items()
                                       if k != "details"}))
    finally:
        cleanup(uid, cid)


def check_failed_send_releases_claim():
    print("\n[recover] a failed send releases the claim for retry")
    uid, cid = "rem-test-fail", "chk-rem-test-fail"
    cleanup(uid, cid)
    original = ns.checklist_due
    calls = {"n": 0}

    def flaky(user, checklist, days_until):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"inApp": None, "emailStatus": "failed", "emailDetail": "x"}
        return original(user, checklist, days_until)

    try:
        make_user(uid)
        make_checklist(cid, uid, days_from_today=0)  # travel-day nudge
        ns.checklist_due = flaky
        report = ns.run_due_checklist_reminders()
        check("failure counted", report["failed"] == 1,
              "report=%s" % {k: v for k, v in report.items() if k != "details"})
        check("no notification written", notif_count(uid) == 0)
        check("claim released so the next run retries",
              get_collection("checklist_reminders").count_documents(
                  {"checklistId": cid}) == 0)

        report2 = ns.run_due_checklist_reminders()
        check("retry succeeds", report2["sent"] == 1 and notif_count(uid) == 1,
              "count=%d report=%s" % (notif_count(uid),
                                      {k: v for k, v in report2.items()
                                       if k != "details"}))
    finally:
        ns.checklist_due = original
        cleanup(uid, cid)


def check_scheduler_thread():
    print("\n[thread] the in-process scheduler starts, once")
    import config
    from services import scheduler

    prev_enabled = config.SCHEDULER_ENABLED
    prev_interval = config.SCHEDULER_INTERVAL_SECONDS
    prev_delay = config.SCHEDULER_INITIAL_DELAY_SECONDS
    try:
        # A long initial delay: this check is about wiring, not timing.
        config.SCHEDULER_ENABLED = True
        config.SCHEDULER_INTERVAL_SECONDS = 3600
        config.SCHEDULER_INITIAL_DELAY_SECONDS = 3600

        t1 = scheduler.start()
        check("thread started", t1 is not None and t1.is_alive())
        check("thread is a daemon", bool(t1 and t1.daemon))
        t2 = scheduler.start()
        check("second start returns the same thread, not a new one",
              t2 is t1, "%s vs %s" % (t1, t2))
        st = scheduler.status()
        check("status reports running", st["running"] is True, "status=%s" % st)
        check("status lists the checklist job",
              "checklist_reminders" in st["jobs"], "jobs=%s" % st["jobs"])

        # Disabled path must not start anything.
        scheduler._thread = None
        config.SCHEDULER_ENABLED = False
        t3 = scheduler.start()
        check("SCHEDULER_ENABLED=false starts nothing", t3 is None)
        check("status reports disabled",
              scheduler.status()["enabled"] is False)
    finally:
        config.SCHEDULER_ENABLED = prev_enabled
        config.SCHEDULER_INTERVAL_SECONDS = prev_interval
        config.SCHEDULER_INITIAL_DELAY_SECONDS = prev_delay
        scheduler._thread = None


def main() -> int:
    print("Checklist reminder scheduler - end-to-end checks")
    try:
        check_index_exists()
        check_send_and_idempotency()
        check_offsets_respected()
        check_missing_user_releases_claim()
        check_failed_send_releases_claim()
        check_scheduler_thread()
    finally:
        print("\n%d checks passed, %d failed" % (PASSED, len(FAILED)))
        if FAILED:
            for name in FAILED:
                print("  failed: %s" % name)
            return 1
    print("Reminder scheduler is behaving.")
    return 0


if __name__ == "__main__":
    import traceback
    try:
        _rc = main()
    except BaseException:  # noqa: BLE001 - a silent traceback here is worse
        traceback.print_exc()
        _rc = 2
    sys.stdout.flush()
    sys.stderr.flush()
    sys.exit(_rc)
