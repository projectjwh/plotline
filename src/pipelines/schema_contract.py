"""Canonical Silver record contract.

Every acquisition adapter emits ``ComicRecord`` objects, and every Silver
parquet file conforms to ``SILVER_SCHEMA``. Centralising the schema here is
what lets many platform adapters produce one consistent, validated dataset
(previously each script re-declared its own ad-hoc shape).

The record deliberately keeps the legacy ``views`` / ``likes`` columns so the
existing Gold pipeline (``pipeline_updates.py``) keeps working, but adds
``primary_metric`` + ``metric_type`` so a listing's popularity number is
*labelled* rather than silently proxied into ``views``.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import polars as pl
from pydantic import BaseModel, Field, field_validator

# --- metric string normalisation -------------------------------------------------

_METRIC_RE = re.compile(r"(-?\d[\d,]*\.?\d*)\s*([BMK]?)", re.IGNORECASE)
_MULT = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def clean_metric(text: object) -> int:
    """Normalise a metric string to an int.

    Handles ``'1.2M'`` -> 1_200_000, ``'10,999'`` -> 10999, ``'315.6K'`` ->
    315_600, ``'UP 26.6K'`` -> 26_600, ``'3.1B'`` -> 3_100_000_000. Returns 0
    when no number can be found (never raises).
    """
    if text is None:
        return 0
    if isinstance(text, (int, float)):
        return int(text)
    m = _METRIC_RE.search(str(text).strip().upper())
    if not m:
        return 0
    num, suffix = m.group(1).replace(",", ""), m.group(2)
    try:
        return int(float(num) * _MULT[suffix])
    except (ValueError, KeyError):
        return 0


# --- the record ------------------------------------------------------------------

METRIC_TYPES = {"views", "likes", "subscribers", "rating", "reads", "unknown"}
CONTENT_TYPES = {"comic", "novel"}


class ComicRecord(BaseModel):
    """One title observed on one platform at one point in time."""

    comic_id: str                      # "{source}:{native_id}" (stable key)
    source: str
    platform_native_id: Optional[str] = None
    title: str
    author: Optional[str] = None
    genre: Optional[str] = None
    url: Optional[str] = None
    rank: Optional[int] = None

    # Explicit primary metric + what it actually is on this platform.
    primary_metric: int = 0
    metric_type: str = "unknown"

    # Legacy / typed metrics (kept for downstream Gold compatibility).
    views: int = 0
    likes: int = 0
    subscribers: Optional[int] = None
    comments: Optional[int] = None
    rating: Optional[float] = None
    # Content structure — the applicable unit per type: episodes (comics),
    # chapters (novels/manga), volumes/books (novels).
    episode_count: Optional[int] = None
    chapter_count: Optional[int] = None
    volume_count: Optional[int] = None

    # Text fields — captured now to unblock the news/NLP + semantic pillars.
    synopsis: Optional[str] = None
    tags: list[str] = Field(default_factory=list)

    # Cover art (real image URL, for display + painting-style analysis) + publisher/studio.
    cover_url: Optional[str] = None
    publisher: Optional[str] = None
    status: Optional[str] = None        # ongoing / completed / hiatus

    content_type: str = "comic"
    scraped_at: datetime
    source_file: Optional[str] = None

    @field_validator("title", "author", "genre", "synopsis")
    @classmethod
    def _strip(cls, v):
        if v is None:
            return v
        v = " ".join(str(v).split())
        return v or None

    @field_validator("metric_type")
    @classmethod
    def _metric_type(cls, v):
        return v if v in METRIC_TYPES else "unknown"

    @field_validator("content_type")
    @classmethod
    def _content_type(cls, v):
        return v if v in CONTENT_TYPES else "comic"


# --- Polars schema (fixed column order + dtypes for partitioned parquet) ---------

SILVER_SCHEMA: dict[str, pl.DataType] = {
    "comic_id": pl.String,
    "source": pl.String,
    "platform_native_id": pl.String,
    "title": pl.String,
    "author": pl.String,
    "genre": pl.String,
    "url": pl.String,
    "rank": pl.Int32,
    "primary_metric": pl.Int64,
    "metric_type": pl.String,
    "views": pl.Int64,
    "likes": pl.Int64,
    "subscribers": pl.Int64,
    "comments": pl.Int64,
    "rating": pl.Float64,
    "episode_count": pl.Int32,
    "chapter_count": pl.Int32,
    "volume_count": pl.Int32,
    "synopsis": pl.String,
    "tags": pl.List(pl.String),
    "cover_url": pl.String,
    "publisher": pl.String,
    "status": pl.String,
    "content_type": pl.String,
    "scraped_at": pl.Datetime("us"),
    "source_file": pl.String,
}


def records_to_frame(records: list[ComicRecord]) -> pl.DataFrame:
    """Build a Silver DataFrame with the canonical schema from validated records."""
    rows = [r.model_dump() for r in records]
    if not rows:
        return pl.DataFrame(schema=SILVER_SCHEMA)
    return pl.DataFrame(rows, schema=SILVER_SCHEMA)
