"""Settings (from the environment) and policy files (YAML).

Settings describe *where* things live: databases, secrets and origins. Policy files
describe *how* the product behaves: entitlements, KPI visibility, thresholds and
model parameters. Policy is data, so business rules change without code changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
DEV_SECRET = "dev-insecure-secret-change-me"


def _csv(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


@dataclass
class Settings:
    env: str = "dev"
    app_db_url: str = f"sqlite:///{ROOT / 'data' / 'app.db'}"
    warehouse_path: str = str(ROOT / "data" / "plotline.duckdb")
    doc_storage_dir: str = str(ROOT / "data" / "private" / "claims")
    policy_dir: str = str(ROOT / "config" / "policy")
    jwt_secret: str = DEV_SECRET
    jwt_ttl_minutes: int = 60 * 24
    ip_hash_salt: str = "dev-ip-salt"
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    trust_proxy: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls()
        e = os.environ.get
        s.env = e("PLOTLINE_ENV", s.env)
        s.app_db_url = e("PLOTLINE_APP_DB_URL") or e("DATABASE_URL") or s.app_db_url
        s.warehouse_path = e("PLOTLINE_WAREHOUSE_PATH", s.warehouse_path)
        s.doc_storage_dir = e("PLOTLINE_DOC_DIR", s.doc_storage_dir)
        s.policy_dir = e("PLOTLINE_POLICY_DIR", s.policy_dir)
        s.jwt_secret = e("PLOTLINE_JWT_SECRET", s.jwt_secret)
        s.jwt_ttl_minutes = int(e("PLOTLINE_JWT_TTL_MINUTES", s.jwt_ttl_minutes))
        s.ip_hash_salt = e("PLOTLINE_IP_SALT", s.ip_hash_salt)
        s.cors_origins = _csv(e("PLOTLINE_CORS_ORIGINS")) or s.cors_origins
        s.trust_proxy = e("PLOTLINE_TRUST_PROXY", "false").lower() == "true"
        s.validate()
        return s

    def validate(self) -> None:
        if self.env == "prod" and (self.jwt_secret == DEV_SECRET or len(self.jwt_secret) < 32
                                   or self.ip_hash_salt == "dev-ip-salt"):
            raise RuntimeError("set PLOTLINE_JWT_SECRET (≥ 32 chars) and PLOTLINE_IP_SALT in prod")


class Policy:
    """Read-only access to the YAML policy files in ``settings.policy_dir``."""

    def __init__(self, policy_dir: str):
        self.dir = Path(policy_dir)

    @lru_cache(maxsize=None)
    def load(self, name: str) -> dict:
        with open(self.dir / f"{name}.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def app(self, *path: str, default=None):
        node = self.load("app")
        for p in path:
            if not isinstance(node, dict) or p not in node:
                return default
            node = node[p]
        return node
