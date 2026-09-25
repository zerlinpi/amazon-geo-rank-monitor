from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

logger = logging.getLogger("amazon_geo_rank_monitor.email")


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


@dataclass(frozen=True)
class SentEmail:
    to: str
    subject: str
    text: str
    attachments: tuple[EmailAttachment, ...] = ()


class ConsoleEmailSender:
    def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> None:
        logger.info(
            "development_email to=%s subject=%s body=%s",
            to,
            subject,
            text.replace("\n", " | "),
        )
        if attachments:
            logger.info(
                "development_email_attachments to=%s files=%s",
                to,
                ",".join(item.filename for item in attachments),
            )


class MemoryEmailSender:
    def __init__(self) -> None:
        self.messages: list[SentEmail] = []

    def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> None:
        self.messages.append(
            SentEmail(
                to=to,
                subject=subject,
                text=text,
                attachments=tuple(attachments or []),
            )
        )


class SmtpEmailSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_email: str,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = True,
        timeout: float = 15.0,
    ) -> None:
        self._host = host
        self._port = port
        self._from_email = from_email
        self._username = username
        self._password = password
        self._starttls = starttls
        self._timeout = timeout

    def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> None:
        message = EmailMessage()
        message["From"] = self._from_email
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        for attachment in attachments or []:
            maintype, _, subtype = attachment.content_type.partition("/")
            if not subtype:
                maintype = "application"
                subtype = "octet-stream"
            message.add_attachment(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.filename,
            )

        with smtplib.SMTP(
            self._host,
            self._port,
            timeout=self._timeout,
        ) as client:
            if self._starttls:
                client.starttls()
            if self._username:
                client.login(self._username, self._password or "")
            client.send_message(message)


def build_email_sender(settings):
    if not settings.smtp_host:
        return ConsoleEmailSender()
    if not settings.smtp_from_email:
        raise ValueError("SMTP_FROM_EMAIL is required when SMTP_HOST is configured")
    return SmtpEmailSender(
        host=settings.smtp_host,
        port=settings.smtp_port,
        from_email=settings.smtp_from_email,
        username=settings.smtp_username,
        password=settings.smtp_password,
        starttls=settings.smtp_starttls,
    )
