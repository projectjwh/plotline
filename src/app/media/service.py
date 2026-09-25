"""Fanboard images (decision D-035).

Uploads are checked by magic bytes, then decoded and re-encoded with Pillow. The
re-encode drops EXIF/GPS and any other metadata, and caps the long edge. Only the
re-encoded file is stored, under a random key. Guest uploads are off by default
(``community.guest_images``) because moderation is manual (D-038).
"""
from __future__ import annotations

import io
import secrets
from datetime import timedelta

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import Column, DateTime, Integer, String, Table, func, insert, select, update
from sqlalchemy.engine import Engine

from src.app.core.blobstore import BlobStore
from src.app.core.db import metadata, new_id, now
from src.app.core.errors import Forbidden, Invalid, NotFound, RateLimited

media = Table(
    "media", metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_key", String(80), nullable=False, index=True),   # voter key: u:<id> | ip:<hash>
    Column("key", String(64), nullable=False),
    Column("mime", String(20), nullable=False),
    Column("width", Integer, nullable=False),
    Column("height", Integer, nullable=False),
    Column("bytes", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False, index=True),
    Column("removed_at", DateTime),
)

SIGNATURES = [(b"\xff\xd8\xff", "JPEG"), (b"\x89PNG\r\n\x1a\n", "PNG"), (b"GIF87a", "GIF"), (b"GIF89a", "GIF")]
OUT = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "GIF": ("image/gif", "gif"), "WEBP": ("image/webp", "webp")}
MAX_PIXELS = 40_000_000               # per frame
MAX_FRAMES = 200                      # animated GIF/WebP
MAX_TOTAL_PIXELS = 200_000_000        # all frames together
Image.MAX_IMAGE_PIXELS = MAX_PIXELS   # Pillow's own guard (warns above this, raises above 2×)


def sniff_image(data: bytes) -> str:
    for sig, fmt in SIGNATURES:
        if data.startswith(sig):
            return fmt
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    raise Invalid("images must be JPEG, PNG, WebP or GIF")


def reencode(data: bytes, max_edge: int) -> tuple[bytes, str, int, int]:
    """Decode and re-encode, dropping all metadata. Returns (bytes, format, width, height)."""
    fmt = sniff_image(data)
    try:
        img = Image.open(io.BytesIO(data))   # lazy: reads the header only
        w0, h0 = img.size
        frames_n = getattr(img, "n_frames", 1)
        # checked before decoding, because Pillow only raises at 2× MAX_IMAGE_PIXELS
        if w0 * h0 > MAX_PIXELS or frames_n > MAX_FRAMES or w0 * h0 * frames_n > MAX_TOTAL_PIXELS:
            raise Invalid("the image is too large to process")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise Invalid("the image could not be read") from None
    animated = getattr(img, "is_animated", False) and fmt in ("GIF", "WEBP")
    out = io.BytesIO()
    if animated:
        frames = []
        for i in range(getattr(img, "n_frames", 1)):
            img.seek(i)
            f = img.copy()
            f.thumbnail((max_edge, max_edge))
            frames.append(f)
        frames[0].save(out, format=fmt, save_all=True, append_images=frames[1:], loop=0,
                       duration=img.info.get("duration", 100))
        w, h = frames[0].size
    else:
        img = ImageOps.exif_transpose(img)       # honour orientation, then drop EXIF
        img.thumbnail((max_edge, max_edge))
        if fmt == "JPEG" and img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(out, format=fmt, **({"quality": 88} if fmt in ("JPEG", "WEBP") else {}))  # no exif= → stripped
        w, h = img.size
    return out.getvalue(), fmt, w, h


class MediaService:
    def __init__(self, engine: Engine, store: BlobStore, cfg: dict):
        self.e, self.store, self.cfg = engine, store, cfg

    def upload(self, owner_key: str, is_guest: bool, data: bytes) -> dict:
        if is_guest and not self.cfg.get("guest_images", False):
            raise Forbidden("sign in to upload images", code="guest_images_off")
        limit = self.cfg.get("max_image_mb", 5) * 1024 * 1024
        if len(data) > limit:
            raise Invalid(f"images must be at most {self.cfg.get('max_image_mb', 5)} MB")
        with self.e.connect() as c:
            recent = c.execute(select(func.count()).select_from(media).where(
                media.c.owner_key == owner_key, media.c.created_at >= now() - timedelta(hours=1))).scalar_one()
        if recent >= self.cfg.get("images_per_hour", 30):
            raise RateLimited("image upload limit reached; try again later")
        out, fmt, w, h = reencode(data, self.cfg.get("max_image_edge", 2048))
        mime, ext = OUT[fmt]
        key = f"media/{secrets.token_hex(16)}.{ext}"
        self.store.put(key, out, mime)
        row = {"id": new_id(), "owner_key": owner_key, "key": key, "mime": mime, "width": w, "height": h,
               "bytes": len(out), "created_at": now(), "removed_at": None}
        with self.e.begin() as c:
            c.execute(insert(media).values(**row))
        return self.public(row)

    @staticmethod
    def public(r: dict) -> dict:
        return {"id": r["id"], "url": f"/media/{r['id']}", "mime": r["mime"], "width": r["width"], "height": r["height"]}

    def get_row(self, media_id: str) -> dict:
        with self.e.connect() as c:
            r = c.execute(select(media).where(media.c.id == media_id)).mappings().first()
        if not r or r["removed_at"]:
            raise NotFound("image not found")
        return dict(r)

    def read(self, media_id: str) -> tuple[bytes, str]:
        r = self.get_row(media_id)
        return self.store.get(r["key"]), r["mime"]

    def attachable(self, owner_key: str, ids: list[str]) -> list[dict]:
        """Validate that every id exists, is live, and belongs to the poster."""
        if len(ids) > self.cfg.get("max_images_per_post", 10):
            raise Invalid(f"at most {self.cfg.get('max_images_per_post', 10)} images per post")
        rows = [self.get_row(i) for i in dict.fromkeys(ids)]
        if any(r["owner_key"] != owner_key for r in rows):
            raise Forbidden("you can only attach images you uploaded")
        return [self.public(r) for r in rows]

    def remove(self, media_id: str) -> None:
        """Moderator removal: deletes the file for everyone."""
        r = self.get_row(media_id)
        self.store.delete(r["key"])
        with self.e.begin() as c:
            c.execute(update(media).where(media.c.id == media_id).values(removed_at=now()))
