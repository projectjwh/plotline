"""Adapter framework for platform-specific Bronze->record parsing.

Each platform registers a ``BaseAdapter`` subclass keyed by its ``source``
name (the Bronze folder name). The driver (``src/pipelines/parser.py``) routes
every Bronze HTML file to the matching adapter, so adding a platform is a small,
isolated unit of code instead of another branch in a monolithic parser.

Robustness principle learned from the real Bronze snapshots: platform CSS
classes are frequently unstable build hashes (Chakra ``css-*``, ridibooks
``fig-*``), but **href patterns are stable and carry the native id**
(``/series/322705``, ``/c/the-backwards-house``). Prefer href-pattern anchor
extraction over brittle class selectors.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable, Optional

from bs4 import BeautifulSoup

from src.pipelines.schema_contract import ComicRecord, clean_metric

__all__ = ["BaseAdapter", "register", "get_adapter", "ADAPTERS", "detect_block", "clean_metric"]


# --- registry --------------------------------------------------------------------

ADAPTERS: dict[str, "BaseAdapter"] = {}


def register(cls):
    """Class decorator: instantiate and register an adapter by its ``source``."""
    if not getattr(cls, "source", None):
        raise ValueError(f"{cls.__name__} must define a 'source'")
    ADAPTERS[cls.source] = cls()
    return cls


def get_adapter(source: str) -> Optional["BaseAdapter"]:
    return ADAPTERS.get(source)


# --- block / junk detection ------------------------------------------------------

_BLOCK_TITLES = re.compile(
    r"connect error|access denied|are you (a )?human|just a moment|"
    r"attention required|403 forbidden|captcha|robot check|blocked",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
# A rendered listing page should be substantial; anything tiny is a shell/error.
_MIN_HTML_BYTES = 20_000


def detect_block(html: str, *, min_bytes: int = _MIN_HTML_BYTES) -> Optional[str]:
    """Return a reason string if this HTML looks blocked/empty, else ``None``.

    This is what keeps the Webtoon "Connect Error" (4.7 KB) pages and
    un-rendered SPA shells out of Silver instead of parsing to nothing.

    Block markers are matched against the ``<title>`` (where interstitials
    announce themselves: "Just a moment…", "Attention Required", "403
    Forbidden") plus a comment/script-stripped head slice — so a benign string
    in a comment or analytics snippet (e.g. a "Blocked until consent" Google
    Tag Manager comment on a perfectly good page) no longer false-triggers.
    """
    if not html or len(html) < min_bytes:
        return f"too_small ({len(html) if html else 0}b < {min_bytes})"
    m = _TITLE_RE.search(html[:8000])
    title = " ".join(m.group(1).split()) if m else ""
    hit = _BLOCK_TITLES.search(title)
    if hit:
        return f"block_marker:{hit.group(0).lower()}"
    cleaned = _SCRIPT_STYLE_RE.sub(" ", _COMMENT_RE.sub(" ", html[:6000]))
    hit = _BLOCK_TITLES.search(cleaned[:4000])
    if hit:
        return f"block_marker:{hit.group(0).lower()}"
    return None


# --- adapter base ----------------------------------------------------------------

class BaseAdapter(ABC):
    source: str = ""
    content_type: str = "comic"
    #: Substrings marking a Bronze filename as a listing/ranking page.
    listing_markers: tuple[str, ...] = ("daily_schedule", "ranking", "listing")

    # -- helpers shared by concrete adapters --
    def make_soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    def comic_id(self, native_id: str) -> str:
        return f"{self.source}:{native_id}"

    def clean(self, text: object) -> int:
        return clean_metric(text)

    def is_listing(self, filename: str) -> bool:
        return any(m in filename for m in self.listing_markers)

    @abstractmethod
    def parse(
        self, html: str, *, source_file: str, scraped_at: datetime
    ) -> list[ComicRecord]:
        """Parse one Bronze HTML document into zero or more records."""
        raise NotImplementedError

    def parse_episodes(self, html: str, *, source_file: str, scraped_at: datetime) -> list[dict]:
        """Extract per-episode rows from a detail page (episode_no, date, likes,
        comments, views). Override per platform; default is none."""
        return []


# --- href-anchor extraction utilities (used by AnchorListAdapter) ----------------

def iter_anchors(soup: BeautifulSoup, href_re: re.Pattern) -> Iterable:
    """Yield (anchor, match) for every <a> whose href matches ``href_re``."""
    for a in soup.find_all("a", href=True):
        m = href_re.search(a["href"])
        if m:
            yield a, m
