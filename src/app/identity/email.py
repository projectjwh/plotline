"""EmailSender: how account mail leaves the system. Replaceable from config (identity.email_sender).

``console`` keeps mail in memory and logs it, for dev and tests. ``resend`` posts to
the Resend HTTP API (https://resend.com/docs/api-reference/emails/send-email) with the
API key from RESEND_API_KEY.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Protocol

from src.app.core.errors import Unavailable
from src.app.core.registry import Registry

log = logging.getLogger("plotline.email")
email_senders = Registry("email sender")


class EmailSender(Protocol):
    def send(self, to: str, subject: str, text: str) -> None: ...


@email_senders.register("console")
class ConsoleSender:
    def __init__(self, **_):
        self.outbox: list[dict] = []

    def send(self, to: str, subject: str, text: str) -> None:
        self.outbox.append({"to": to, "subject": subject, "text": text})
        # dev/tests only (context.py refuses this sender in prod), so the link can be printed
        log.info("email (console) to=%s subject=%s\n%s", to, subject, text)


@email_senders.register("resend")
class ResendSender:
    URL = "https://api.resend.com/emails"

    def __init__(self, api_key: str | None, sender: str, **_):
        if not api_key:
            raise RuntimeError("identity.email_sender is 'resend' but RESEND_API_KEY is not set")
        self.key, self.sender = api_key, sender

    def send(self, to: str, subject: str, text: str) -> None:
        body = json.dumps({"from": self.sender, "to": [to], "subject": subject, "text": text}).encode()
        req = urllib.request.Request(self.URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 — fixed https URL
                if r.status >= 300:
                    raise Unavailable(f"email provider returned {r.status}")
        except OSError as e:
            log.error("resend send failed: %s", e)
            raise Unavailable("could not send email right now; try again shortly") from None
