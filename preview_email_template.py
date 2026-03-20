"""
Generate a preview of the email report with REAL data from Google Sheets.
Opens the result in the default browser.

Usage:
    python preview_email_template.py              # report for yesterday
    python preview_email_template.py 2026-02-10   # report for a specific date
"""

import sys
import webbrowser
from datetime import date, timedelta
from pathlib import Path

from sheets_client import collect_sheets_metrics
from email_report_builder import build_email_report, build_email_subject

PREVIEW_DIR = Path(__file__).parent / "logs" / "previews"


def main():
    # Parse date from CLI args
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        try:
            target_date = date.fromisoformat(args[0])
        except ValueError:
            print(f"Invalid date format: {args[0]}. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        target_date = date.today() - timedelta(days=1)

    print(f"Fetching data from Google Sheets for {target_date}...")

    try:
        data = collect_sheets_metrics(target_date)
    except Exception as e:
        import traceback
        print(f"Failed to fetch data: {e}")
        traceback.print_exc()
        sys.exit(1)

    # Check if data exists
    if data["data"].get("deposits", 0) == 0 and data["data"].get("registrations", 0) == 0:
        print(f"No data found for {target_date}. Sheet may not be updated yet.")
        sys.exit(1)

    # Build HTML
    html = build_email_report(data)
    subject = build_email_subject(data)

    # Save and open
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    filepath = PREVIEW_DIR / f"preview_{target_date.isoformat()}.html"
    filepath.write_text(html, encoding="utf-8")

    print(f"Subject: {subject}")
    print(f"Preview saved to: {filepath}")
    webbrowser.open(filepath.as_uri())


if __name__ == "__main__":
    main()
