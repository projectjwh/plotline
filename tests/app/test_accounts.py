from tests.app.conftest import last_token, register


def test_unverified_account_is_limited_until_confirmed(client):
    user, h = register(client, "newbie", verify=False)
    assert user["email_verified"] is False
    r = client.put("/ratings/webtoon_global:1", headers=h, json={"score": 8})
    assert r.status_code == 403 and r.json()["error"] == "email_unverified"
    gid = client.get("/fanboards/by/title/webtoon_global:1").json()["id"]
    r = client.post(f"/fanboards/{gid}/posts", headers=h, json={"title": "t", "body": "b"})
    assert r.status_code == 403 and r.json()["error"] == "email_unverified"
    # guests (no token) can still post
    assert client.post(f"/fanboards/{gid}/posts", json={"title": "t", "body": "b", "nick": "g", "password": "pw1234"}).status_code == 201
    r = client.post("/auth/verify/confirm", json={"token": last_token(client, "newbie@x.test")})
    assert r.status_code == 200 and r.json()["user"]["email_verified"] is True
    assert client.put("/ratings/webtoon_global:1", headers=h, json={"score": 8}).status_code == 200


def test_tokens_are_purpose_bound(client):
    _, h = register(client, "reader1", verify=False)
    verify_tok = last_token(client, "reader1@x.test")
    assert client.get("/me", headers={"Authorization": f"Bearer {verify_tok}"}).status_code == 401
    access = h["Authorization"].split()[1]
    assert client.post("/auth/verify/confirm", json={"token": access}).status_code == 401
    assert client.post("/auth/password/reset", json={"token": verify_tok, "password": "another-pass-9"}).status_code == 401


def test_password_reset_signs_out_old_sessions(client):
    _, h = register(client, "reader1")
    assert client.post("/auth/password/forgot", json={"email": "reader1@x.test"}).status_code == 202
    tok = last_token(client, "reader1@x.test", "reset")
    assert client.post("/auth/password/reset", json={"token": tok, "password": "brand-new-pass-7"}).status_code == 204
    assert client.get("/me", headers=h).status_code == 401                              # old session ended
    assert client.post("/auth/password/reset", json={"token": tok, "password": "again-pass-777"}).status_code == 401  # single use
    assert client.post("/auth/login", json={"email": "reader1@x.test", "password": "correct-horse-1"}).status_code == 401
    assert client.post("/auth/login", json={"email": "reader1@x.test", "password": "brand-new-pass-7"}).status_code == 200


def test_forgot_does_not_reveal_accounts(client):
    before = len(client.app.state.ctx.mailer.outbox)
    r = client.post("/auth/password/forgot", json={"email": "nobody@x.test"})
    assert r.status_code == 202 and len(client.app.state.ctx.mailer.outbox) == before


def test_login_throttle_locks_after_repeated_failures(client):
    register(client, "reader1")
    for _ in range(5):
        assert client.post("/auth/login", json={"email": "reader1@x.test", "password": "wrong-password"}).status_code == 401
    r = client.post("/auth/login", json={"email": "reader1@x.test", "password": "correct-horse-1"})
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"


def test_locale_preference(client):
    _, h = register(client, "reader1")
    assert client.patch("/me", headers=h, json={"locale": "ko"}).json()["user"]["locale"] == "ko"
    assert client.patch("/me", headers=h, json={"locale": "fr"}).status_code == 422


def test_login_checks_a_hash_even_for_unknown_emails(client, monkeypatch):
    """Unknown and known emails both pay for one password check, so timing does not reveal accounts."""
    register(client, "known")
    ctx = client.app.state.ctx
    calls = []
    real = ctx.identity.provider.verify_password
    monkeypatch.setattr(ctx.identity.provider, "verify_password", lambda h, p: calls.append(h) or real(h, p))
    for email in ("known@x.test", "nobody@x.test"):
        assert client.post("/auth/login", json={"email": email, "password": "wrong-password-1"}).status_code == 401
    assert len(calls) == 2
