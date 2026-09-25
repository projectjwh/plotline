"""BlobStore: private object storage for user uploads (claim documents, fanboard images).

``local`` writes under a folder (dev/tests). ``r2`` uses Cloudflare R2 through its S3 API,
reusing the repo's R2 credentials (R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY; see
src/db/publish_warehouse.py). Uploads go to a separate, private bucket, R2_APP_BUCKET, never
the public warehouse bucket.
"""
from __future__ import annotations

import os
import re
from typing import Protocol

from src.app.core.errors import NotFound
from src.app.core.registry import Registry

blob_stores = Registry("blob store")
_KEY = re.compile(r"^[a-z]+/[a-f0-9]{32}\.[a-z0-9]{2,4}$")   # prefix/hex.ext: nothing user-controlled


def check_key(key: str) -> str:
    if not _KEY.match(key):
        raise NotFound("object not found")
    return key


class BlobStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


@blob_stores.register("local")
class LocalBlobStore:
    def __init__(self, root: str, **_):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, key: str) -> str:
        return os.path.join(self.root, *check_key(key).split("/"))

    def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self._path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "xb") as f:
            f.write(data)

    def get(self, key: str) -> bytes:
        p = self._path(key)
        if not os.path.exists(p):
            raise NotFound("object not found")
        with open(p, "rb") as f:
            return f.read()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if os.path.exists(p):
            os.remove(p)


@blob_stores.register("r2")
class R2BlobStore:
    def __init__(self, client=None, bucket: str | None = None, **_):
        self.bucket = bucket or os.environ.get("R2_APP_BUCKET")
        if client is None:
            missing = [k for k in ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_APP_BUCKET")
                       if not os.environ.get(k)]
            if missing:
                raise RuntimeError(f"r2 blob store needs env: {', '.join(missing)}")
            import boto3  # lazy: only the r2 store needs it
            client = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT"], region_name="auto",
                                  aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                                  aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"])
        self.s3 = client

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=check_key(key), Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=check_key(key))["Body"].read()
        except Exception as e:  # botocore NoSuchKey and friends
            if "NoSuchKey" in type(e).__name__ or "NoSuchKey" in str(e) or "404" in str(e):
                raise NotFound("object not found") from None
            raise

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=check_key(key))
