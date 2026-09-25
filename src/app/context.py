"""Composition root: the one place where modules are wired together.

Modules never import each other's repos. They get their collaborators here as small
callables or services, and they react to each other through the event bus.
"""
from __future__ import annotations

import polars as pl

# importing an implementation module registers it in its Registry
import src.app.community.rules  # noqa: F401
import src.app.fan.ratings  # noqa: F401
import src.app.fan.scout  # noqa: F401
import src.app.identity.builtin_jwt  # noqa: F401
import src.app.valuation.revenue_multiple  # noqa: F401
import src.app.verification.storage  # noqa: F401
from src.app.community.repo import CommunityRepo
from src.app.community.rules import promotion_rules
from src.app.community.service import CommunityService
from src.app.core.config import Policy, Settings
from src.app.core.db import create_all, make_engine
from src.app.core.errors import NotFound
from src.app.core.events import CLAIM_APPROVED, CLAIM_REVOKED, TITLE_ENTERED_RISING, EventBus
from src.app.entitlement.repo import GrantRepo
from src.app.entitlement.service import EntitlementService, Viewer, owns_title
from src.app.fan.ratings import rating_aggregators
from src.app.fan.repo import FanRepo
from src.app.fan.scout import scout_rules
from src.app.fan.service import FanService
from src.app.identity.provider import auth_providers
from src.app.identity.repo import UserRepo
from src.app.identity.service import IdentityService
from src.app.kpi.projector import KpiProjector
from src.app.market.service import MarketService
from src.app.market.warehouse import Warehouse
from src.app.valuation.base import valuation_models
from src.app.verification.repo import ClaimRepo
from src.app.verification.service import VerificationService
from src.app.verification.storage import doc_storages


class AppContext:
    def __init__(self, settings: Settings):
        self.settings = s = settings
        self.policy = p = Policy(s.policy_dir)
        self.engine = make_engine(s.app_db_url)
        create_all(self.engine)
        self.bus = EventBus()

        provider = auth_providers.create(p.app("identity", "provider"), secret=s.jwt_secret, ttl_minutes=s.jwt_ttl_minutes)
        self.identity = IdentityService(UserRepo(self.engine), provider)
        self.market = MarketService(Warehouse(s.warehouse_path), p.app("market", default={}), p.app("readiness", default={}))
        self.kpi = KpiProjector(p.load("kpis"))

        vcfg = p.app("verification", default={})
        self.verification = VerificationService(
            ClaimRepo(self.engine), doc_storages.create(vcfg.get("storage", "local_fs"), root=s.doc_storage_dir),
            self.bus, vcfg, entity_exists=self._entity_name)
        self.entitlement = EntitlementService(GrantRepo(self.engine), p.load("entitlements"),
                                              self.verification.approved_claims)

        ccfg = p.app("community", default={})
        self.community = CommunityService(
            CommunityRepo(self.engine),
            promotion_rules.create(ccfg.get("promotion_rule", "threshold"), min_up=ccfg.get("concept_min_up", 10),
                                   min_ratio=ccfg.get("concept_min_ratio", 0.8)),
            ccfg, s.ip_hash_salt, title_lookup=self.title_or_none, genre_exists=self._genre_exists,
            badge=lambda v, t: owns_title(v.claims, t), viewer_for=self.viewer_for, handle_for=self.handle_for)

        fcfg = p.app("fan", default={})
        self.fan = FanService(
            FanRepo(self.engine),
            rating_aggregators.create(fcfg.get("rating_aggregator", "bayesian"), prior_mean=fcfg.get("rating_prior_mean", 7.0),
                                      prior_weight=fcfg.get("rating_prior_weight", 20)),
            scout_rules.create(fcfg.get("scout_rule", "lead_time"), points_per_day=fcfg.get("scout_points_per_day", 3),
                               max_points=fcfg.get("scout_max_points", 500)),
            fcfg, title_exists=self._title_exists, is_owner=self.is_owner, handle_for=self.handle_for)

        vm = p.app("valuation", default={})
        self.valuation = valuation_models.create(vm.get("model", "revenue_multiple"),
                                                 base_multiple=vm.get("base_multiple"), adjustment=vm.get("adjustment"))

        # cross-module reactions
        refresh = lambda payload: self.fan.refresh_owner_flags(self.viewer_for(payload["user_id"]))  # noqa: E731
        self.bus.subscribe(CLAIM_APPROVED, refresh)
        self.bus.subscribe(CLAIM_REVOKED, refresh)
        self.bus.subscribe(TITLE_ENTERED_RISING, self.fan.on_title_rising)

    # ---- small adapters handed to modules ----
    def viewer_for(self, user_id: str) -> Viewer:
        return self.entitlement.resolve(self.identity.get(user_id))

    def handle_for(self, user_id: str) -> str | None:
        u = self.identity.get(user_id)
        return u["handle"] if u else None

    def title_or_none(self, comic_id: str) -> dict | None:
        try:
            return self.market.title(comic_id)
        except NotFound:
            return None

    def _title_exists(self, comic_id: str) -> bool:
        return self.market.title_exists(comic_id)

    def is_owner(self, v: Viewer, comic_id: str) -> bool:
        t = self.title_or_none(comic_id)
        return bool(t) and owns_title(v.claims, t)

    def _genre_exists(self, name: str) -> bool:
        return not self.market.universe().filter(pl.col("genre_parent") == name).is_empty()

    def _entity_name(self, claim_type: str, ref: str) -> str | None:
        if claim_type == "title":
            t = self.title_or_none(ref)
            return t["title"] if t else None
        col = {"author": "author", "publisher": "publisher"}.get(claim_type)
        if not col:
            return None
        hit = self.market.universe().filter(pl.col(col).str.to_lowercase() == ref.lower())
        return hit[col][0] if not hit.is_empty() else None
