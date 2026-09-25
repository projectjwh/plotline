"""AuthProvider: the replaceable seam for credentials and tokens (built-in JWT now, an external IdP later)."""
from __future__ import annotations

from typing import Protocol

from src.app.core.registry import Registry

auth_providers = Registry("auth provider")


class AuthProvider(Protocol):
    def hash_password(self, password: str) -> str: ...
    def verify_password(self, hashed: str, password: str) -> bool: ...
    def issue_token(self, user_id: str) -> str: ...
    def decode_token(self, token: str) -> str:
        """Return the user id, or raise Unauthorized."""
        ...
