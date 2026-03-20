"""
Daily Analytics Report via Email - Entry Point.

Fetches data from Google Sheets, builds an HTML email report,
and sends it to configured recipients.

Usage:
    python main_email.py                # report for yesterday
    python main_email.py 2026-02-10     # report for a specific date
    python main_email.py --dry-run      # save HTML to file, don't send email
    python main_email.py --preview      # save HTML and open in browser
"""

import logging
import sys
import json
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path

from config import LOG_DIR
from sheets_client import collect_sheets_metrics
from email_report_builder import build_email_report, build_email_subject
from email_sender import send_email
from telegram_sender import send_alert

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE = LOG_DIR / "email_report.log"
SENT_LOG = LOG_DIR / "email_sent_dates.json"
PREVIEW_DIR = LOG_DIR / "previews"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("email_report")


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
# Preview
# ---------------------------------------------------------------------------

def _save_preview(html: str, target_date: date) -> Path:
    """Save HTML to a file for preview."""
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    filepath = PREVIEW_DIR / f"report_{target_date.isoformat()}.html"
    filepath.write_text(html, encoding="utf-8")
    logger.info("Preview saved to %s", filepath)
    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(target_date: date, dry_run: bool = False, preview: bool = False) -> None:
    logger.info("Starting email report for %s (dry_run=%s, preview=%s)", target_date, dry_run, preview)
    start_time = datetime.now()

    # Idempotency check
    if not dry_run and not preview and _already_sent(target_date):
        logger.info("Email report for %s already sent. Skipping.", target_date)
        return

    # Collect metrics from Google Sheets
    try:
        data = collect_sheets_metrics(target_date)
    except Exception as e:
        logger.error("Failed to collect Sheets metrics: %s", e)
        if not dry_run:
            send_alert(f"Failed to collect Sheets metrics for email report {target_date}: {e}")
        return

    # Check if data exists for target date
    if data["data"].get("deposits", 0) == 0 and data["data"].get("registrations", 0) == 0:
        msg = f"No data in Google Sheets for {target_date}. Sheet may not be updated yet."
        logger.warning(msg)
        if not dry_run:
            send_alert(msg)
        return

    # Build HTML report
    html_report = build_email_report(data)
    subject = build_email_subject(data)

    # Output
    if dry_run or preview:
        filepath = _save_preview(html_report, target_date)
        print(f"\nSubject: {subject}")
        print(f"HTML saved to: {filepath}\n")
        if preview:
            webbrowser.open(filepath.as_uri())
    else:
        success = send_email(subject, html_report)
        if success:
            _mark_sent(target_date)
            logger.info("Email report sent successfully.")
        else:
            logger.error("Failed to send email report.")
            send_alert(f"Failed to send email daily report for {target_date}")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("Finished in %.1f seconds.", elapsed)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    dry_run = "--dry-run" in sys.argv
    preview = "--preview" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if args:
        try:
            target_date = date.fromisoformat(args[0])
        except ValueError:
            print(f"Invalid date format: {args[0]}. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        target_date = date.today() - timedelta(days=1)

    run(target_date, dry_run=dry_run, preview=preview)


if __name__ == "__main__":
    main()
