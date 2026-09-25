"""Claim-document retention (D-040): documents go 90 days after the decision; the record stays."""
from datetime import timedelta

from src.app.cli import main as cli_main
from src.app.core.db import now
from tests.app.conftest import PDF, register


def _claim(client, h, ref="Studio Nara"):
    r = client.post("/claims", headers=h, data={"claim_type": "publisher", "entity_ref": ref},
                    files=[("files", ("doc.pdf", PDF, "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()


def _stored(client, claim_id):
    ctx = client.app.state.ctx
    return ctx.verification.repo.get(claim_id)["doc_keys"]


def test_purge_after_retention_window(client, admin):
    _, ah = admin
    _, h = register(client, "pub")
    c = _claim(client, h)
    ctx = client.app.state.ctx
    key = _stored(client, c["id"])[0]
    client.post(f"/admin/claims/{c['id']}/decision", headers=ah, json={"decision": "approve"})

    assert ctx.verification.purge_documents(now() + timedelta(days=89)) == 0          # inside the window
    assert ctx.verification.purge_documents(now() + timedelta(days=91)) == 1
    assert _stored(client, c["id"]) == []
    assert client.get(f"/admin/claims/{c['id']}/documents/{key}", headers=ah).status_code == 404
    row = ctx.verification.repo.get(c["id"])
    assert row["status"] == "approved" and row["docs_purged_at"] is not None                # the decision is kept
    assert ctx.verification.purge_documents(now() + timedelta(days=200)) == 0              # idempotent


def test_pending_claims_are_never_purged(client):
    _, h = register(client, "pub")
    c = _claim(client, h)
    assert client.app.state.ctx.verification.purge_documents(now() + timedelta(days=3650)) == 0
    assert len(_stored(client, c["id"])) == 1


def test_withdraw_deletes_documents_now(client, admin):
    _, ah = admin
    _, h = register(client, "pub")
    _, other = register(client, "other")
    c = _claim(client, h)
    key = _stored(client, c["id"])[0]
    assert client.post(f"/claims/{c['id']}/withdraw", headers=other).status_code == 404      # not yours
    r = client.post(f"/claims/{c['id']}/withdraw", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "withdrawn" and r.json()["documents"] == 0
    assert client.get(f"/admin/claims/{c['id']}/documents/{key}", headers=ah).status_code == 404
    assert client.post(f"/claims/{c['id']}/withdraw", headers=h).status_code == 409
    assert client.post(f"/admin/claims/{c['id']}/decision", headers=ah, json={"decision": "approve"}).status_code == 409
    assert _claim(client, h)["status"] == "pending"                                         # may claim again


def test_cli_purge(settings, monkeypatch, capsys):
    for k, v in {"PLOTLINE_ENV": "test", "PLOTLINE_APP_DB_URL": settings.app_db_url,
                 "PLOTLINE_WAREHOUSE_PATH": settings.warehouse_path, "PLOTLINE_DOC_DIR": settings.doc_storage_dir,
                 "PLOTLINE_JWT_SECRET": settings.jwt_secret}.items():
        monkeypatch.setenv(k, v)
    assert cli_main(["purge-claim-docs"]) == 0
    assert "purged documents of 0" in capsys.readouterr().out
