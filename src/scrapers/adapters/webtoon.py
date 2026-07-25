"""Webtoon adapter (plain-HTML, CSS-selector based).

Webtoon renders server-side HTML (no embedded JSON list), so this adapter uses
CSS selectors sourced from ``config.yaml`` — finally wiring the per-platform
``selectors:`` block that the old parser ignored. It ports the detail + listing
logic from the original ``parser.py`` and additionally captures synopsis / tags
(dropped before) to feed the downstream NLP / semantic pillars.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional

import yaml

from src.pipelines.schema_contract import ComicRecord
from src.scrapers.adapters.base import BaseAdapter, register

_CFG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "config.yaml",
)
with open(_CFG_PATH, encoding="utf-8") as _f:
    _SEL = yaml.safe_load(_f)["scraping"]["targets"]["webtoon_global"].get("selectors", {})


def _sel_text(node, selector: str) -> Optional[str]:
    if not selector:
        return None
    for css in selector.split(","):
        el = node.select_one(css.strip())
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return None


@register
class WebtoonAdapter(BaseAdapter):
    source = "webtoon_global"
    content_type = "comic"

    def _detail(self, soup, source_file, scraped_at) -> list[ComicRecord]:
        title = _sel_text(soup, "h1, .subj") or _sel_text(soup, _SEL.get("title", ".subj"))
        if not title:
            return []
        # Real Webtoon detail structure: ul.grade_area carries total views +
        # subscribers, each keyed by an .ico_* icon span.
        views = subscribers = 0
        rating = None
        ga = soup.select_one(".grade_area")
        if ga:
            for li in ga.find_all("li"):
                cls = " ".join(sp_cls for el in li.find_all(class_=True) for sp_cls in el.get("class", []))
                val = self.clean(li.get_text(" ", strip=True))
                if "ico_view" in cls and "ico_view2" not in cls:
                    views = val
                elif "ico_subscribe" in cls:
                    subscribers = val
                elif "ico_grade" in cls:
                    try:
                        rating = float(re.search(r"\d+(\.\d+)?", li.get_text()).group())
                    except (AttributeError, ValueError):
                        pass
        tags = [t.get_text(strip=True) for t in soup.select(".tag_lst .tag, .keyword")][:20]
        # Publication status from the schedule badge (.day_info): a completed series
        # reads "COMPLETED"/"완결"; anything with a weekday/UP schedule is ongoing.
        day = _sel_text(soup, ".day_info, .detail_day, .date_info")
        status = None
        if day:
            d = day.upper()
            status = "completed" if ("COMPLETED" in d or "완결" in day) else ("hiatus" if "HIATUS" in d else "ongoing")
        ogimg = soup.find("meta", property="og:image")
        cover = ogimg.get("content") if ogimg and ogimg.get("content") else None
        ep_nos = [int(m.group(1)) for li in soup.select("#_listUl li")
                  for m in [re.search(r"#(\d+)", (li.select_one(".tx") or li).get_text())] if m]
        ep_count = max(ep_nos) if ep_nos else None
        primary, mtype = (views, "views") if views else (subscribers, "subscribers")
        return [ComicRecord(
            comic_id=self.comic_id(re.sub(r"\s+", "_", title).lower()),
            source=self.source,
            title=title,
            author=_sel_text(soup, _SEL.get("author", ".author")),
            genre=_sel_text(soup, _SEL.get("genre", ".genre")),
            primary_metric=primary, metric_type=mtype,
            views=views, likes=0,
            subscribers=subscribers or None,
            rating=rating, cover_url=cover, episode_count=ep_count,
            synopsis=_sel_text(soup, _SEL.get("synopsis", ".summary, p.summary")),
            tags=tags, status=status,
            content_type=self.content_type,
            scraped_at=scraped_at, source_file=source_file,
        )]

    def _listing(self, soup, source_file, scraped_at) -> list[ComicRecord]:
        items = soup.select("ul.daily_card li, ul.card_lst li, ul.webtoon_list li")
        records = []
        for rank, item in enumerate(items, start=1):
            title = _sel_text(item, ".subj, .title, strong.title")
            if not title:
                continue
            genre = _sel_text(item, ".genre, .info_text .genre")
            metric = self.clean(_sel_text(item, ".grade_num, .view_count.type_like, .view_count"))
            # Capture the detail-page href so the detail crawler can enrich it.
            a = item.find("a", href=True)
            url = None
            if a:
                url = a["href"] if a["href"].startswith("http") else "https://www.webtoons.com" + a["href"]
            im = item.find("img")
            cover = None
            if im:
                for k in ("data-src", "src"):
                    v = im.get(k)
                    if v and v.startswith("http"):
                        cover = v
                        break
            records.append(ComicRecord(
                comic_id=self.comic_id(re.sub(r"\s+", "_", title).lower()),
                source=self.source,
                title=title, genre=genre, rank=rank, url=url,
                primary_metric=metric, metric_type="likes",
                likes=metric, cover_url=cover,
                content_type=self.content_type,
                scraped_at=scraped_at, source_file=source_file,
            ))
        return records

    def parse(self, html, *, source_file, scraped_at):
        soup = self.make_soup(html)
        filename = os.path.basename(source_file)
        if "comic_detail" in filename:
            return self._detail(soup, source_file, scraped_at)
        return self._listing(soup, source_file, scraped_at)

    def parse_episodes(self, html, *, source_file, scraped_at):
        """Per-episode rows from the detail page's episode list (#_listUl):
        episode number, upload date, and per-episode likes."""
        soup = self.make_soup(html)
        title = _sel_text(soup, "h1, .subj")
        if not title:
            return []
        cid = self.comic_id(re.sub(r"\s+", "_", title).lower())
        eps = []
        for li in soup.select("#_listUl li, ul._episodeList li"):
            subj = li.select_one(".subj")
            if not subj:
                continue
            tx = li.select_one(".tx")
            no = None
            if tx:
                m = re.search(r"#(\d+)", tx.get_text())
                no = int(m.group(1)) if m else None
            date = li.select_one(".date")
            like = li.select_one(".like_area, ._likeitArea, .like")
            eps.append({
                "comic_id": cid, "source": self.source, "episode_no": no,
                "episode_title": subj.get_text(strip=True),
                "upload_date": date.get_text(strip=True) if date else None,
                "likes": self.clean(like.get_text()) if like else 0,
                "views": 0, "comments": 0,
                "scraped_at": scraped_at, "source_file": source_file,
            })
        return eps
