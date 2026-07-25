"""Href-anchor listing adapters.

On real Bronze snapshots each title surfaces through several anchors that share
the same native id (a cover-image anchor carrying ``img[alt]``, a title anchor,
a metric anchor). So the robust algorithm is: collect every anchor whose href
matches the platform's stable pattern, **group by native id, and merge** the
best title / rank / metric across the group. This tolerates unstable CSS build
hashes (Chakra ``css-*``, ridibooks ``fig-*``) because it keys off hrefs, not
classes.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional

from src.pipelines.schema_contract import ComicRecord, clean_metric
from src.scrapers.adapters.base import BaseAdapter, iter_anchors, register

# Card texts / anchor texts that are chrome, not titles.
_NOISE = re.compile(
    r"^(up|new|hot|free with gold|latest\s?24hours|read more|detail|more|"
    r"\d+(hr|h|d|m)|wed|mon|tue|thu|fri|sat|sun|completed|ongoing)$",
    re.IGNORECASE,
)
_NUMERIC = re.compile(r"^\s*(up\s*)?[\d.,]+\s*[kmb]?\s*$", re.IGNORECASE)
_METRIC_TOKEN = re.compile(r"\b\d[\d.,]*\s*[KMB]\b", re.IGNORECASE)  # 28.7K, 1.2M
_TIME_TOKEN = re.compile(r"\b\d+\s?(hr|h|min|d)\b", re.IGNORECASE)   # 3hr, 24h
_LEAD_NOISE = re.compile(r"^(free with gold|up|new|latest\s?24hours)\s+", re.IGNORECASE)

# Title-candidate source priority (lower = more trustworthy).
ALT, TITLE_ATTR, ANCHOR_TEXT = 0, 1, 2


def _clean_cand(s: Optional[str]) -> Optional[str]:
    """Strip leading chrome ('Free with Gold ...') from a title candidate."""
    if not s:
        return None
    return _LEAD_NOISE.sub("", " ".join(s.split())).strip() or None


def _is_titleish(s: Optional[str]) -> bool:
    if not s:
        return False
    s = s.strip()
    if len(s) < 2 or _NUMERIC.match(s) or _NOISE.match(s):
        return False
    # Reject strings that are really metrics/timestamps leaking as text.
    return not _METRIC_TOKEN.search(s) and not _TIME_TOKEN.search(s)


def _slug_to_title(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title()


# --- detail-page helpers (shared across platforms) -------------------------------

def _og(soup, prop: str) -> Optional[str]:
    m = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    c = m.get("content") if m else None
    return " ".join(c.split()) if c else None


def _canonical(soup) -> Optional[str]:
    link = soup.find("link", rel="canonical")
    if link and link.get("href"):
        return link["href"]
    return _og(soup, "og:url")


def _detail_id(soup, href_re: re.Pattern, id_group: int) -> Optional[str]:
    """Native id of the title this detail page is about (from canonical/og:url)."""
    url = _canonical(soup) or ""
    m = href_re.search(url)
    return m.group(id_group) if m else None


_SITE_SUFFIX = re.compile(
    r"\s*(\||::|[-–—])\s*(tapas.*|line\s*webtoon.*|webtoon.*|wattpad.*|manga\s*plus.*|"
    r"globalcomix.*|webcomics.*|ridibooks.*)$", re.IGNORECASE)


def _clean_detail_title(t: Optional[str]) -> Optional[str]:
    if not t:
        return None
    t = re.sub(r"^\s*read\s+", "", t, flags=re.IGNORECASE)
    t = _SITE_SUFFIX.sub("", t)
    t = re.split(r"\s+\|\s+", t)[0]  # drop any remaining "| Site" tail
    return " ".join(t.split()).strip() or None


def _detail_title(soup) -> Optional[str]:
    t = _clean_detail_title(_og(soup, "og:title"))
    if t:
        return t
    h = soup.find("h1")
    return _clean_detail_title(h.get_text(" ", strip=True)) if h else None


_JUNK_TITLES = {"comics", "webcomics", "releases", "read more", "home", "profile", "browse"}


def _is_junk_title(t: str) -> bool:
    tl = t.strip().lower()
    return tl in _JUNK_TITLES or "publisher profile" in tl or tl.endswith(" profile")


def _pick_primary(views: int, likes: int, subs) -> tuple[int, str]:
    if views:
        return views, "views"
    if subs:
        return int(subs), "subscribers"
    if likes:
        return likes, "likes"
    return 0, "unknown"


_M = r"([\d.,]+\s*[kmbKMB]?)"  # a metric number w/ optional K/M/B suffix


def _text_metrics(soup, patterns: dict) -> dict:
    """Pull labelled numbers out of a detail page's visible text.

    ``patterns`` maps an output field -> list of regexes (first match wins);
    each regex must capture the number in group 1.
    """
    txt = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    out = {}
    for field, pats in patterns.items():
        for p in pats:
            m = re.search(p, txt, re.IGNORECASE)
            if m:
                out[field] = clean_metric(m.group(1))
                break
    syn = _og(soup, "og:description")
    if syn:
        out["synopsis"] = syn
    return out


class AnchorListAdapter(BaseAdapter):
    """Group-by-native-id anchor extractor. Subclasses tune the small hooks."""

    href_re: re.Pattern = re.compile(r"^$")   # regex over href
    id_group: int = 1                         # capture group holding the native id
    slug_group: Optional[int] = None          # capture group holding a title slug
    metric_type: str = "unknown"
    base_url: str = ""
    #: derive the title from the url slug when the DOM yields none.
    title_from_slug: bool = False

    # -- per-platform hooks (safe no-op defaults) --
    def clean_alt(self, alt: str) -> tuple[Optional[str], Optional[str]]:
        """Return (title, author) parsed from an ``img[alt]`` string."""
        return (alt, None)

    def extract_metric(self, card_texts: list[str]) -> tuple[int, str]:
        """Return (primary_metric, metric_type) from a card's text tokens."""
        for t in card_texts:
            if _METRIC_TOKEN.search(t):
                return self.clean(t), self.metric_type
        return 0, "unknown"

    def extract_extra(self, card_texts: list[str]) -> dict:
        """Return optional {genre, author, rating, ...} from a card."""
        return {}

    # -- detail-page enrichment --
    def detail_metrics(self, soup) -> dict:
        """Granular metrics from a single title's detail page. Override per platform.

        May return any of: views, likes, subscribers, rating, episode_count,
        author, genre, synopsis, tags.
        """
        return {}

    def parse_detail(self, html: str, *, source_file: str, scraped_at: datetime) -> list[ComicRecord]:
        soup = self.make_soup(html)
        nid = _detail_id(soup, self.href_re, self.id_group)
        title = _detail_title(soup)
        if not nid and not title:
            return []
        if not nid:
            nid = re.sub(r"\s+", "_", title).lower()
        if not title:
            title = None if nid.isdigit() else _slug_to_title(nid)
        if not title or _is_junk_title(title):
            return []  # generic/publisher-profile pages are not titles
        d = self.detail_metrics(soup)
        views = int(d.get("views") or 0)
        likes = int(d.get("likes") or 0)
        subs = d.get("subscribers")
        primary, mtype = _pick_primary(views, likes, subs)
        return [ComicRecord(
            comic_id=self.comic_id(nid), source=self.source, platform_native_id=nid,
            title=title, author=d.get("author"), genre=d.get("genre"),
            url=_canonical(soup), primary_metric=primary, metric_type=mtype,
            views=views, likes=likes, subscribers=subs, comments=d.get("comments"),
            rating=d.get("rating"), episode_count=d.get("episode_count"),
            chapter_count=d.get("chapter_count"), volume_count=d.get("volume_count"),
            synopsis=d.get("synopsis") or _og(soup, "og:description"),
            cover_url=_og(soup, "og:image"), publisher=d.get("publisher"),
            tags=d.get("tags") or [], content_type=self.content_type,
            scraped_at=scraped_at, source_file=source_file,
        )]

    # -- main --
    def parse(self, html: str, *, source_file: str, scraped_at: datetime) -> list[ComicRecord]:
        if "comic_detail" in os.path.basename(source_file):
            return self.parse_detail(html, source_file=source_file, scraped_at=scraped_at)
        return self._parse_listing(html, source_file=source_file, scraped_at=scraped_at)

    def _parse_listing(self, html: str, *, source_file: str, scraped_at: datetime) -> list[ComicRecord]:
        soup = self.make_soup(html)
        groups: dict[str, dict] = {}
        order: list[str] = []

        for a, m in iter_anchors(soup, self.href_re):
            nid = m.group(self.id_group)
            if nid not in groups:
                groups[nid] = {
                    "cands": [], "author": None, "cover": None,
                    "url": None, "card_texts": [], "slug": None,
                }
                order.append(nid)
            g = groups[nid]

            # url (first absolute one wins)
            if g["url"] is None:
                href = a["href"]
                g["url"] = href if href.startswith("http") else self.base_url + href
            # slug (explicit group, or the id itself when it is a slug)
            if g["slug"] is None:
                if self.slug_group:
                    g["slug"] = m.group(self.slug_group)
                elif self.title_from_slug:
                    g["slug"] = nid

            # cover art — first real image url (handles lazy-loaded data-src)
            img = a.find("img")
            if g["cover"] is None:
                ci = img or (a.find_parent(["li", "article", "div"]) or a).find("img")
                if ci:
                    for k in ("data-src", "data-original", "src"):
                        v = ci.get(k)
                        if v and v.startswith("http") and "data:" not in v:
                            g["cover"] = v
                            break
            # title candidates, tagged by source priority (alt > title-attr > text)
            if img and img.get("alt"):
                t, author = self.clean_alt(img["alt"].strip())
                t = _clean_cand(t)
                if _is_titleish(t):
                    g["cands"].append((ALT, t))
                if author and not g["author"]:
                    g["author"] = author
            ta = _clean_cand(a.get("title"))
            if _is_titleish(ta):
                g["cands"].append((TITLE_ATTR, ta))
            atext = _clean_cand(a.get_text(" ", strip=True))
            if _is_titleish(atext):
                g["cands"].append((ANCHOR_TEXT, atext))

            # card context (parent li/article/div) for metric + extras
            card = a.find_parent(["li", "article", "div"])
            if card and not g["card_texts"]:
                g["card_texts"] = [t.strip() for t in card.stripped_strings][:16]

        records: list[ComicRecord] = []
        for rank, nid in enumerate(order, start=1):
            g = groups[nid]
            # Best title: most trustworthy source first, then longest within it.
            title = None
            if g["cands"]:
                best_priority = min(p for p, _ in g["cands"])
                title = max((t for p, t in g["cands"] if p == best_priority), key=len)
            if not title and self.title_from_slug and g["slug"]:
                title = _slug_to_title(g["slug"])
            if not title:
                continue  # a title-less row is not useful; skip

            metric, mtype = self.extract_metric(g["card_texts"])
            extra = self.extract_extra(g["card_texts"])
            author = g["author"] or extra.get("author")

            records.append(ComicRecord(
                comic_id=self.comic_id(nid),
                source=self.source,
                platform_native_id=nid,
                title=title,
                author=author,
                genre=extra.get("genre"),
                url=g["url"],
                rank=rank,
                primary_metric=metric,
                metric_type=mtype,
                views=metric if mtype in ("views", "reads") else 0,
                likes=metric if mtype == "likes" else 0,
                rating=extra.get("rating"),
                cover_url=g["cover"],
                content_type=self.content_type,
                scraped_at=scraped_at,
                source_file=source_file,
            ))
        return records


# --- concrete platform adapters --------------------------------------------------

@register
class GlobalComixAdapter(AnchorListAdapter):
    source = "globalcomix"
    content_type = "comic"
    base_url = "https://globalcomix.com"
    href_re = re.compile(r"/c/([^/?#]+)")
    title_from_slug = True

    def clean_alt(self, alt):
        return (re.sub(r"^Cover image for\s+", "", alt).strip(), None)

    def detail_metrics(self, soup):
        # Per-comic total views. (The "Follow" count on GlobalComix is a
        # publisher-level metric, so it is deliberately not used here.)
        return _text_metrics(soup, {"views": [_M + r"\s+views?"]})


@register
class WattpadAdapter(AnchorListAdapter):
    source = "wattpad"
    content_type = "novel"
    base_url = "https://www.wattpad.com"
    href_re = re.compile(r"/story/(\d+)")
    metric_type = "reads"

    def clean_alt(self, alt):
        parts = re.split(r"\s+by\s+", alt, maxsplit=1)
        title = parts[0].strip()
        author = parts[1].strip() if len(parts) > 1 else None
        return (title, author)

    def detail_metrics(self, soup):
        # Wattpad: Reads -> views, Votes -> likes, Parts -> episode_count.
        return _text_metrics(soup, {
            "views": [r"Reads\s*" + _M, _M + r"\s*Reads"],
            "likes": [r"Votes\s*" + _M, _M + r"\s*Votes"],
            "episode_count": [r"Parts\s*(\d[\d,]*)", r"(\d[\d,]*)\s*Parts"],
        })


@register
class MangaPlusAdapter(AnchorListAdapter):
    source = "mangaplus"
    content_type = "comic"
    base_url = "https://mangaplus.shueisha.co.jp"
    href_re = re.compile(r"/titles/(\d+)")
    metric_type = "views"

    def clean_alt(self, alt):
        s = re.sub(r"^Read the Manga\s+", "", alt)
        s = re.sub(r"\s+for free!?$", "", s)
        parts = re.split(r"\s+by\s+", s, maxsplit=1)
        return (parts[0].strip(), parts[1].strip() if len(parts) > 1 else None)


@register
class WebComicsAppAdapter(AnchorListAdapter):
    source = "webcomics_app"
    content_type = "comic"
    base_url = "https://www.webcomicsapp.com"
    # url = /comic/{slug}/{hexid}: native id is the hex, title comes from the slug
    href_re = re.compile(r"/comic/([^/]+)/([0-9a-f]{6,})")
    id_group = 2
    slug_group = 1
    title_from_slug = True

    def detail_metrics(self, soup):
        return _text_metrics(soup, {
            "subscribers": [r"([\d,]+)\s*followers"],
            "likes": [r"([\d,]+)\s*likes?"],
        })


@register
class RidibooksAdapter(AnchorListAdapter):
    source = "ridibooks"
    content_type = "novel"
    base_url = "https://ridibooks.com"
    href_re = re.compile(r"/books/(\d+)")

    def extract_extra(self, card_texts):
        extra = {}
        for t in card_texts:
            if re.match(r"^\d\.\d$", t):        # rating like 5.0
                extra["rating"] = float(t)
            elif t.endswith("소설") or t.endswith("만화"):
                extra["genre"] = t
        return extra

    def detail_metrics(self, soup):
        d = {}
        m = re.search(r"(\d+)\s*권", soup.get_text(" "))  # Korean volume/book count
        if m:
            d["volume_count"] = int(m.group(1))
        return d


@register
class WebnovelAdapter(AnchorListAdapter):
    source = "webnovel"
    content_type = "novel"
    base_url = "https://www.webnovel.com"
    href_re = re.compile(r"/book/[^_/?#]+_(\d+)")

    def extract_extra(self, card_texts):
        extra = {}
        # card layout: [title, genre, rating, 'detail']
        for t in card_texts[1:]:
            if re.match(r"^\d\.\d+$", t):
                extra["rating"] = float(t)
            elif t.isalpha() and t.lower() not in ("detail",) and "genre" not in extra:
                extra["genre"] = t
        return extra

    def detail_metrics(self, soup):
        d = _text_metrics(soup, {"chapter_count": [r"([\d,]+)\s+Chapters?"]})
        m = re.search(r"Volume\s*(\d+)", soup.get_text(" "))
        if m:
            d["volume_count"] = int(m.group(1))
        return d


@register
class TapasAdapter(AnchorListAdapter):
    """Tapas listing anchors expose the series id + a popularity number, but the
    title renders separately; kept registered so it captures id/rank/metric and
    picks up titles when a snapshot includes them."""
    source = "tapas_io"
    content_type = "comic"
    base_url = "https://tapas.io"
    href_re = re.compile(r"/series/(\d+)")
    metric_type = "views"

    def detail_metrics(self, soup):
        # Tapas detail pages carry clean views / subscribers / likes + episode count.
        return _text_metrics(soup, {
            "views": [_M + r"\s+views"],
            "subscribers": [_M + r"\s+subscribers"],
            "likes": [_M + r"\s+likes"],
            "episode_count": [r"(\d[\d,]*)\s+episodes"],
        })
