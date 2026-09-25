"""Accounts: sign-up, login, email verification, password reset, throttling (decisions D-014, D-032)."""
from __future__ import annotations

import re
from datetime import timedelta

from src.app.core.db import now
from src.app.core.errors import Conflict, Invalid, NotFound, RateLimited, Unauthorized
from src.app.identity.email import EmailSender
from src.app.identity.provider import AuthProvider
from src.app.identity.repo import UserRepo

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HANDLE = re.compile(r"^[A-Za-z0-9_]{3,24}$")
LOCALES = {"en", "ko"}


def public_user(u: dict) -> dict:
    return {"id": u["id"], "handle": u["handle"], "is_admin": bool(u["is_admin"]),
            "email_verified": bool(u.get("email_verified_at")), "locale": u.get("locale") or "en"}


class IdentityService:
    def __init__(self, repo: UserRepo, provider: AuthProvider, mailer: EmailSender, cfg: dict, app_base_url: str):
        self.repo, self.provider, self.mailer, self.cfg = repo, provider, mailer, cfg
        self.base = app_base_url.rstrip("/")
        # checked when the email is unknown, so a failed login takes as long either way (no enumeration by timing)
        self._dummy_hash = provider.hash_password("not-a-real-password-" + "x" * 16)

    # ---------- throttling ----------
    def _throttle(self, keys: list[str], kind: str) -> None:
        t = self.cfg.get("throttle", {})
        limit, window = t.get("max_failures", 5), t.get("window_minutes", 15)
        since = now() - timedelta(minutes=window)
        if any(self.repo.failures_since(k, kind, since) >= limit for k in keys):
            raise RateLimited(f"too many attempts; try again in {window} minutes")

    # ---------- sign-up / login ----------
    def register(self, email: str, password: str, handle: str, *, ip_key: str, locale: str = "en") -> dict:
        email = email.strip().lower()
        self._throttle([ip_key], "signup")
        try:
            if not _EMAIL.match(email):
                raise Invalid("invalid email")
            if not _HANDLE.match(handle):
                raise Invalid("handle must be 3–24 letters, digits or underscores")
            if len(password) < 10:
                raise Invalid("password must be at least 10 characters")
            if locale not in LOCALES:
                raise Invalid("locale must be en or ko")
            if self.repo.by_email(email):
                raise Conflict("email already registered")
            if self.repo.by_handle(handle):
                raise Conflict("handle taken")
        except (Invalid, Conflict):
            self.repo.record_attempt([ip_key], "signup", False)
            raise
        # admin is never granted at sign-up (emails are unverified); use `python -m src.app.cli make-admin`
        u = self.repo.create(email, handle, self.provider.hash_password(password), False, locale)
        self.repo.record_attempt([ip_key], "signup", True)
        self.send_verification(u)
        return u

    def login(self, email: str, password: str, *, ip_key: str) -> tuple[dict, str]:
        email = email.strip().lower()
        keys = [f"email:{email}", ip_key]
        self._throttle(keys, "login")
        u = self.repo.by_email(email)
        ok = self.provider.verify_password(u["password_hash"] if u else self._dummy_hash, password)
        if not u or not ok:
            self.repo.record_attempt(keys, "login", False)
            raise Unauthorized("wrong email or password")
        self.repo.record_attempt(keys, "login", True)
        return u, self.access_token(u)

    def access_token(self, u: dict) -> str:
        return self.provider.issue_token(u["id"], version=u["token_version"] or 0)

    def user_from_token(self, token: str) -> dict:
        claims = self.provider.decode_token(token, "access")
        u = self.repo.by_id(claims["sub"])
        if not u:
            raise Unauthorized("user no longer exists")
        if claims.get("ver", 0) != (u["token_version"] or 0):
            raise Unauthorized("session ended; sign in again")
        return u

    # ---------- email verification ----------
    def send_verification(self, u: dict) -> None:
        if u.get("email_verified_at"):
            return
        tok = self.provider.issue_token(u["id"], version=u["token_version"] or 0, purpose="verify",
                                        ttl_minutes=self.cfg.get("verify_ttl_minutes", 1440))
        self.mailer.send(u["email"], "Confirm your Plotline email",
                         f"Confirm your email to rate, wish and post under your name:\n{self.base}/verify?token={tok}\n"
                         "The link expires in 24 hours.")

    def confirm_verification(self, token: str) -> dict:
        claims = self.provider.decode_token(token, "verify")
        u = self.repo.by_id(claims["sub"])
        if not u:
            raise NotFound("user not found")
        if not u["email_verified_at"]:
            self.repo.patch(u["id"], email_verified_at=now())
        return self.repo.by_id(u["id"])

    # ---------- password reset ----------
    def forgot(self, email: str, *, ip_key: str) -> None:
        """Always succeeds from the caller's view, so it does not reveal which emails exist."""
        email = email.strip().lower()
        self._throttle([ip_key], "forgot")
        self.repo.record_attempt([ip_key], "forgot", False)   # every request counts toward the limit
        u = self.repo.by_email(email)
        if not u:
            return
        tok = self.provider.issue_token(u["id"], version=u["token_version"] or 0, purpose="reset",
                                        ttl_minutes=self.cfg.get("reset_ttl_minutes", 30))
        self.mailer.send(u["email"], "Reset your Plotline password",
                         f"Reset your password here:\n{self.base}/reset?token={tok}\n"
                         "The link expires in 30 minutes. If you didn't ask for this, ignore this email.")

    def reset(self, token: str, new_password: str) -> None:
        claims = self.provider.decode_token(token, "reset")
        u = self.repo.by_id(claims["sub"])
        if not u or claims.get("ver", 0) != (u["token_version"] or 0):
            raise Unauthorized("this reset link has already been used or has expired")
        if len(new_password) < 10:
            raise Invalid("password must be at least 10 characters")
        self.repo.set_password(u["id"], self.provider.hash_password(new_password))  # bumps token_version
        if not u["email_verified_at"]:
            self.repo.patch(u["id"], email_verified_at=now())  # the reset link proves mailbox access

    # ---------- profile ----------
    def set_locale(self, user_id: str, locale: str) -> dict:
        if locale not in LOCALES:
            raise Invalid("locale must be en or ko")
        self.repo.patch(user_id, locale=locale)
        return self.repo.by_id(user_id)

    def get(self, user_id: str) -> dict | None:
        return self.repo.by_id(user_id)

    def set_admin(self, email: str, is_admin: bool) -> dict:
        u = self.repo.by_email(email.strip().lower())
        if not u:
            raise NotFound("user not found")
        self.repo.set_admin(u["id"], is_admin)
        return {**u, "is_admin": is_admin}

    def by_handle(self, handle: str) -> dict:
        u = self.repo.by_handle(handle)
        if not u:
            raise NotFound("user not found")
        return u
