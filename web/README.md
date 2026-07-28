# Plotline — link-only hosted explorer (Cloudflare Pages)

This directory is the deploy root for a **password-protected, API-backed** hosting of the
explorer. The front-end is a small shell (`index.html`, ~0.4 MB) that fetches
`explorer_data.json` (~15 MB) at runtime; a daily local job rebuilds the data and redeploys so
the site refreshes each day. Access is gated by HTTP Basic Auth in `_worker.js`.

```
web/
  _worker.js           # Basic Auth gate (committed) — protects the whole site
  index.html           # API-backed shell (generated; git-ignored)
  explorer_data.json   # the data the shell fetches (generated; git-ignored)
```

## One-time setup

1. Create a **Cloudflare account** (free). Install the CLI is not required — `npx wrangler`
   works.

2. Authorize this machine:

   ```powershell
   npx wrangler login
   ```

3. Build the shell + data once, then create the Pages project by deploying:

   ```powershell
   python -m src.reports.build_explorer --mode api --covers 6000 `
     --data-url "/explorer_data.json" --out web\index.html
   npx wrangler pages deploy web --project-name plotline --commit-dirty=true
   ```

4. Set the shared password (used by everyone with the link):

   ```powershell
   npx wrangler pages secret put SITE_PASSWORD --project-name plotline
   ```

You now have a URL like `https://plotline.pages.dev` that prompts for a password (any
username + your password) and is marked `noindex`.

## Daily refresh

`deploy/refresh_and_publish.ps1` runs the gather → rebuild → redeploy. Register it with Task
Scheduler (command is in the script header) to run daily, e.g. 6 AM. The site updates each day
once the gather completes; no manual step.

## Notes

- **Link-only:** the auth Worker returns `401` without the password and sets
  `X-Robots-Tag: noindex`, so the site is not publicly browsable or indexed.
- **Custom password rotation:** re-run the `wrangler pages secret put SITE_PASSWORD` command.
- **Lighter payload (optional):** the 15 MB JSON is dominated by embedded base64 covers. On a
  self-hosted origin (no artifact CSP), covers could instead be served from their remote URLs
  or a `web/covers/` folder, shrinking the JSON to ~3 MB. Not required — the current build
  works as-is (Cloudflare gzips it to ~5 MB on the wire).
- **Custom domain:** add one in the Pages project settings; the auth Worker applies there too.
