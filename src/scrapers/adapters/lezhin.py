"""Lezhin adapter — client-rendered ranking (React, ``lzCard*`` components).

Lezhin's ranking is a React app: the requests path 404s and the initial HTML
has no data, but a hydrated Playwright snapshot exposes clean, stably-classed
card nodes. Each ``/comic/<slug>`` card carries its own title / rank / author /
genre / episode nodes (``.lzCardTitle`` etc.), so a per-card parse is far more
robust than scraping the flattened anchor text. Note the site redirects
``lezhin.com`` → ``lezhinus.com`` for the English catalog.
"""
from __future__ import annotations

import re
from datetime import datetime

from src.pipelines.schema_contract import ComicRecord, clean_metric
from src.scrapers.adapters.base import BaseAdapter, register

_COMIC = re.compile(r"/comic/([A-Za-z0-9_]+)")


@register
class LezhinAdapter(BaseAdapter):
    source = "lezhin"
    content_type = "comic"
    base_url = "https://www.lezhinus.com"

    def parse(self, html, *, source_file, scraped_at):
        soup = self.make_soup(html)
        out: list[ComicRecord] = []
        seen: set[str] = set()
        rank = 0
        for a in soup.find_all("a", href=_COMIC.search):
            title_el = a.select_one(".lzCardTitle")
            if not title_el:
                continue  # only ranking cards carry a title node (skip promo links)
            title = title_el.get_text(" ", strip=True)
            if not title:
                continue
            nid = _COMIC.search(a["href"]).group(1)
            if nid in seen:
                continue
            seen.add(nid)
            rank += 1

            metas = [e.get_text(" ", strip=True) for e in a.select(".lzCardMeta")]
            author = metas[0] if len(metas) >= 1 else None
            genre = metas[1] if len(metas) >= 2 else None
            episodes = None
            for mt in metas:
                em = re.search(r"(\d+)\s*Eps", mt, re.IGNORECASE)
                if em:
                    episodes = int(em.group(1))
                    break

            rk_el = a.select_one(".lzCardRanking")
            rk = clean_metric(rk_el.get_text()) if rk_el else 0

            img = a.find("img")
            cover = img.get("src") if img and (img.get("src") or "").startswith("http") else None
            href = a["href"]
            url = href if href.startswith("http") else self.base_url + href

            out.append(ComicRecord(
                comic_id=self.comic_id(nid), source=self.source, platform_native_id=nid,
                title=title, author=author, genre=genre, url=url,
                rank=rk or rank, primary_metric=0, metric_type="unknown",
                episode_count=episodes, cover_url=cover,
                content_type=self.content_type,
                scraped_at=scraped_at, source_file=source_file,
            ))
        return out
