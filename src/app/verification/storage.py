"""DocStorage: where claim evidence lives. The local folder is for dev; an S3/R2 adapter can register later.

Files are validated by their magic bytes, not by the declared MIME type, and are stored
under random keys outside any web root. Only admin endpoints read them back.
"""
from __future__ import annotations

import os
import re
import secrets
from typing import Protocol

from src.app.core.errors import Invalid, NotFound
from src.app.core.registry import Registry

doc_storages = Registry("document storage")

SIGNATURES = {b"%PDF-": ("application/pdf", "pdf"), b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
              b"\xff\xd8\xff": ("image/jpeg", "jpg")}
_KEY = re.compile(r"^[a-f0-9]{32}\.(pdf|png|jpg)$")


def sniff(data: bytes) -> tuple[str, str]:
    for sig, kind in SIGNATURES.items():
        if data.startswith(sig):
            return kind
    raise Invalid("only PDF, PNG or JPEG files are accepted")


class DocStorage(Protocol):
    def put(self, data: bytes) -> tuple[str, str]:
        """Store the bytes and return (key, mime)."""
        ...
    def get(self, key: str) -> tuple[bytes, str]: ...
    def delete(self, key: str) -> None: ...


@doc_storages.register("local_fs")
class LocalFSStorage:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, key: str) -> str:
        if not _KEY.match(key):  # blocks path traversal
            raise NotFound("document not found")
        return os.path.join(self.root, key)

    def put(self, data: bytes) -> tuple[str, str]:
        mime, ext = sniff(data)
        key = f"{secrets.token_hex(16)}.{ext}"
        with open(self._path(key), "xb") as f:
            f.write(data)
        return key, mime

    def get(self, key: str) -> tuple[bytes, str]:
        p = self._path(key)
        if not os.path.exists(p):
            raise NotFound("document not found")
        with open(p, "rb") as f:
            data = f.read()
        return data, sniff(data)[0]

    def delete(self, key: str) -> None:
        p = self._path(key)
        if os.path.exists(p):
            os.remove(p)
