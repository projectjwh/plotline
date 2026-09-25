"""Built-in auth: argon2 password hashes plus HS256 access tokens. There is no vendor cost."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from src.app.core.errors import Unauthorized
from src.app.identity.provider import auth_providers

_ph = PasswordHasher()


def hash_secret(secret: str) -> str:
    return _ph.hash(secret)


def verify_secret(hashed: str | None, secret: str | None) -> bool:
    if not hashed or secret is None:
        return False
    try:
        return _ph.verify(hashed, secret)
    except (VerifyMismatchError, InvalidHashError):
        return False


@auth_providers.register("builtin_jwt")
class BuiltinJWTProvider:
    ALG = "HS256"

    def __init__(self, secret: str, ttl_minutes: int):
        self.secret, self.ttl = secret, ttl_minutes

    def hash_password(self, password: str) -> str:
        return hash_secret(password)

    def verify_password(self, hashed: str, password: str) -> bool:
        return verify_secret(hashed, password)

    def issue_token(self, user_id: str) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode({"sub": user_id, "iat": now, "exp": now + timedelta(minutes=self.ttl)},
                          self.secret, algorithm=self.ALG)

    def decode_token(self, token: str) -> str:
        try:
            return jwt.decode(token, self.secret, algorithms=[self.ALG])["sub"]
        except jwt.PyJWTError as e:
            raise Unauthorized(f"invalid token: {e.__class__.__name__}") from None
