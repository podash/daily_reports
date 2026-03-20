"""
Risk Daily Report via Email - Entry Point.

Fetches Top 5 Players from PostgreSQL and sends a daily risk email.

Usage:
    python main_risk_email.py                # report for yesterday
    python main_risk_email.py 2026-03-15     # report for a specific date
    python main_risk_email.py --dry-run      # save HTML, don't send
    python main_risk_email.py --preview      # save HTML and open in browser
    python main_risk_email.py --tg-only      # send only to Telegram, skip email
"""

import json
import logging
import sys
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path

from config import LOG_DIR
from top_players import fetch_top_players_profit
from risk_email_builder import build_risk_report, build_risk_subject
from email_sender import send_email
from telegram_sender import send_alert, send_risk_report

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

import os
_raw = os.getenv("RISK_EMAIL_RECIPIENTS", "")
RISK_RECIPIENTS: list[str] = (
    [r.strip() for r in _raw.split(",") if r.strip()]
    if _raw.strip()
    else []
)

LOG_FILE   = LOG_DIR / "risk_email.log"
SENT_LOG   = LOG_DIR / "risk_email_sent_dates.json"
PREVIEW_DIR = LOG_DIR / "previews"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("risk_email")


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def _load_sent() -> set[str]:
    if SENT_LOG.exists():
        try:
            return set(json.loads(SENT_LOG.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            return set()
    return set()


def _mark_sent(target_date: date) -> None:
    sent = _load_sent()
    sent.add(target_date.isoformat())
    SENT_LOG.write_text(json.dumps(sorted(sent)), encoding="utf-8")


def _already_sent(target_date: date) -> bool:
    return target_date.isoformat() in _load_sent()


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def _save_preview(html: str, target_date: date) -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    filepath = PREVIEW_DIR / f"risk_{target_date.isoformat()}.html"
    filepath.write_text(html, encoding="utf-8")
    logger.info("Preview saved to %s", filepath)
    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(target_date: date, dry_run: bool = False, preview: bool = False, tg_only: bool = False) -> None:
    logger.info(
        "Starting risk report for %s (dry_run=%s, preview=%s, tg_only=%s)",
        target_date, dry_run, preview, tg_only,
    )
    start_time = datetime.now()

    if not dry_run and not preview and _already_sent(target_date):
        logger.info("Risk report for %s already sent. Skipping.", target_date)
        return

    try:
        top_players = fetch_top_players_profit(target_date)
    except Exception as e:
        logger.error("Failed to fetch top players: %s", e)
        if not dry_run:
            send_alert(f"Risk report FAILED for {target_date}: {e}")
        return

    html_report = build_risk_report(top_players, target_date)
    subject     = build_risk_subject(target_date)

    if dry_run or preview:
        filepath = _save_preview(html_report, target_date)
        print(f"\nSubject: {subject}")
        print(f"HTML saved to: {filepath}\n")
        if preview:
            webbrowser.open(filepath.as_uri())
        # Telegram preview: print formatted text without actually sending
        logger.info("Telegram send skipped in dry-run/preview mode.")
    else:
        email_ok = False
        if not tg_only:
            recipients = RISK_RECIPIENTS or None
            email_ok = send_email(subject, html_report, recipients=recipients)

        tg_ok = send_risk_report(top_players, target_date)

        if email_ok or tg_ok:
            _mark_sent(target_date)
            logger.info(
                "Risk report delivered (email=%s, telegram=%s).", email_ok, tg_ok
            )
        else:
            logger.error("Failed to deliver risk report via any channel.")
            send_alert(f"Risk report SEND FAILED for {target_date}")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("Finished in %.1f seconds.", elapsed)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    dry_run = "--dry-run" in sys.argv
    preview = "--preview" in sys.argv
    tg_only = "--tg-only" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if args:
        try:
            target_date = date.fromisoformat(args[0])
        except ValueError:
            print(f"Invalid date: {args[0]}. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        target_date = date.today() - timedelta(days=1)

    run(target_date, dry_run=dry_run, preview=preview, tg_only=tg_only)


if __name__ == "__main__":
    main()
