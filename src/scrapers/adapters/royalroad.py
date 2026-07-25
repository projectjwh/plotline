"""RoyalRoad adapter — server-rendered fiction lists (requests-friendly).

RoyalRoad's popular/active list is fully server-rendered and unusually rich:
each ``div.fiction-list-item`` already carries followers, total views, chapter
count, genre tags and a cover — so the *listing alone* yields near-complete
records without a detail crawl. (Playwright fails on RoyalRoad; the requests
``listing_fetch`` path feeds this adapter instead.)
"""
from __future__ import annotations

import os
import re
from datetime import datetime

from src.pipelines.schema_contract import ComicRecord
from src.scrapers.adapters.base import BaseAdapter, register

_FIC = re.compile(r"/fiction/(\d+)/([^/?#\"]+)")


def _num(text: str, label: str):
    m = re.search(r"([\d,]+)\s+" + label, text, re.IGNORECASE)
    return int(m.group(1).replace(",", "")) if m else None


@register
class RoyalRoadAdapter(BaseAdapter):
    source = "royalroad"
    content_type = "novel"

    def parse(self, html, *, source_file, scraped_at):
        soup = self.make_soup(html)
        out = []
        for rank, it in enumerate(soup.select("div.fiction-list-item"), start=1):
            a = it.select_one(".fiction-title a") or it.select_one("h2 a")
            if not a or not a.get("href"):
                continue
            m = _FIC.search(a["href"])
            if not m:
                continue
            nid = m.group(1)
            title = a.get_text(strip=True)
            if not title:
                continue
            img = it.find("img")
            cover = img.get("src") if img and (img.get("src") or "").startswith("http") else None
            tags = [t.get_text(strip=True) for t in it.select("a.fiction-tag")]
            txt = re.sub(r"\s+", " ", it.get_text(" ", strip=True))
            views = _num(txt, "Views")
            followers = _num(txt, "Followers")
            chapters = _num(txt, "Chapters")
            if views:
                primary, mtype = views, "views"
            elif followers:
                primary, mtype = followers, "subscribers"
            else:
                primary, mtype = 0, "unknown"
            out.append(ComicRecord(
                comic_id=self.comic_id(nid), source=self.source, platform_native_id=nid,
                title=title, genre=(tags[0] if tags else None), tags=tags[:20],
                url="https://www.royalroad.com" + a["href"], rank=rank,
                primary_metric=primary, metric_type=mtype,
                views=views or 0, subscribers=followers, chapter_count=chapters,
                cover_url=cover, content_type=self.content_type,
                scraped_at=scraped_at, source_file=source_file,
            ))
        return out
