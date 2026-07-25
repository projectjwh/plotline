"""Publish the built warehouse to object storage (Cloudflare R2 via the S3 API).

The read API downloads this artifact on boot (``PLOTLINE_WAREHOUSE_URL``), so the
refresh job (CI or local) is what makes new data go live — no image rebuild, no
redeploy. If the R2 env vars are unset, this exits cleanly (0) so a refresh run
without publish credentials still succeeds.

Env: R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET,
     R2_KEY (default 'plotline.duckdb'), R2_PUBLIC_BASE (optional, for the URL).
Run: python -m src.db.publish_warehouse
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DB = os.path.join(_ROOT, "data", "plotline.duckdb")


def main() -> int:
    endpoint = os.environ.get("R2_ENDPOINT")
    bucket = os.environ.get("R2_BUCKET")
    key = os.environ.get("R2_KEY", "plotline.duckdb")
    if not (endpoint and bucket and os.environ.get("R2_ACCESS_KEY_ID")):
        print("publish: R2 env not set — skipping upload (warehouse built locally).")
        return 0
    if not os.path.exists(DB):
        print(f"publish: no warehouse at {DB} — run `python -m src.db.warehouse` first.")
        return 1
    import boto3  # lazy — only needed when publishing
    s3 = boto3.client(
        "s3", endpoint_url=endpoint, region_name="auto",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"])
    base = os.environ.get("R2_PUBLIC_BASE", "").rstrip("/")

    def _put(local: str, obj_key: str, content_type: str) -> None:
        print(f"publish: uploading {os.path.getsize(local) / 1e6:.1f} MB → r2://{bucket}/{obj_key}")
        s3.upload_file(local, bucket, obj_key, ExtraArgs={"ContentType": content_type})
        if base:
            print(f"         public URL = {base}/{obj_key}")

    _put(DB, key, "application/octet-stream")  # the warehouse (PLOTLINE_WAREHOUSE_URL)

    # Also publish the explorer data JSON if the refresh built one — the
    # Vercel-hosted API-backed shell fetches it (see build_explorer --mode api).
    ej = os.environ.get("PLOTLINE_EXPLORER_JSON")
    if ej and os.path.exists(ej):
        _put(ej, os.environ.get("R2_EXPLORER_KEY", "explorer_data.json"), "application/json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
