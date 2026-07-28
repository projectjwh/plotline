# Deploy the Plotline explorer to Render (no GitHub)

The explorer is a static bundle — `web/index.html` (shell) + `web/explorer_data.json`
(data) — served by Caddy with gzip. Everything is prepared:

- `Dockerfile.web` — Caddy image serving `web/`
- `Caddyfile` — gzip + caching (optional password gate, commented)
- `render.yaml` — Render Blueprint (Docker web service)

Rebuild the bundle any time with:

```bash
python -m src.reports.build_explorer --mode api --covers 3000 \
  --data-url "/explorer_data.json" --out web/index.html
```

## Path A — Docker image, zero git hosts (recommended)

Requires Docker Desktop running and a container registry (Docker Hub is free).

```bash
# 1. Build (from repo root)
docker build -f Dockerfile.web -t plotline-web:latest .

# 2. Test locally — open http://localhost:10000
docker run --rm -p 10000:10000 -e PORT=10000 plotline-web:latest

# 3. Push to a registry (log in first: `docker login`)
docker tag plotline-web:latest docker.io/<your-user>/plotline-web:latest
docker push docker.io/<your-user>/plotline-web:latest
```

Then in the Render dashboard: **New → Web Service → Deploy an existing image**,
enter `docker.io/<your-user>/plotline-web:latest`, region + Free plan, Create.
Render injects `$PORT`; the Caddyfile already binds to it. Done — no GitHub.

## Path B — Render Blueprint via a non-GitHub Git remote

If you'd rather Render build the Dockerfile, push the repo to **GitLab or
Bitbucket** (not GitHub) and point Render at it:

```bash
git remote add deploy git@gitlab.com:<you>/plotline.git   # or Bitbucket
git push deploy HEAD
```

In Render: **New → Blueprint**, select the GitLab/Bitbucket repo. Render reads
`render.yaml` and builds `Dockerfile.web`. (Ensure `web/` is committed — it is
currently gitignored under `reports/`, so add `web/` explicitly if you use this
path: `git add -f web/index.html web/explorer_data.json`.)

## Optional: password gate (parity with the old Cloudflare deploy)

1. Generate a bcrypt hash:
   `docker run --rm caddy:2-alpine caddy hash-password --plaintext 'YOUR_PASS'`
2. Uncomment the `basicauth` block in `Caddyfile`.
3. On Render set env vars `AUTH_USER` and `AUTH_HASH` (the hash from step 1).

## Refresh (new data)

Re-run the build command above, then redeploy: `docker build … && docker push …`
and click **Manual Deploy** on Render (Path A), or `git push deploy` (Path B).
