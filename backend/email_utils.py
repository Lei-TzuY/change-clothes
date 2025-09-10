import smtplib
from email.message import EmailMessage
from typing import Optional

from flask import current_app


def send_mail(to: str, subject: str, html: str, text: Optional[str] = None) -> None:
    cfg = current_app.config
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("MAIL_SENDER", "noreply@localhost")
    msg["To"] = to
    if text:
        msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    host = cfg.get("MAIL_SERVER", "localhost")
    port = int(cfg.get("MAIL_PORT", 25))
    use_ssl = bool(cfg.get("MAIL_USE_SSL"))
    use_tls = bool(cfg.get("MAIL_USE_TLS"))
    username = cfg.get("MAIL_USERNAME")
    password = cfg.get("MAIL_PASSWORD")

    # Dev shortcut: only print mail content instead of sending
    if cfg.get("MAIL_DEV_PRINT"):
        current_app.logger.info("[MAIL_DEV_PRINT] To=%s Subject=%s\n%s", to, subject, html)
        return

    if use_ssl:
        smtp = smtplib.SMTP_SSL(host=host, port=port, timeout=10)
    else:
        smtp = smtplib.SMTP(host=host, port=port, timeout=10)
    try:
        if use_tls and not use_ssl:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
