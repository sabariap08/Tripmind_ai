"""Run every scheduled TripMind job once. Intended for cron / Kubernetes CronJob.

Use this instead of the in-process thread when you would rather not have a
background thread inside the web server - for example with multiple web workers,
where every worker would otherwise run its own scheduler (harmless, because the
jobs are idempotent, but wasteful).

Both paths call the same job functions, so running this from cron while the
in-process scheduler is still enabled is safe: a reminder that one of them
already claimed is skipped by the other, thanks to the unique index on
``checklist_reminders``.

Usage::

    # once, now
    python scripts/run_scheduled_jobs.py

    # daily at 08:07 (not on the hour, to avoid every cron job on earth firing
    # at the same instant against the same database)
    7 8 * * *  cd /path/to/backend && python scripts/run_scheduled_jobs.py

Then set SCHEDULER_ENABLED=false in .env so the web process stops running its
own copy.

Exit code is 0 when every job succeeded, 1 when any job reported an error - so
cron surfaces the failure instead of silently mailing nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services import scheduler  # noqa: E402


def _has_error(result):
    """A job result is a failure if it is an error string or carries one."""
    if isinstance(result, dict):
        return bool(result.get("error")) or result.get("failed", 0) > 0
    return result is None


def main() -> int:
    report = scheduler.run_all()
    print(json.dumps(report, indent=2, default=str))

    failures = [name for name, result in report.items() if _has_error(result)]
    if failures:
        print("\nFAILED jobs: %s" % ", ".join(failures), file=sys.stderr)
        return 1
    print("\nall jobs ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
