"""Send the one-time verification code by e-mail over SMTP. Blocking; call from a thread."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from stuard.settings import Settings

log = logging.getLogger(__name__)


class Mailer:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def configured(self) -> bool:
        return bool(self.s.smtp_host and self.s.smtp_from)

    def send(self, to: str, subject: str, body: str) -> bool:
        if not self.configured():
            log.warning("SMTP is not configured (SMTP_HOST / SMTP_FROM); cannot send verification e-mail")
            return False
        msg = EmailMessage()
        msg["From"] = self.s.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            if self.s.smtp_ssl:
                server: smtplib.SMTP = smtplib.SMTP_SSL(
                    self.s.smtp_host, self.s.smtp_port, timeout=20, context=ssl.create_default_context()
                )
            else:
                server = smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=20)
            with server:
                if self.s.smtp_starttls and not self.s.smtp_ssl:
                    server.starttls(context=ssl.create_default_context())
                user = self.s.smtp_user
                password = self.s.smtp_password.get_secret_value()
                if user and password:
                    server.login(user, password)
                server.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            log.warning("could not send verification e-mail: %r", exc)
            return False
        return True
