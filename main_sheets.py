"""
Daily Analytics Report from Google Sheets - Entry Point.

Usage:
    python main_sheets.py              # report for yesterday
    python main_sheets.py 2026-02-10   # report for a specific date
    python main_sheets.py --dry-run    # print to console, don't send to Telegram
"""

import logging
import sys
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from config import LOG_DIR
from sheets_client import collect_sheets_metrics
from sheets_report_builder import build_sheets_report
from telegram_sender import send_message, send_alert

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE = LOG_DIR / "sheets_report.log"
SENT_LOG = LOG_DIR / "sheets_sent_dates.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("sheets_report")


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
    logger.info("Starting Sheets report for %s (dry_run=%s)", target_date, dry_run)
    start_time = datetime.now()

    # Idempotency check
    if not dry_run and _already_sent(target_date):
        logger.info("Sheets report for %s already sent. Skipping.", target_date)
        return

    # Collect metrics from Google Sheets
    try:
        data = collect_sheets_metrics(target_date)
    except Exception as e:
        logger.error("Failed to collect Sheets metrics: %s", e)
        if not dry_run:
            send_alert(f"Failed to collect Sheets metrics for {target_date}: {e}")
        return

    # Check if data exists for target date
    if data["data"].get("deposits", 0) == 0 and data["data"].get("registrations", 0) == 0:
        msg = f"No data in Google Sheets for {target_date}. Sheet may not be updated yet."
        logger.warning(msg)
        if not dry_run:
            send_alert(msg)
        return

    # Build report
    report_text = build_sheets_report(data)

    # Output
    if dry_run:
        print("\n" + "=" * 60)
        print(report_text)
        print("=" * 60 + "\n")
    else:
        success = send_message(report_text)
        if success:
            _mark_sent(target_date)
            logger.info("Sheets report sent successfully.")
        else:
            logger.error("Failed to send Sheets report to Telegram.")

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
