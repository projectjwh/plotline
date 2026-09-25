"""Composition root: the one place where modules are wired together.

Modules never import each other's repos. They get their collaborators here as small
callables or services, and they react to each other through the event bus.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import polars as pl

# importing an implementation module registers it in its Registry
import src.app.community.rules  # noqa: F401
import src.app.fan.ratings  # noqa: F401
import src.app.fan.scout  # noqa: F401
import src.app.identity.builtin_jwt  # noqa: F401
import src.app.identity.email  # noqa: F401
import src.app.valuation.revenue_multiple  # noqa: F401
import src.app.verification.storage  # noqa: F401
import src.app.core.blobstore  # noqa: F401
import src.app.embeds.service  # noqa: F401
from src.app.community.repo import CommunityRepo
from src.app.community.rules import promotion_rules
from src.app.community.service import CommunityService
from src.app.core.blobstore import blob_stores
from src.app.core.config import Policy, Settings
from src.app.embeds.service import EmbedService, fetchers
from src.app.media.service import MediaService
from src.app.core.db import create_all, make_engine
from src.app.core.errors import NotFound
from src.app.core.events import CLAIM_APPROVED, CLAIM_REVOKED, TITLE_ENTERED_RISING, EventBus
from src.app.entitlement.repo import GrantRepo
from src.app.entitlement.service import EntitlementService, Viewer, owns_title
from src.app.fan.ratings import rating_aggregators
from src.app.fan.repo import FanRepo
from src.app.fan.scout import scout_rules
from src.app.fan.service import FanService
from src.app.feed.service import FeedService
from src.app.identity.email import email_senders
from src.app.identity.provider import auth_providers
from src.app.identity.repo import UserRepo
from src.app.identity.service import IdentityService
from src.app.kpi.projector import KpiProjector
from src.app.market.service import MarketService
from src.app.market.warehouse import Warehouse, ensure_warehouse
from src.app.valuation.base import valuation_models
from src.app.verification.repo import ClaimRepo
from src.app.verification.service import VerificationService
from src.app.verification.storage import doc_storages


class AppContext:
    def __init__(self, settings: Settings):
        self.settings = s = settings
        self.policy = p = Policy(s.policy_dir)
        self.engine = make_engine(s.app_db_url)
        if s.env != "prod":          # prod schema comes from `alembic upgrade head` (Fly release command)
            create_all(self.engine)
        self.bus = EventBus()

        provider = auth_providers.create(p.app("identity", "provider"), secret=s.jwt_secret, ttl_minutes=s.jwt_ttl_minutes)
        icfg = p.app("identity", default={})
        sender = os.environ.get("PLOTLINE_EMAIL_SENDER") or icfg.get("email_sender", "console")
        if s.env == "prod" and sender == "console":
            raise RuntimeError("prod needs a real email sender: set PLOTLINE_EMAIL_SENDER=resend and RESEND_API_KEY")
        self.mailer = email_senders.create(sender, api_key=s.resend_api_key, sender=s.email_from)
        self.identity = IdentityService(UserRepo(self.engine), provider, self.mailer, icfg, s.app_base_url)
        ensure_warehouse(s.warehouse_path, s.warehouse_url)
        self.market = MarketService(Warehouse(s.warehouse_path), p.app("market", default={}), p.app("readiness", default={}))
        self.kpi = KpiProjector(p.load("kpis"))

        # private object storage for uploads: local folder in dev/tests, R2 in prod (D-031)
        store_name = os.environ.get("PLOTLINE_BLOB_STORE") or p.app("storage", "blobs", default="local")
        if s.env == "prod" and store_name == "local":
            raise RuntimeError("prod needs PLOTLINE_BLOB_STORE=r2 (and R2_* env) for uploads")
        self.blobs = blob_stores.create(store_name, root=s.doc_storage_dir)
        vcfg = p.app("verification", default={})
        self.verification = VerificationService(
            ClaimRepo(self.engine), doc_storages.create(vcfg.get("storage", "blob"), store=self.blobs, root=s.doc_storage_dir),
            self.bus, vcfg, entity_exists=self._entity_name)
        self.entitlement = EntitlementService(GrantRepo(self.engine), p.load("entitlements"),
                                              self.verification.approved_claims)

        ccfg = p.app("community", default={})
        self.media = MediaService(self.engine, self.blobs, ccfg)
        self.embeds = EmbedService(self.engine, fetchers.create(ccfg.get("embed_fetcher", "urllib")), ccfg)
        self.community = CommunityService(
            CommunityRepo(self.engine),
            promotion_rules.create(ccfg.get("promotion_rule", "threshold"), min_up=ccfg.get("concept_min_up", 10),
                                   min_ratio=ccfg.get("concept_min_ratio", 0.8)),
            ccfg, s.ip_hash_salt, title_lookup=self.title_or_none, genre_exists=self._genre_exists,
            badge=lambda v, t: owns_title(v.claims, t), viewer_for=self.viewer_for, handle_for=self.handle_for,
            attach_media=self.media.attachable, link_previews=self.embeds.cached)

        fcfg = p.app("fan", default={})
        self.fan = FanService(
            FanRepo(self.engine),
            rating_aggregators.create(fcfg.get("rating_aggregator", "bayesian"), prior_mean=fcfg.get("rating_prior_mean", 7.0),
                                      prior_weight=fcfg.get("rating_prior_weight", 20)),
            scout_rules.create(fcfg.get("scout_rule", "lead_time"), points_per_day=fcfg.get("scout_points_per_day", 3),
                               max_points=fcfg.get("scout_max_points", 500)),
            fcfg, title_exists=self._title_exists, is_owner=self.is_owner, handle_for=self.handle_for)

        self.feed = FeedService(self._feed_sources(p.app("feed", default={})), self.fan.follows_of,
                                p.app("feed", default={}))

        vm = p.app("valuation", default={})
        self.valuation = valuation_models.create(vm.get("model", "revenue_multiple"),
                                                 base_multiple=vm.get("base_multiple"), adjustment=vm.get("adjustment"))

        # cross-module reactions
        refresh = lambda payload: self.fan.refresh_owner_flags(self.viewer_for(payload["user_id"]))  # noqa: E731
        self.bus.subscribe(CLAIM_APPROVED, refresh)
        self.bus.subscribe(CLAIM_REVOKED, refresh)
        self.bus.subscribe(TITLE_ENTERED_RISING, self.fan.on_title_rising)

    def _feed_sources(self, cfg: dict) -> dict:
        """Feed sources by name (D-033). ``feed.sources`` in app.yaml picks which ones run.

        Posts are windowed from now. Market events are windowed from the warehouse's
        latest crawl date, so a late refresh does not empty the feed.
        """
        listing_days = self.policy.app("market", "listing_window_days", default=30)
        window, limit = timedelta(days=cfg.get("window_days", 14)), cfg.get("posts_limit", 200)

        def market_since() -> str:
            as_of = self.market.as_of()
            return (as_of - window).isoformat() if as_of else "9999"

        available = {
            "posts": lambda f, since, lang: [
                {"id": f"post:{p['id']}", "kind": "post", "at": p["created_at"], "post": p}
                for p in self.community.feed_posts(sorted(f.titles), since, lang, limit)],
            "rank_moves": lambda f, since, lang: [
                {"id": f"move:{m['title']['comic_id']}:{m['at'][:10]}", "kind": "rank_move", **m}
                for m in self.market.rank_moves(f.titles) if m["at"] and m["at"] >= market_since()],
            "new_titles": lambda f, since, lang: [
                {"id": f"listing:{n['title']['comic_id']}", "kind": "new_title", **n}
                for n in self.market.new_titles_by(f.authors, f.publishers, listing_days)
                if n["at"] and n["at"] >= market_since()],
            "episodes": lambda f, since, lang: [
                {"id": f"episode:{e['title']['comic_id']}:{e['episode_no']}", "kind": "episode", **e}
                for e in self.market.episodes(f.titles, date.fromisoformat(market_since()[:10]))
                if market_since() != "9999"],
        }
        names = cfg.get("sources", list(available))
        unknown = set(names) - set(available)
        if unknown:
            raise RuntimeError(f"unknown feed sources in app.yaml: {sorted(unknown)}")
        return {n: available[n] for n in names}

    def readiness(self) -> dict:
        """What /ready reports: can we reach the app DB, and is the warehouse readable?"""
        try:
            with self.engine.connect() as c:
                c.exec_driver_sql("SELECT 1")
            db = True
        except Exception:
            db = False
        return {"app_db": db, "warehouse": self.market.wh.ready()}

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
