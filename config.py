import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "25060")),
    "database": os.getenv("DB_NAME", "platform"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "sslmode": os.getenv("DB_SSLMODE", "require"),
}

TELEGRAM_BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID      = os.getenv("TELEGRAM_CHAT_ID", "")
RISK_TELEGRAM_CHAT_ID = os.getenv("RISK_TELEGRAM_CHAT_ID", "")

ALERT_THRESHOLD_PCT = float(os.getenv("ALERT_THRESHOLD_PCT", "20"))

TOP_COUNTRIES_LIMIT = 10

# Google Sheets
GOOGLE_SHEETS_URL = os.getenv(
    "GOOGLE_SHEETS_URL",
    "https://docs.google.com/spreadsheets/d/1G1ZR2wXQCX6L4yDFuwjZAZUMFiqWa_MTcfjL6Wm2PJM/edit",
)
GOOGLE_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CREDENTIALS_PATH",
    str(Path(__file__).parent.parent / "google_sheets" / "credentials.json"),
)

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Email
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_SENDER_NAME = os.getenv("EMAIL_SENDER_NAME", "BetAndYou Analytics")
EMAIL_RECIPIENTS = [
    r.strip() for r in os.getenv("EMAIL_RECIPIENTS", "").split(",") if r.strip()
]
