"""Canonical genre taxonomy.

Platform genre labels are a mess: Korean (BL, 로판, 무협, 현판, 패러디…), webfiction
abbreviations (LitRPG, GameLit, Isekai), format words (Graphic Novel) and even
character tags (Male Lead). This normalises every raw label into a 2-level
hierarchy — an English **subgenre** mapped to a **parent** "larger genre" — so
charts can show broad buckets that drill down into subgenres.

``normalize_genre(raw) -> (subgenre_en, parent)``. Unknown labels title-case
through to parent "Other" rather than being dropped, so nothing is lost.
"""
from __future__ import annotations

# raw label (lower-cased, whitespace-collapsed) -> (English subgenre, parent)
_MAP: dict[str, tuple[str, str]] = {
    # --- Korean ---
    "bl": ("Boys' Love", "Romance"),
    "gl": ("Girls' Love", "Romance"),
    "로판": ("Romance Fantasy", "Romance"),
    "로맨스": ("Romance", "Romance"),
    "판타지": ("Fantasy", "Fantasy"),
    "현판": ("Modern Fantasy", "Fantasy"),
    "무협": ("Wuxia", "Action"),
    "패러디": ("Parody", "Comedy"),
    "라이트노벨": ("Light Novel", "Fantasy"),
    "드라마": ("Drama", "Drama"),
    "미스터리": ("Mystery", "Thriller"),
    "스포츠": ("Sports", "Sports"),
    "액션": ("Action", "Action"),
    "일상": ("Slice of Life", "Slice of Life"),
    # --- English / abbreviations / tags ---
    "romance": ("Romance", "Romance"),
    "heartwarming": ("Heartwarming", "Romance"),
    "fantasy": ("Fantasy", "Fantasy"),
    "urban fantasy": ("Urban Fantasy", "Fantasy"),
    "urban": ("Urban Fantasy", "Fantasy"),
    "eastern": ("Eastern Fantasy", "Fantasy"),
    "portal fantasy / isekai": ("Isekai", "Fantasy"),
    "isekai": ("Isekai", "Fantasy"),
    "reincarnation": ("Reincarnation", "Fantasy"),
    "cultivation": ("Cultivation", "Fantasy"),
    "kingdom building": ("Kingdom Building", "Fantasy"),
    "ruling class": ("Kingdom Building", "Fantasy"),
    "litrpg": ("LitRPG", "Fantasy"),
    "gamelit": ("GameLit", "Fantasy"),
    "progression": ("Progression", "Fantasy"),
    "action": ("Action", "Action"),
    "wuxia": ("Wuxia", "Action"),
    "war and military": ("War & Military", "Action"),
    "superhero": ("Superhero", "Action"),
    "super heroes": ("Superhero", "Action"),
    "strategy": ("Strategy", "Action"),
    "sci-fi": ("Science Fiction", "Science Fiction"),
    "sf/fantasy": ("Science Fantasy", "Science Fiction"),
    "space opera": ("Space Opera", "Science Fiction"),
    "time loop": ("Time Loop", "Science Fiction"),
    "time travel": ("Time Travel", "Science Fiction"),
    "virtual reality": ("Virtual Reality", "Science Fiction"),
    "games": ("Gaming", "Science Fiction"),
    "drama": ("Drama", "Drama"),
    "comedy": ("Comedy", "Comedy"),
    "parody": ("Parody", "Comedy"),
    "thriller": ("Thriller", "Thriller"),
    "mystery": ("Mystery", "Thriller"),
    "crime/mystery": ("Crime & Mystery", "Thriller"),
    "psychological": ("Psychological", "Thriller"),
    "horror": ("Horror", "Horror"),
    "slice of life": ("Slice of Life", "Slice of Life"),
    "informative": ("Informative", "Slice of Life"),
    "sports": ("Sports", "Sports"),
    "historical": ("Historical", "Historical"),
    "history": ("Historical", "Historical"),
    "supernatural": ("Supernatural", "Supernatural"),
    # formats / non-genre character tags -> Other
    "graphic novel": ("Graphic Novel", "Other"),
    "general": ("General", "Other"),
    "male lead": ("Male Lead", "Other"),
    "female lead": ("Female Lead", "Other"),
    "multiple lead characters": ("Ensemble Cast", "Other"),
    "anti-hero lead": ("Anti-Hero", "Other"),
}

PARENTS = ["Romance", "Fantasy", "Action", "Science Fiction", "Drama", "Comedy",
           "Thriller", "Horror", "Slice of Life", "Sports", "Historical",
           "Supernatural", "Other"]


def normalize_genre(raw: str | None) -> tuple[str | None, str | None]:
    """(subgenre_english, parent). Unknown -> (Title Case, 'Other')."""
    if not raw:
        return (None, None)
    key = " ".join(str(raw).split()).lower()
    if key in _MAP:
        return _MAP[key]
    return (" ".join(str(raw).split()).title(), "Other")
