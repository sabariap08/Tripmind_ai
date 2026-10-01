"""In-process scheduler for TripMind's periodic work.

Why this exists
---------------
``services.notification_service.due_checklists_for_today`` computed which
pre-trip checklists were inside their reminder window, and
``checklist_due`` knew how to send one. Nothing called either. The feature was
written, tested by hand, and then never reached in production: a traveller
generated a checklist and was never reminded about it, with no error anywhere
because no code path ran.

A single daemon thread closes that gap. It is deliberately the smallest thing
that works:

* **One thread, one loop.** Not a job framework. There is one job today.
* **Idempotent jobs, not a singleton scheduler.** Correctness comes from each
  job being safe to run twice (see ``notification_service._claim_reminder``,
  which claims via a unique index). A singleton guard would only hide the
  problem behind a lock, and would still break the moment someone ran
  ``scripts/run_scheduled_jobs.py`` from cron alongside the web process.
* **A failing job never kills the thread.** Every job runs inside try/except
  and its exception is logged. A scheduler that exits on the first transient
  MongoDB blip stops reminding people for the lifetime of the process, which is
  strictly worse than one missed reminder.
* **Daemon thread.** It does not keep the interpreter alive, so it does not
  interfere with a clean shutdown or with a test that imports the app.

Running it from cron instead
----------------------------
Set ``SCHEDULER_ENABLED=false`` and call ``scripts/run_scheduled_jobs.py`` on a
schedule. Same job functions, same idempotency, so the two can even overlap
during a migration without double-sending.
"""

from __future__ import annotations

import logging
import threading

import config

log = logging.getLogger("tripmind.scheduler")

# Guards against a second thread being started in the same process. This is
# only a convenience for double-import (e.g. app.py imported as both "__main__"
# and "app") -- it is NOT the correctness mechanism. Cross-process safety lives
# in the database.
_thread = None
_lock = threading.Lock()


def checklist_reminder_job():
    """Send due pre-trip checklist reminders. Idempotent."""
    from services import notification_service
    return notification_service.run_due_checklist_reminders()


def _training_sample_count():
    """Total recorded training samples across the three sample kinds.

    Counted rather than summed from model state because the model docs are
    *outputs* of training: using them to decide whether to train again would let
    a previous retrain satisfy its own trigger.
    """
    from services.mongodb import get_collection
    total = 0
    for kind in ("cost", "duration", "delay"):
        try:
            total += get_collection("ml_training_samples").count_documents(
                {"type": kind})
        except Exception:  # pragma: no cover - a missing collection is zero
            continue
    return total


def ml_retrain_job():
    """Retrain the ML models if enough new samples have accumulated.

    Returns a dict describing the decision, so the admin scheduler status
    endpoint can show *why* it did or did not retrain rather than just whether
    it did. Skipped states report the reason; they are not errors.
    """
    if not config.ML_AUTOTRAIN_ENABLED:
        return {"skipped": "disabled"}

    from services.ml import registry
    from services.ml.train import train_all

    samples = _training_sample_count()
    if samples < config.ML_AUTOTRAIN_MIN_SAMPLES:
        return {"skipped": "too_few_samples", "samples": samples,
                "required": config.ML_AUTOTRAIN_MIN_SAMPLES}

    last = registry.last_trained_at()
    if last:
        from datetime import datetime

        try:
            elapsed = (datetime.utcnow() - datetime.fromisoformat(last)
                       ).total_seconds()
        except (TypeError, ValueError):
            elapsed = None
        if elapsed is not None and elapsed < config.ML_AUTOTRAIN_MIN_INTERVAL_SECONDS:
            return {"skipped": "too_soon", "samples": samples,
                    "secondsSinceLast": int(elapsed)}

    summary = train_all()
    registry.mark_trained(summary.get("trainedAt"))
    return {"retrained": True, "samples": samples,
            "trainedAt": summary.get("trainedAt")}


# Every job the scheduler owns. Kept as data so ``run_all`` is the single place
# that knows the list, and so adding a job cannot mean forgetting to register it
# in the loop as well.
JOBS = (
    ("checklist_reminders", checklist_reminder_job),
    ("ml_retrain", ml_retrain_job),
)


def run_all():
    """Run every job once. Never raises.

    Returns ``{job_name: result_or_error}``. An error is captured as a string
    rather than propagated so one broken job cannot stop the others, and so the
    caller can see which one failed.
    """
    results = {}
    for name, job in JOBS:
        try:
            results[name] = job()
        except Exception as exc:  # pragma: no cover - defensive by design
            log.exception("Scheduled job %s failed", name)
            results[name] = {"error": str(exc)[:300]}
    return results


def _loop(interval_seconds, initial_delay_seconds):  # pragma: no cover - timing
    if initial_delay_seconds > 0:
        log.info("Scheduler waiting %ss before its first run.",
                 initial_delay_seconds)
        # A plain sleep in daemon-thread shape: interrupted by nothing, but
        # bounded so a misconfigured delay cannot hang start-up forever.
        import time
        time.sleep(initial_delay_seconds)

    while True:
        try:
            report = run_all()
            for name, result in report.items():
                if isinstance(result, dict) and result.get("error"):
                    log.warning("Job %s errored: %s", name, result["error"])
        except Exception as exc:
            # Belt and braces. run_all already swallows per-job errors; this
            # catches a failure in the loop body itself, so the thread cannot
            # die on an unexpected shape.
            log.exception("Scheduler tick failed: %s", exc)

        import time
        try:
            time.sleep(interval_seconds)
        except (KeyboardInterrupt, SystemExit):
            # Not expected in a daemon thread, but if the process is tearing
            # down we should stop tidily rather than log a traceback.
            log.info("Scheduler stopping.")
            return


def start(force=False):
    """Start the scheduler thread if enabled. Returns the thread, or None.

    Safe to call more than once: the second call is a no-op and returns the
    already-running thread.
    """
    global _thread

    if not force and not config.SCHEDULER_ENABLED:
        log.info("Scheduler disabled (SCHEDULER_ENABLED=false). "
                 "Run scripts/run_scheduled_jobs.py from cron instead.")
        return None

    with _lock:
        if _thread is not None and _thread.is_alive():
            return _thread

        interval = max(1, int(config.SCHEDULER_INTERVAL_SECONDS or 3600))
        delay = max(0, int(config.SCHEDULER_INITIAL_DELAY_SECONDS or 0))

        thread = threading.Thread(
            target=_loop,
            args=(interval, delay),
            name="tripmind-scheduler",
            daemon=True,  # never hold the process open
        )
        thread.start()
        _thread = thread
        log.info("Scheduler started: every %ss, first run in %ss.",
                 interval, delay)
        return thread


def stop(timeout=5.0):  # pragma: no cover - test/ shutdown helper
    """Best-effort stop. The thread is a daemon, so this is for cleanliness."""
    global _thread
    with _lock:
        thread = _thread
        _thread = None
    if thread is None or not thread.is_alive():
        return False
    # There is no wakeup primitive for time.sleep, so the thread ends with the
    # process. Report honestly rather than pretending the join succeeded.
    thread.join(timeout=timeout)
    return not thread.is_alive()


def status():
    """Introspection for the admin endpoint."""
    thread = _thread
    return {
        "enabled": bool(config.SCHEDULER_ENABLED),
        "running": bool(thread is not None and thread.is_alive()),
        "intervalSeconds": config.SCHEDULER_INTERVAL_SECONDS,
        "initialDelaySeconds": config.SCHEDULER_INITIAL_DELAY_SECONDS,
        "jobs": [name for name, _ in JOBS],
        "mlAutotrain": {
            "enabled": bool(config.ML_AUTOTRAIN_ENABLED),
            "minSamples": config.ML_AUTOTRAIN_MIN_SAMPLES,
            "minIntervalSeconds": config.ML_AUTOTRAIN_MIN_INTERVAL_SECONDS,
        },
    }
