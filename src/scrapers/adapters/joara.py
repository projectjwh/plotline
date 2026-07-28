"""Joara adapter — Korean web-novel ranking (client-rendered ``li[data-idx]``).

Joara's ranking renders as ``<li data-idx="N">`` cards after hydration; the book
links are JS-driven (``href="/"``), so the stable identifier is the numeric id
embedded in the cover CDN url (``cf-image.joara.com/literature_file/<id>``) and
the clean title is that cover ``img[alt]``. ``data-idx`` gives the rank and the
card text carries the genre badge + episode count (``N화``).
"""
from __future__ import annotations

import re
from datetime import datetime

from src.pipelines.schema_contract import ComicRecord
from src.scrapers.adapters.base import BaseAdapter, register

_LIT = re.compile(r"literature_file/(\d+)")
_EPS = re.compile(r"(\d+)\s*화")                    # "22화" = 22 episodes
# joara's ranking cards carry a genre *badge* (BL / 로판 / 판타지 / 로맨스 / 패러디);
# match it explicitly instead of grabbing "the first token", which was picking
# up episode-count tokens like "50화무료". Anything not on this list -> None,
# so genre is filled by the cross-source verification layer rather than guessed.
_GENRE_BADGE = re.compile(r"(BL|GL|로판|로맨스|판타지|무협|패러디|현판|라이트노벨|드라마|미스터리)")


@register
class JoaraAdapter(BaseAdapter):
    source = "joara"
    content_type = "novel"
    base_url = "https://www.joara.com"

    def parse(self, html, *, source_file, scraped_at):
        soup = self.make_soup(html)
        out: list[ComicRecord] = []
        seen: set[str] = set()
        for card in soup.select("li[data-idx]"):
            nid = title = cover = None
            for im in card.find_all("img"):
                mm = _LIT.search(im.get("src") or "")
                if mm:
                    nid = mm.group(1)
                    title = (im.get("alt") or "").strip() or None
                    src = im.get("src") or ""
                    cover = src if src.startswith("http") else None
                    break
            if not nid or not title or nid in seen:
                continue
            seen.add(nid)

            try:
                rank = int(card.get("data-idx"))
            except (TypeError, ValueError):
                rank = None

            txt = card.get_text(" ", strip=True)
            ep = _EPS.search(txt)
            chapters = int(ep.group(1)) if ep else None
            gm = _GENRE_BADGE.search(txt)
            genre = gm.group(1) if gm else None   # only a recognised badge; else None

            out.append(ComicRecord(
                comic_id=self.comic_id(nid), source=self.source, platform_native_id=nid,
                title=title, genre=genre, url=None, rank=rank,
                primary_metric=0, metric_type="unknown",
                chapter_count=chapters, cover_url=cover,
                content_type=self.content_type,
                scraped_at=scraped_at, source_file=source_file,
            ))
        return out
