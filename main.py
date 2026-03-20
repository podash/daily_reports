"""
Daily Analytics Report - Entry Point.

Usage:
    python main.py              # report for yesterday
    python main.py 2026-02-10   # report for a specific date
    python main.py --dry-run    # print to console, don't send to Telegram
"""

import logging
import sys
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from config import LOG_DIR
from metrics import collect_daily_metrics, check_freshness
from report_builder import build_report
from telegram_sender import send_message, send_alert

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE = LOG_DIR / "daily_report.log"
SENT_LOG = LOG_DIR / "sent_dates.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("daily_report")


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def _load_sent_dates() -> set[str]:
    if SENT_LOG.exists():
        try:
            return set(json.loads(SENT_LOG.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            return set()
    return set()


def _mark_sent(target_date: date) -> None:
    sent = _load_sent_dates()
    sent.add(target_date.isoformat())
    SENT_LOG.write_text(json.dumps(sorted(sent)), encoding="utf-8")


def _already_sent(target_date: date) -> bool:
    return target_date.isoformat() in _load_sent_dates()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(target_date: date, dry_run: bool = False) -> None:
    logger.info("Starting daily report for %s (dry_run=%s)", target_date, dry_run)
    start_time = datetime.now()

    # Idempotency check
    if not dry_run and _already_sent(target_date):
        logger.info("Report for %s already sent. Skipping.", target_date)
        return

    # Freshness check
    try:
        freshness = check_freshness(target_date)
        stale_views = [v for v, info in freshness.items() if not info["fresh"]]
        if stale_views:
            msg = f"Stale aggregates for {target_date}: {', '.join(stale_views)}"
            logger.warning(msg)
            if not dry_run:
                send_alert(msg)
                # Continue anyway with available data
    except Exception as e:
        logger.error("Freshness check failed: %s", e)
        if not dry_run:
            send_alert(f"Freshness check failed: {e}")
        return

    # Collect metrics
    try:
        data = collect_daily_metrics(target_date)
    except Exception as e:
        logger.error("Failed to collect metrics: %s", e)
        if not dry_run:
            send_alert(f"Failed to collect metrics for {target_date}: {e}")
        return

    # Build report
    report_text = build_report(data)

    # Output
    if dry_run:
        print("\n" + "=" * 60)
        print(report_text)
        print("=" * 60 + "\n")
    else:
        success = send_message(report_text)
        if success:
            _mark_sent(target_date)
            logger.info("Report sent successfully.")
        else:
            logger.error("Failed to send report to Telegram.")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("Finished in %.1f seconds.", elapsed)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if args:
        try:
            target_date = date.fromisoformat(args[0])
        except ValueError:
            print(f"Invalid date format: {args[0]}. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        target_date = date.today() - timedelta(days=1)

    run(target_date, dry_run=dry_run)


if __name__ == "__main__":
    main()
