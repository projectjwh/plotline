"""Deploy plumbing: /ready, request ids, body cap, write rate limits, client IP behind a proxy."""
import dataclasses
import os

from fastapi.testclient import TestClient

from src.app.core.http import client_ip
from src.app.main import create_app


def test_ready_reports_db_and_warehouse(client, settings):
    r = client.get("/ready")
    assert r.status_code == 200 and r.json() == {"status": "ready", "app_db": True, "warehouse": True}
    os.remove(settings.warehouse_path)
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["warehouse"] is False


def test_request_id_is_echoed_or_assigned(client):
    assert client.get("/health", headers={"X-Request-ID": "abc12345-req"}).headers["x-request-id"] == "abc12345-req"
    rid = client.get("/health", headers={"X-Request-ID": "bad id\n"}).headers["x-request-id"]
    assert len(rid) == 32 and rid.isalnum()


def test_body_cap(settings):
    c = TestClient(create_app(dataclasses.replace(settings, max_body_mb=1)))
    r = c.post("/auth/login", content=b"x" * (1024 * 1024 + 1), headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"] == "too_large"

    def chunks():  # no Content-Length: the streamed body is counted
        for _ in range(3):
            yield b"x" * (512 * 1024)
    r = c.post("/auth/login", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413
    # claim uploads get their own cap (5 files × 10 MB in app.yaml), so a 2 MB claim body is not refused
    r = c.post("/claims", content=b"x" * (2 * 1024 * 1024), headers={"content-type": "application/json"})
    assert r.status_code != 413


def test_write_rate_limit_per_ip(settings):
    c = TestClient(create_app(dataclasses.replace(settings, rate_limits=True)))
    codes = [c.post("/follows", json={"target_type": "title", "ref": "tapas_io:3"}).status_code for _ in range(61)]
    assert codes[:60] == [401] * 60 and codes[60] == 429          # write: 60/minute in app.yaml
    assert c.get("/health").status_code == 200            # reads are not limited here


def test_client_ip_trusts_only_the_proxy_hop():
    h = {"x-forwarded-for": "6.6.6.6, 203.0.113.9", "fly-client-ip": "198.51.100.7"}
    assert client_ip(h, "10.0.0.1", trust_proxy=False, ip_header=None) == "10.0.0.1"
    assert client_ip(h, "10.0.0.1", trust_proxy=True, ip_header=None) == "203.0.113.9"   # not the spoofed 6.6.6.6
    assert client_ip(h, "10.0.0.1", trust_proxy=True, ip_header="Fly-Client-IP") == "198.51.100.7"
