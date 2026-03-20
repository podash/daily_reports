"""
Send HTML email reports via SMTP.

Supports Gmail, Outlook, and custom SMTP servers.
Uses TLS by default.
"""

import logging
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import (
    EMAIL_SMTP_HOST,
    EMAIL_SMTP_PORT,
    EMAIL_SENDER,
    EMAIL_PASSWORD,
    EMAIL_RECIPIENTS,
    EMAIL_SENDER_NAME,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
TIMEOUT_SEC = 30


def send_email(
    subject: str,
    html_body: str,
    recipients: list[str] | None = None,
    inline_images: dict[str, bytes] | None = None,
) -> bool:
    """
    Send an HTML email to the configured recipients.
    inline_images: dict of {content_id: png_bytes} for CID-embedded images.
    Returns True on success, False on failure.
    """
    recipients = recipients or EMAIL_RECIPIENTS

    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        logger.warning("Email credentials not configured. Skipping send.")
        return False

    if not recipients:
        logger.warning("No email recipients configured. Skipping send.")
        return False

    # Build MIME structure: related > alternative + images
    if inline_images:
        outer = MIMEMultipart("related")
        alt   = MIMEMultipart("alternative")
        outer.attach(alt)
    else:
        outer = MIMEMultipart("alternative")
        alt   = outer

    outer["Subject"] = subject
    outer["From"] = f"{EMAIL_SENDER_NAME} <{EMAIL_SENDER}>" if EMAIL_SENDER_NAME else EMAIL_SENDER
    outer["To"] = ", ".join(recipients)

    plain_text = (
        f"{subject}\n\n"
        "This report is best viewed in an HTML-capable email client.\n"
        "Please enable HTML rendering to see the full report."
    )
    alt.attach(MIMEText(plain_text, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))

    if inline_images:
        for cid, png_bytes in inline_images.items():
            img = MIMEImage(png_bytes, "png")
            img.add_header("Content-ID", f"<{cid}>")
            img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
            outer.attach(img)

    # Try STARTTLS (port 587), then fallback to SSL (port 465)
    connection_strategies = [
        ("STARTTLS", EMAIL_SMTP_PORT, False),
        ("SSL",      465,             True),
    ]

    for strategy_name, port, use_ssl in connection_strategies:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if use_ssl:
                    ctx = smtplib.SMTP_SSL(EMAIL_SMTP_HOST, port, timeout=TIMEOUT_SEC)
                    server = ctx.__enter__()
                else:
                    ctx = smtplib.SMTP(EMAIL_SMTP_HOST, port, timeout=TIMEOUT_SEC)
                    server = ctx.__enter__()
                    server.ehlo()
                    server.starttls()
                    server.ehlo()

                with ctx:
                    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                    server.sendmail(EMAIL_SENDER, recipients, outer.as_string())

                logger.info(
                    "Email sent successfully to %s (%s, attempt %d).",
                    ", ".join(recipients), strategy_name, attempt,
                )
                return True

            except smtplib.SMTPAuthenticationError as e:
                logger.error("SMTP authentication failed: %s", e)
                return False

            except OSError as e:
                logger.warning("Connection failed (%s, attempt %d): %s", strategy_name, attempt, e)
                if attempt >= MAX_RETRIES:
                    logger.warning("Switching strategy after %s failed.", strategy_name)
                    break

            except Exception as e:
                logger.error("Failed to send email (%s, attempt %d): %s", strategy_name, attempt, e)
                if attempt >= MAX_RETRIES:
                    break

    logger.error("All send strategies failed.")
    return False


def send_email_ssl(subject: str, html_body: str, recipients: list[str] | None = None) -> bool:
    """
    Send an HTML email using SMTP_SSL (port 465).
    Use this for servers that require SSL from the start (not STARTTLS).
    """
    recipients = recipients or EMAIL_RECIPIENTS

    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        logger.warning("Email credentials not configured. Skipping send.")
        return False

    if not recipients:
        logger.warning("No email recipients configured. Skipping send.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{EMAIL_SENDER_NAME} <{EMAIL_SENDER}>" if EMAIL_SENDER_NAME else EMAIL_SENDER
    msg["To"] = ", ".join(recipients)

    plain_text = (
        f"{subject}\n\n"
        "This report is best viewed in an HTML-capable email client."
    )
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=TIMEOUT_SEC) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, recipients, msg.as_string())

        logger.info("Email sent (SSL) to %s.", ", ".join(recipients))
        return True

    except Exception as e:
        logger.error("Failed to send email (SSL): %s", e)
        return False
