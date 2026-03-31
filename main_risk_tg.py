"""
Intraday Risk Report via Telegram.

Sends top players by profit for TODAY (from midnight to current moment).
Runs 3x/day: at 08:00, 13:00, 17:00 local time.

Time slot is detected automatically from the current hour:
  08:xx -> "0-8 год"
  13:xx -> "0-13 год"
  17:xx -> "0-17 год"

Requires aggregates.daily_player_casino_totals and daily_player_sport_totals
to be refreshed before each run (pg_cron handles this).

Usage:
    python main_risk_tg.py                        # auto-detect slot from current hour
    python main_risk_tg.py --slot 8               # force slot 0-8
    python main_risk_tg.py --slot 13              # force slot 0-13
    python main_risk_tg.py --slot 17              # force slot 0-17
    python main_risk_tg.py --date 2026-03-18      # send report for a specific date
    python main_risk_tg.py --dry-run              # print to console, don't send
"""

import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from config import LOG_DIR, RISK_TELEGRAM_CHAT_ID
from top_players import fetch_top_players_profit
from telegram_sender import send_message, send_alert

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LOG_FILE = LOG_DIR / "risk_tg.log"
SENT_LOG = LOG_DIR / "risk_tg_sent_slots.json"

SLOTS = [8, 13, 17]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("risk_tg")


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


def _mark_sent(key: str) -> None:
    sent = _load_sent()
    sent.add(key)
    SENT_LOG.write_text(json.dumps(sorted(sent)), encoding="utf-8")


def _already_sent(key: str) -> bool:
    return key in _load_sent()


# ---------------------------------------------------------------------------
# Slot detection
# ---------------------------------------------------------------------------

def _detect_slot() -> int:
    """Detect current time slot based on current hour."""
    hour = datetime.now().hour
    for slot in sorted(SLOTS):
        if hour < slot:
            return slot
    return SLOTS[-1]


# ---------------------------------------------------------------------------
# Message formatter
# ---------------------------------------------------------------------------

def _format_message(data: dict, today: date, slot: int) -> str:
    label = f"0-{slot} год"
    day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

    header = (
        f"<b>Risk Report — {today.strftime('%d %b %Y')} ({day_names[today.weekday()]})</b>\n"
        f"<i>Сьогодні {label}  |  Profit = Winnings - Bets</i>\n"
    )

    def _fmt(v: float) -> str:
        return f"${v:,.0f}"

    def _player_meta(r: dict) -> str:
        parts = []
        if r.get("currency"):
            parts.append(r["currency"])
        if r.get("affiliate_id"):
            parts.append(f"aff:{r['affiliate_id']}")
        return f"  [{', '.join(parts)}]" if parts else ""

    def _profit_block(title: str, rows: list[dict]) -> str:
        lines = [f"\n<b>{title}</b>"]
        if not rows:
            lines.append("  No data")
        else:
            for i, r in enumerate(rows, 1):
                lines.append(
                    f"  {i}. <code>{r['player_id']}</code>{_player_meta(r)}  "
                    f"+{_fmt(r['amount_usd'])}  "
                    f"(wins {_fmt(r.get('winnings', 0))} / bets {_fmt(r.get('bets', 0))})"
                )
        return "\n".join(lines)

    def _simple_block(title: str, rows: list[dict]) -> str:
        lines = [f"\n<b>{title}</b>"]
        if not rows:
            lines.append("  No data")
        else:
            for i, r in enumerate(rows, 1):
                lines.append(
                    f"  {i}. <code>{r['player_id']}</code>{_player_meta(r)}  {_fmt(r['amount_usd'])}"
                )
        return "\n".join(lines)

    body = (
        _profit_block("Casino Profit — Top 5", data.get("casino", []))
        + _profit_block("Sport Profit — Top 10", data.get("sport", []))
        + _simple_block("Deposits — Top 5", data.get("deposits", []))
        + _simple_block("Withdrawals — Top 10", data.get("withdrawals", []))
    )

    return header + body


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(slot: int, dry_run: bool = False, target_date: date | None = None) -> None:
    today = target_date or date.today()
    sent_key = f"{today.isoformat()}:{slot}"

    logger.info(
        "Starting intraday risk TG | date=%s | slot=0-%d | dry_run=%s",
        today, slot, dry_run,
    )

    if not dry_run and _already_sent(sent_key):
        logger.info("Slot %s already sent. Skipping.", sent_key)
        return

    try:
        data = fetch_top_players_profit(today)
    except Exception as e:
        logger.error("Failed to fetch top players: %s", e)
        if not dry_run:
            send_alert(f"Risk TG FAILED for {today} slot 0-{slot}: {e}")
        return

    text = _format_message(data, today, slot)

    if dry_run:
        print("\n" + "=" * 60)
        print(text)
        print("=" * 60 + "\n")
        return

    if not RISK_TELEGRAM_CHAT_ID:
        logger.error("RISK_TELEGRAM_CHAT_ID not set in .env")
        return

    ok = send_message(text, chat_id=RISK_TELEGRAM_CHAT_ID, parse_mode="HTML")
    if ok:
        _mark_sent(sent_key)
        logger.info("Intraday risk report sent. slot=0-%d", slot)
    else:
        logger.error("Failed to send intraday risk TG report.")
        send_alert(f"Risk TG SEND FAILED for {today} slot 0-{slot}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    dry_run = "--dry-run" in sys.argv

    slot: int | None = None
    if "--slot" in sys.argv:
        idx = sys.argv.index("--slot")
        if idx + 1 < len(sys.argv):
            try:
                slot = int(sys.argv[idx + 1])
            except ValueError:
                print("--slot requires an integer: 8, 13 or 17")
                sys.exit(1)

    target_date: date | None = None
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            try:
                target_date = date.fromisoformat(sys.argv[idx + 1])
            except ValueError:
                print("--date requires format YYYY-MM-DD, e.g. 2026-03-18")
                sys.exit(1)

    if slot is None:
        slot = _detect_slot()

    if slot not in SLOTS:
        print(f"Invalid slot {slot}. Must be one of {SLOTS}")
        sys.exit(1)

    run(slot, dry_run=dry_run, target_date=target_date)


if __name__ == "__main__":
    main()
