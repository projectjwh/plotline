"""Resolves who the viewer is (fan, author, publisher, investor or admin) from policy, claims and plans.

Policy (``config/policy/entitlements.yaml``) maps each premium persona to the claim
types that qualify for it and the plan that must be active. Nothing here hard-codes
those rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from src.app.core.errors import Forbidden, Invalid
from src.app.entitlement.repo import GrantRepo

FAN = "fan"


@dataclass(frozen=True)
class Viewer:
    user: dict | None = None
    is_admin: bool = False
    personas: frozenset[str] = frozenset()       # active premium personas
    claims: tuple[dict, ...] = field(default_factory=tuple)  # approved claims

    @property
    def user_id(self) -> str | None:
        return self.user["id"] if self.user else None

    @property
    def is_premium(self) -> bool:
        return bool(self.personas) or self.is_admin

    @property
    def audiences(self) -> frozenset[str]:
        """KPI audiences whose visibility applies. Fans are always included."""
        return frozenset({FAN}) | self.personas


ANON = Viewer()


def owns_title(claims, title: dict) -> bool:
    """True when an approved claim covers this title, directly or through its author or publisher."""
    for c in claims:
        t, ref = c["claim_type"], c["entity_ref"]
        if t == "title" and ref == title.get("comic_id"):
            return True
        if t == "author" and title.get("author") and ref.casefold() == str(title["author"]).casefold():
            return True
        if t == "publisher" and title.get("publisher") and ref.casefold() == str(title["publisher"]).casefold():
            return True
    return False


class EntitlementService:
    def __init__(self, repo: GrantRepo, policy: dict, approved_claims: Callable[[str], list[dict]]):
        self.repo = repo
        self.personas: dict = policy.get("personas", {})
        self._approved_claims = approved_claims

    def plans(self) -> list[str]:
        return sorted({p["plan"] for p in self.personas.values()})

    def resolve(self, user: dict | None) -> Viewer:
        if not user:
            return ANON
        claims = tuple(self._approved_claims(user["id"]))
        plans = self.repo.active_plans(user["id"])
        types = {c["claim_type"] for c in claims}
        active = frozenset(name for name, rule in self.personas.items()
                           if rule["plan"] in plans and types & set(rule["claim_types"]))
        is_admin = bool(user.get("is_admin"))
        if is_admin:  # admins see everything, so reviewers can check what customers see
            active = frozenset(self.personas)
        return Viewer(user=user, is_admin=is_admin, personas=active, claims=claims)

    def grant(self, user_id: str, plan: str, by: str) -> None:
        if plan not in self.plans():
            raise Invalid(f"unknown plan '{plan}'")
        self.repo.upsert(user_id, plan, "active", "admin", by)

    def revoke(self, user_id: str, plan: str) -> None:
        self.repo.remove(user_id, plan)

    def status(self, viewer: Viewer) -> dict:
        """What the user has, and what each persona still needs (used by the account page)."""
        if not viewer.user:
            return {"personas": [], "is_admin": False, "requirements": {}}
        plans = self.repo.active_plans(viewer.user_id)
        types = {c["claim_type"] for c in viewer.claims}
        req = {name: {"claim": bool(types & set(r["claim_types"])), "plan": r["plan"] in plans,
                      "claim_types": r["claim_types"]} for name, r in self.personas.items()}
        return {"personas": sorted(viewer.personas), "is_admin": viewer.is_admin, "requirements": req}

    @staticmethod
    def require_premium(viewer: Viewer, persona: str | None = None) -> None:
        if viewer.is_admin:
            return
        if persona and persona not in viewer.personas:
            raise Forbidden(f"requires a verified {persona} plan", code="premium_required")
        if not viewer.personas:
            raise Forbidden("requires a verified premium plan", code="premium_required")
