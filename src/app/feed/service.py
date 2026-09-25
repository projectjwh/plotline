"""Personal feed for signed-in fans (D-033).

The feed is computed when it is read (fan-out on read). There is no feed table: each
source turns what the user follows into dated items, and the service merges them
newest first and pages with an opaque cursor. That keeps the feed correct after
unfollows and deletions, and it is cheap at the current scale (one user's follows,
a 14-day window). A stored fan-out can replace it later behind the same endpoint.

Sources are plain callables, wired in ``context.py`` and switched on in
``config/policy/app.yaml`` (``feed.sources``):

* ``posts``      new posts in the fanboards of followed titles
* ``rank_moves`` latest rank change of followed titles (with the ``rising`` flag)
* ``new_titles`` new listings by followed authors and publishers
* ``episodes``   new episodes of followed titles (warehouse ``fact_episode.upload_date``)
"""
from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from src.app.core.db import now
from src.app.core.errors import Invalid


@dataclass
class Follows:
    titles: set[str]
    authors: set[str]
    publishers: set[str]

    @classmethod
    def from_rows(cls, rows: list[dict]) -> "Follows":
        pick = lambda t: {r["target_ref"] for r in rows if r["target_type"] == t}  # noqa: E731
        return cls(pick("title"), pick("author"), pick("publisher"))


# a source gets (follows, since, lang) and returns items with at least "id", "kind" and "at" (ISO string)
Source = Callable[[Follows, datetime, "str | None"], list[dict]]


def encode_cursor(item: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps([item["at"], item["id"]]).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        at, id_ = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if not isinstance(at, str) or not isinstance(id_, str):
            raise ValueError
        return at, id_
    except (ValueError, binascii.Error, TypeError):
        raise Invalid("bad cursor", code="bad_cursor") from None


class FeedService:
    def __init__(self, sources: dict[str, Source], follows_for: Callable[[str], list[dict]], cfg: dict):
        self.sources, self.follows_for, self.cfg = sources, follows_for, cfg

    def feed(self, user_id: str, *, cursor: str | None = None, limit: int = 30, lang: str | None = None,
             kinds: set[str] | None = None) -> dict:
        f = Follows.from_rows(self.follows_for(user_id))
        since = now() - timedelta(days=self.cfg.get("window_days", 14))
        items: list[dict] = []
        for name, src in self.sources.items():
            if kinds and name not in kinds:
                continue
            items.extend(i for i in src(f, since, lang) if i.get("at"))
        # newest first; the id breaks ties so paging is stable
        items.sort(key=lambda i: (i["at"], i["id"]), reverse=True)
        if cursor:
            c = decode_cursor(cursor)
            items = [i for i in items if (i["at"], i["id"]) < c]
        limit = max(1, min(limit, self.cfg.get("max_page", 50)))
        page = items[:limit]
        return {"items": page, "next_cursor": encode_cursor(page[-1]) if len(items) > limit else None,
                "following": {"titles": len(f.titles), "authors": len(f.authors), "publishers": len(f.publishers)},
                "window_days": self.cfg.get("window_days", 14)}
