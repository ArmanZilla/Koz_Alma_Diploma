"""
KozAlma AI — Notification Service.

Sends OTP codes via configured channels:
  • Email (SMTP/STARTTLS) — Gmail App Password compatible
  • WhatsApp — via Twilio API (sandbox or business number)
  • Dev mode — prints OTP to console (OTP_DEV_MODE=true)
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import get_settings

logger = logging.getLogger(__name__)


async def send_otp(channel: str, identifier: str, code: str) -> bool:
    """Dispatch OTP via the appropriate channel.

    Returns True if sent (or logged in dev mode), False on failure.
    IMPORTANT: always return ok=true to the user (no enumeration),
    but log errors internally.
    """
    settings = get_settings()

    # Dev mode — print to console, do NOT send
    if settings.otp_dev_mode:
        print(f"\n{'='*50}")
        print(f"  [DEV MODE] OTP for {identifier}: {code}")
        print(f"{'='*50}\n")
        return True

    if channel == "email":
        return _send_email(identifier, code)
    elif channel == "whatsapp":
        return _send_whatsapp(identifier, code)
    elif channel == "phone":
        # Legacy "phone" channel → route to WhatsApp
        return _send_whatsapp(identifier, code)
    else:
        logger.error("Unknown OTP channel: %s", channel)
        return False


def _send_email(to_email: str, code: str) -> bool:
    """Send OTP via Gmail-compatible SMTP (STARTTLS).

    Uses MIMEText for proper encoding.
    Requires Gmail App Password (2FA must be enabled on the account).
    """
    settings = get_settings()

    if not settings.smtp_host:
        logger.error("SMTP_HOST not configured — cannot send email OTP")
        return False

    if not settings.smtp_user or not settings.smtp_pass:
        logger.error("SMTP_USER or SMTP_PASS not set — cannot send email OTP")
        return False

    sender = settings.smtp_from or settings.smtp_user
    ttl_min = settings.otp_ttl_seconds // 60

    # Build MIME message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "KozAlma AI — Код подтверждения"
    msg["From"] = sender
    msg["To"] = to_email

    # Plain text body
    text_body = (
        f"Ваш код подтверждения: {code}\n\n"
        f"Код действителен {ttl_min} минут.\n"
        f"Если вы не запрашивали код, просто проигнорируйте это сообщение."
    )

    # HTML body (renders nicer in Gmail/Outlook)
    html_body = f"""\
<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
  <div style="max-width: 400px; margin: 0 auto; text-align: center;">
    <h2 style="color: #6C63FF;">KozAlma AI</h2>
    <p style="font-size: 16px; color: #333;">Ваш код подтверждения:</p>
    <div style="font-size: 36px; font-weight: bold; letter-spacing: 8px;
                color: #6C63FF; padding: 20px; background: #f5f5f5;
                border-radius: 12px; margin: 16px 0;">
      {code}
    </div>
    <p style="font-size: 14px; color: #666;">
      Код действителен {ttl_min} минут.<br>
      Если вы не запрашивали код, проигнорируйте это сообщение.
    </p>
  </div>
</body>
</html>"""

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(sender, [to_email], msg.as_string())

        logger.info("✅ Email OTP sent to %s****", to_email[:4])
        return True

    except smtplib.SMTPAuthenticationError as exc:
        logger.error(
            "❌ SMTP auth failed (check SMTP_USER/SMTP_PASS, "
            "Gmail requires App Password with 2FA): %s", exc
        )
        return False
    except smtplib.SMTPException as exc:
        logger.error("❌ SMTP error sending to %s****: %s", to_email[:4], exc)
        return False
    except Exception as exc:
        logger.error("❌ Unexpected email error for %s****: %s", to_email[:4], exc)
        return False


def _send_whatsapp(phone: str, code: str) -> bool:
    """Send OTP via Twilio WhatsApp API.

    Supports both Twilio Sandbox and Business numbers.

    NOTE — Twilio Sandbox:
      Before receiving messages, the user must first send:
          join <your-sandbox-keyword>
      to the sandbox number (e.g. +1 415 523 8886) from their WhatsApp.
      This is a Twilio sandbox requirement, not a KozAlma limitation.

    Args:
        phone: Phone number, e.g. "+77789826080" or "whatsapp:+77789826080"
        code:  6-digit OTP code (NOT logged in production)
    """
    settings = get_settings()

    # ── Validate Twilio credentials ──
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        logger.error(
            "❌ Twilio not configured (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN empty) "
            "— cannot send WhatsApp OTP"
        )
        return False

    # ── Normalize identifier to whatsapp: format ──
    to_number = phone.strip()
    if not to_number.startswith("whatsapp:"):
        to_number = f"whatsapp:{to_number}"

    from_number = settings.twilio_whatsapp_from.strip()
    if not from_number.startswith("whatsapp:"):
        from_number = f"whatsapp:{from_number}"

    # ── Send via Twilio ──
    try:
        from twilio.rest import Client
        from twilio.base.exceptions import TwilioRestException

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

        ttl_min = settings.otp_ttl_seconds // 60
        message = client.messages.create(
            body=(
                f"KozAlma AI — ваш код подтверждения: {code}\n"
                f"Код действителен {ttl_min} минут.\n"
                f"Не сообщайте код никому."
            ),
            from_=from_number,
            to=to_number,
        )

        # Log success (SID only, never the code)
        logger.info(
            "✅ WhatsApp OTP sent to %s**** (SID: %s)",
            phone[:4], message.sid
        )
        return True

    except ImportError:
        logger.error(
            "❌ 'twilio' package not installed — run: pip install twilio"
        )
        return False
    except Exception as exc:
        # Catch TwilioRestException and any other errors
        # Log error but NOT the code — prevent leakage
        logger.error(
            "❌ WhatsApp OTP failed for %s****: %s",
            phone[:4], exc
        )
        return False
