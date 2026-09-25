"""Ownership and authority claims, reviewed by hand (spec §2 and §7)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from src.app.core.db import now
from src.app.core.errors import Conflict, Forbidden, Invalid, NotFound, Unauthorized
from src.app.core.events import CLAIM_APPROVED, CLAIM_REVOKED, EventBus
from src.app.entitlement.service import Viewer
from src.app.verification.repo import ClaimRepo
from src.app.verification.storage import DocStorage


def _public(c: dict, admin: bool = False) -> dict:
    out = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in c.items()
           if k not in ("doc_keys",) or admin}
    out["documents"] = len(c["doc_keys"])
    return out


class VerificationService:
    def __init__(self, repo: ClaimRepo, storage: DocStorage, bus: EventBus, cfg: dict, *,
                 entity_exists: Callable[[str, str], str | None]):
        """``entity_exists(claim_type, ref)`` returns the display name, or None if the entity is unknown."""
        self.repo, self.storage, self.bus, self.cfg = repo, storage, bus, cfg
        self.entity_exists = entity_exists

    def approved_claims(self, user_id: str) -> list[dict]:
        return self.repo.for_user(user_id, "approved")

    def submit(self, v: Viewer, claim_type: str, entity_ref: str, role: str | None,
               files: list[bytes], entity_name: str | None = None) -> dict:
        if not v.user_id:
            raise Unauthorized("sign in to submit a claim")
        if claim_type not in self.cfg.get("claim_types", []):
            raise Invalid(f"claim_type must be one of {self.cfg.get('claim_types')}")
        entity_ref = entity_ref.strip()
        if not entity_ref:
            raise Invalid("entity_ref is required")
        if claim_type == "investor_entity":
            name = (entity_name or entity_ref).strip()
        else:
            name = self.entity_exists(claim_type, entity_ref)
            if not name:
                raise NotFound(f"no listed {claim_type} matches '{entity_ref}'")
        if not files:
            raise Invalid("attach at least one document")
        if len(files) > self.cfg.get("max_files", 5):
            raise Invalid(f"at most {self.cfg.get('max_files', 5)} documents")
        limit = self.cfg.get("max_file_mb", 10) * 1024 * 1024
        if any(len(f) > limit for f in files):
            raise Invalid(f"each document must be at most {self.cfg.get('max_file_mb', 10)} MB")
        if self.repo.pending_duplicate(v.user_id, claim_type, entity_ref):
            raise Conflict("you already have a pending or approved claim for this entity")
        keys = []
        try:
            for f in files:
                keys.append(self.storage.put(f)[0])
        except Exception:
            for k in keys:  # don't leave orphans behind when one file is rejected
                self.storage.delete(k)
            raise
        c = self.repo.create(user_id=v.user_id, claim_type=claim_type, entity_ref=entity_ref, entity_name=name,
                             role=(role or "")[:120] or None, doc_keys=keys)
        return _public(c)

    def mine(self, v: Viewer) -> list[dict]:
        if not v.user_id:
            raise Unauthorized("sign in")
        return [_public(c) for c in self.repo.for_user(v.user_id)]

    def withdraw(self, v: Viewer, claim_id: str) -> dict:
        """The user withdraws a pending claim; its documents are deleted now (D-040)."""
        c = self.repo.get(claim_id)
        if not c or c["user_id"] != v.user_id:
            raise NotFound("claim not found")
        if c["status"] != "pending" or not self.repo.withdraw(claim_id):
            raise Conflict("only a pending claim can be withdrawn")
        self._delete_docs(c)
        return _public(self.repo.get(claim_id))

    # ---------- retention (D-040) ----------
    def _delete_docs(self, c: dict) -> None:
        for k in c["doc_keys"]:
            self.storage.delete(k)   # deleting a missing key is a no-op, so a retried purge is safe
        self.repo.mark_purged(c["id"])

    def purge_documents(self, at: datetime | None = None) -> int:
        """Delete the documents of claims decided more than ``retention_days_after_decision`` ago.

        The claim row (who, what, decision, reviewer, note, dates) is kept as the record.
        """
        days = self.cfg.get("retention_days_after_decision", 90)
        due = self.repo.due_for_purge((at or now()) - timedelta(days=days))
        for c in due:
            self._delete_docs(c)
        return len(due)

    # ---------- admin ----------
    def _admin(self, v: Viewer) -> None:
        if not v.is_admin:
            raise Forbidden("admins only")

    def queue(self, v: Viewer, status: str = "pending") -> list[dict]:
        self._admin(v)
        return [_public(c, admin=True) for c in self.repo.by_status(status)]

    def decide(self, v: Viewer, claim_id: str, decision: str, note: str | None) -> dict:
        self._admin(v)
        c = self.repo.get(claim_id)
        if not c:
            raise NotFound("claim not found")
        allowed = {"approve": ("pending", "approved"), "reject": ("pending", "rejected"),
                   "revoke": ("approved", "revoked")}
        if decision not in allowed:
            raise Invalid("decision must be approve, reject or revoke")
        need, new = allowed[decision]
        if c["status"] != need:
            raise Conflict(f"cannot {decision} a claim that is {c['status']}")
        if decision == "reject" and not (note or "").strip():
            raise Invalid("a rejection needs a note for the user")
        self.repo.set_status(claim_id, new, v.user_id, note)
        c = self.repo.get(claim_id)
        if new == "approved":
            self.bus.publish(CLAIM_APPROVED, {"user_id": c["user_id"], "claim": c})
        elif new == "revoked":
            self.bus.publish(CLAIM_REVOKED, {"user_id": c["user_id"], "claim": c})
        return _public(c, admin=True)

    def document(self, v: Viewer, claim_id: str, key: str) -> tuple[bytes, str]:
        self._admin(v)
        c = self.repo.get(claim_id)
        if not c or key not in c["doc_keys"]:
            raise NotFound("document not found")
        return self.storage.get(key)
