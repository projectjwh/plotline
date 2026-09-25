from __future__ import annotations

import re

from src.app.core.errors import Conflict, Invalid, NotFound, Unauthorized
from src.app.identity.provider import AuthProvider
from src.app.identity.repo import UserRepo

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HANDLE = re.compile(r"^[A-Za-z0-9_]{3,24}$")


def public_user(u: dict) -> dict:
    return {"id": u["id"], "handle": u["handle"], "is_admin": bool(u["is_admin"])}


class IdentityService:
    def __init__(self, repo: UserRepo, provider: AuthProvider):
        self.repo, self.provider = repo, provider

    def register(self, email: str, password: str, handle: str) -> dict:
        email = email.strip().lower()
        if not _EMAIL.match(email):
            raise Invalid("invalid email")
        if not _HANDLE.match(handle):
            raise Invalid("handle must be 3–24 letters, digits or underscores")
        if len(password) < 10:
            raise Invalid("password must be at least 10 characters")
        if self.repo.by_email(email):
            raise Conflict("email already registered")
        if self.repo.by_handle(handle):
            raise Conflict("handle taken")
        # admin is never granted at sign-up (emails are unverified); use `python -m src.app.cli make-admin`
        return self.repo.create(email, handle, self.provider.hash_password(password), False)

    def login(self, email: str, password: str) -> tuple[dict, str]:
        u = self.repo.by_email(email.strip().lower())
        if not u or not self.provider.verify_password(u["password_hash"], password):
            raise Unauthorized("wrong email or password")
        return u, self.provider.issue_token(u["id"])

    def user_from_token(self, token: str) -> dict:
        u = self.repo.by_id(self.provider.decode_token(token))
        if not u:
            raise Unauthorized("user no longer exists")
        return u

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
