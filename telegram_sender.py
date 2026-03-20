"""
Send messages via Telegram Bot API.
"""

import logging
import time

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

MAX_RETRIES = 3
RETRY_DELAY_SEC = 5
MAX_MESSAGE_LENGTH = 4096


def send_message(text: str, chat_id: str = "", parse_mode: str = "") -> bool:
    """
    Send a text message to Telegram.
    Returns True on success, False on failure after retries.
    """
    chat_id = chat_id or TELEGRAM_CHAT_ID
    token = TELEGRAM_BOT_TOKEN

    if not token or token == "your_bot_token_here":
        logger.warning("Telegram bot token not configured. Skipping send.")
        return False

    if not chat_id or chat_id == "your_chat_id_here":
        logger.warning("Telegram chat_id not configured. Skipping send.")
        return False

    url = TELEGRAM_API_URL.format(token=token)

    # Telegram limit is 4096 chars per message. Truncate if needed.
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[: MAX_MESSAGE_LENGTH - 20] + "\n\n... (truncated)"

    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    logger.info("Message sent successfully (attempt %d).", attempt)
                    return True
                logger.error("Telegram API returned ok=false: %s", data)
            elif resp.status_code == 429:
                retry_after = resp.json().get("parameters", {}).get("retry_after", RETRY_DELAY_SEC)
                logger.warning("Rate limited. Retrying after %ds.", retry_after)
                time.sleep(retry_after)
                continue
            else:
                logger.error("Telegram API HTTP %d: %s", resp.status_code, resp.text)
        except requests.RequestException as e:
            logger.error("Request failed (attempt %d): %s", attempt, e)

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_SEC)

    logger.error("Failed to send message after %d attempts.", MAX_RETRIES)
    return False


def send_alert(text: str) -> bool:
    """Send an alert/error notification (same channel, prefixed)."""
    return send_message(f"[ALERT] Daily Report\n\n{text}")


def send_risk_report(data: dict, target_date, chat_id: str = "") -> bool:
    """Format and send the risk report as a Telegram HTML message."""
    from config import RISK_TELEGRAM_CHAT_ID
    from datetime import date as _date

    chat_id = chat_id or RISK_TELEGRAM_CHAT_ID
    if not chat_id:
        logger.warning("RISK_TELEGRAM_CHAT_ID not set. Skipping Telegram send.")
        return False

    day_names = {0:"Mon",1:"Tue",2:"Wed",3:"Thu",4:"Fri",5:"Sat",6:"Sun"}
    d: _date = target_date
    header = (
        f"<b>Risk Report — {d.strftime('%d %b %Y')} ({day_names[d.weekday()]})</b>\n"
        f"<i>Profit = Winnings - Bets (USD)</i>\n"
    )

    def _fmt(v: float) -> str:
        return f"${v:,.0f}"

    def _profit_block(title: str, rows: list[dict]) -> str:
        lines = [f"\n<b>{title}</b>"]
        if not rows:
            lines.append("  No data")
        else:
            for i, r in enumerate(rows, 1):
                profit   = _fmt(r["amount_usd"])
                winnings = _fmt(r.get("winnings", 0))
                bets     = _fmt(r.get("bets", 0))
                lines.append(
                    f"  {i}. <code>{r['player_id']}</code>  "
                    f"+{profit}  (wins {winnings} / bets {bets})"
                )
        return "\n".join(lines)

    def _simple_block(title: str, rows: list[dict]) -> str:
        lines = [f"\n<b>{title}</b>"]
        if not rows:
            lines.append("  No data")
        else:
            for i, r in enumerate(rows, 1):
                lines.append(
                    f"  {i}. <code>{r['player_id']}</code>  {_fmt(r['amount_usd'])}"
                )
        return "\n".join(lines)

    body = (
        _profit_block("Casino Profit — Top 5",  data.get("casino", []))
        + _profit_block("Sport Profit — Top 10", data.get("sport", []))
        + _simple_block("Deposits — Top 5",      data.get("deposits", []))
        + _simple_block("Withdrawals — Top 10",  data.get("withdrawals", []))
    )

    text = header + body
    return send_message(text, chat_id=chat_id, parse_mode="HTML")
