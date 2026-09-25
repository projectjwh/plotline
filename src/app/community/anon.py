"""Guest (DCInside-style) identity: a nickname plus a password, the first two IP octets for
display, and a salted IP hash for moderation. The raw IP is never stored."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress


def ip_prefix(ip: str | None) -> str:
    try:
        a = ipaddress.ip_address(ip or "")
    except ValueError:
        return "?"
    if a.version == 4:
        return ".".join(str(a).split(".")[:2])
    return ":".join(a.exploded.split(":")[:2])


def ip_hash(ip: str | None, salt: str) -> str:
    return hmac.new(salt.encode(), (ip or "").encode(), hashlib.sha256).hexdigest()[:40]


def voter_key(user_id: str | None, iph: str) -> str:
    return f"u:{user_id}" if user_id else f"ip:{iph}"
