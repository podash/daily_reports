"""
Affiliate GEO Weekly Report via Email - Entry Point.

Reads data from PostgreSQL, builds a 9-block HTML report for affiliate managers,
and sends it to configured recipients. Intended to run every Monday.

Usage:
    python main_affiliate_weekly.py                          # all managers combined
    python main_affiliate_weekly.py --manager "affiliate 1"  # per-manager report
    python main_affiliate_weekly.py 2026-03-10               # specific date
    python main_affiliate_weekly.py --dry-run                # save HTML, don't send
    python main_affiliate_weekly.py --preview                # save HTML, open browser

--manager accepts the key from manager_names.json (case-insensitive).
Examples: "affiliate 1", "mediabuy", "affiliate tl 3"
"""

import json
import logging
import os
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

from config import LOG_DIR, EMAIL_RECIPIENTS
from affiliate_weekly_metrics import collect_weekly_metrics
from affiliate_weekly_builder import build_weekly_report, build_weekly_subject
from email_sender import send_email
from telegram_sender import send_alert

# ---------------------------------------------------------------------------
# Focus GEO: comma-separated country names in .env
# Defaults to top affiliate markets if not set
# ---------------------------------------------------------------------------

_DEFAULT_FOCUS_GEO = (
    "Turkey,Portugal,Latvia,Uzbekistan,Spain,Germany,Poland,"
    "Austria,Belgium,Brazil,Egypt,Tunisia,Morocco,Azerbaijan,"
    "Slovenia,Switzerland,Canada"
)
_raw_geo = os.getenv("AFFILIATE_FOCUS_GEO", _DEFAULT_FOCUS_GEO)
FOCUS_GEO: list[str] = [c.strip() for c in _raw_geo.split(",") if c.strip()]

# Affiliate report recipients (separate from daily report)
_raw_rec = os.getenv("AFFILIATE_EMAIL_RECIPIENTS", "")
AFFILIATE_RECIPIENTS: list[str] = (
    [r.strip() for r in _raw_rec.split(",") if r.strip()]
    if _raw_rec.strip()
    else EMAIL_RECIPIENTS
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE = LOG_DIR / "affiliate_weekly_report.log"
SENT_LOG = LOG_DIR / "affiliate_weekly_sent_dates.json"
PREVIEW_DIR = LOG_DIR / "previews"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("affiliate_weekly")


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



# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def _save_preview(html: str, report_date: date, manager_slug: str = "") -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    slug = f"_{manager_slug}" if manager_slug else ""
    filepath = PREVIEW_DIR / f"affiliate_weekly{slug}_{report_date.isoformat()}.html"
    filepath.write_text(html, encoding="utf-8")
    logger.info("Preview saved: %s", filepath)
    return filepath


def _manager_slug(manager_group: str | None) -> str:
    """Convert manager group key to a safe filename component."""
    if not manager_group:
        return ""
    return manager_group.lower().strip().replace(" ", "_")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    report_date: date,
    dry_run: bool = False,
    preview: bool = False,
    manager_group: str | None = None,
) -> None:
    slug = _manager_slug(manager_group)
    logger.info(
        "Starting affiliate weekly report | date=%s | geo_count=%d"
        " | manager=%s | dry_run=%s | preview=%s",
        report_date, len(FOCUS_GEO), manager_group or "ALL", dry_run, preview,
    )
    start_time = datetime.now()

    sent_key = f"{report_date.isoformat()}:{slug or 'all'}"
    if not dry_run and not preview and sent_key in _load_sent():
        logger.info("Weekly report for %s / manager=%s already sent. Skipping.", report_date, slug or "ALL")
        return

    try:
        data = collect_weekly_metrics(report_date, FOCUS_GEO, manager_group=manager_group)
    except Exception as e:
        logger.error("Failed to collect affiliate weekly metrics: %s", e)
        if not dry_run:
            send_alert(f"Affiliate weekly report FAILED for {report_date} manager={manager_group}: {e}")
        return

    if not data.get("block1") and not data.get("block8"):
        msg = (
            f"No affiliate data for week ending {data['periods']['period_end']}"
            f" (manager={manager_group or 'ALL'})."
        )
        logger.warning(msg)
        if not dry_run:
            send_alert(msg)
        return

    html_report = build_weekly_report(data)
    subject = build_weekly_subject(data)

    if dry_run or preview:
        filepath = _save_preview(html_report, report_date, slug)
        print(f"\nSubject: {subject}")
        print(f"HTML saved: {filepath}\n")
        if preview:
            webbrowser.open(filepath.as_uri())
    else:
        success = send_email(
            subject, html_report,
            recipients=AFFILIATE_RECIPIENTS or None,
        )
        if success:
            sent = _load_sent()
            sent.add(sent_key)
            SENT_LOG.write_text(json.dumps(sorted(sent)), encoding="utf-8")
            logger.info("Affiliate weekly report sent successfully.")
        else:
            logger.error("Failed to send affiliate weekly report.")
            send_alert(f"Affiliate weekly report SEND FAILED for {report_date} manager={manager_group}")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("Finished in %.1f seconds.", elapsed)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_manager_names() -> dict[str, str]:
    path = Path(__file__).parent / "manager_names.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Failed to load manager_names.json: %s", e)
        return {}


def main() -> None:
    dry_run  = "--dry-run" in sys.argv
    preview  = "--preview" in sys.argv
    run_all  = "--all"     in sys.argv

    # --manager "affiliate 1"
    manager_group: str | None = None
    if "--manager" in sys.argv:
        idx = sys.argv.index("--manager")
        if idx + 1 < len(sys.argv):
            manager_group = sys.argv[idx + 1].strip().lower()
        else:
            print("--manager requires a value, e.g. --manager \"affiliate 1\"")
            sys.exit(1)

    # Collect positional args
    positional = []
    skip_next = False
    for a in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if a == "--manager":
            skip_next = True
            continue
        if not a.startswith("--"):
            positional.append(a)

    if positional:
        try:
            report_date = date.fromisoformat(positional[0])
        except ValueError:
            print(f"Invalid date: {positional[0]}. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        report_date = date.today()

    if run_all:
        managers = list(_load_manager_names().keys())
        logger.info("--all mode: running for %d managers: %s", len(managers), managers)
        for mgr in managers:
            logger.info("--- Running for manager: %s ---", mgr)
            try:
                run(report_date, dry_run=dry_run, preview=preview, manager_group=mgr)
            except Exception as e:
                logger.error("Failed for manager %s: %s", mgr, e)
        logger.info("--all mode completed.")
    else:
        run(report_date, dry_run=dry_run, preview=preview, manager_group=manager_group)


if __name__ == "__main__":
    main()
