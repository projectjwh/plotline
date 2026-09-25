# Decision log

Architecture and product decisions for the Plotline revamp, newest last. **Append a new entry for every decision. Never edit a closed one.** To reverse a decision, add a new entry that supersedes it.

**Status values:**
- **Accepted**: in force.
- **Superseded**: replaced by a later entry.
- **Open**: needs an owner decision.

**Source tags:**
- **[owner]**: your answer in a planning survey.
- **[code]**: verified in this repository.
- **[ext]**: an external source, cited.
- **[proposal]**: my recommendation, which you accepted.

| ID | Date | Area |
|---|---|---|
| D-001 … D-011 | 2026-09-24/25 | Product and personas |
| D-012 … D-019 | 2026-09-25 | Backend architecture |
| D-020 … D-027 | 2026-09-25 | Frontend and design |
| D-031 … D-043 | 2026-09-25 | Phase 2b: deployable backend |
| O-01 … O-24 | open / resolved | Outstanding decisions |

---

## Product and personas

**D-001 · Positioning: "IMDb + DCInside for digital story IP", starting with web novels and web comics.** Accepted. [owner]
- Fans get an IMDb-style title database and DCInside-style boards.
- The scraped market data becomes the premium layer.

**D-002 · Four customer groups; fans are free, and authors, publishers and IP investors pay.** Accepted. [owner]
- Alternative considered: a single paid "Pro" tier, the old model in `src/api/billing.py:27`. Rejected in favour of one plan per persona.

**D-003 · Paid access needs ownership or authority verified by manual document review.** Accepted. [owner]
- Alternatives considered: a token placed on the author's platform profile; matching an email domain. Not chosen.

**D-004 · Investors qualify through authorized-entity documents (PE/VC mandate, studio or company registration); they don't need to own a listed IP.** Accepted. [owner]

**D-005 · Premium users see every title at full depth, competitors included.** Accepted. [owner]
- Alternative considered: full depth only for their own titles, with anonymized peer benchmarks for everyone else.

**D-006 · Community model.**
- DCInside-style anonymous posting (nickname plus password, IP prefix shown), verified badges, and reports with a moderation queue. [owner]
- Fan features: ratings and reviews, follows and watchlist, per-title boards, lists and credits. [owner]
- Accepted.

**D-007 · Product thesis: the fan-data flywheel.** Accepted as a hypothesis. [proposal]
- Fan activity produces signals nobody else has (fan rating, wishlist votes, board activity, scout lead time). Paid personas buy KPIs built on those signals.
- The validation metrics are in `product-spec.md` §8.

**D-008 · KPI visibility per persona follows the matrix in `product-spec.md` §6.** Accepted. [proposal]
- Four data-quality metrics are dropped from the product: `novel_share`, `cover_coverage_pct`, `coverage_pct`, `with_cover`.
- Enforced in `config/policy/kpis.yaml`. Any field not declared there is hidden.

**D-009 · Valuation is a revenue-multiple band.** Accepted. [owner]
- The multiples are `null` until you set them, because no public dataset of story-IP deal multiples was found.
- Until then the API returns the revenue band and `valuation: null` with a reason.

**D-010 · Pricing: one plan per persona, prices still to be set.** Accepted. [owner]
- Billing stays off; admins grant plans (`src/api/billing.py` gate kept).

**D-011 · The fan rating is a Bayesian weighted mean (prior 7.0, weight 20); verified owners' votes are excluded.** Accepted. [proposal]
- Rationale: IMDb shows a weighted average to resist manipulation. [ext] [IMDb Help](https://help.imdb.com/article/imdb/track-movies-tv/the-vote-average-for-film-x-should-be-y-why-are-you-displaying-another-rating/G3RC8ZNFAGWNTX4L)
- Plotline publishes its formula, where IMDb keeps its own undisclosed.

## Backend architecture

**D-012 · Modular monolith (`src/app/`).** Accepted. [owner: "modular enough to modify in the future"]
- Each module is a service, a repo and a router.
- Replaceable behaviour is a `Protocol` plus a `Registry`, selected by name in `config/policy/app.yaml`.
- Modules are wired in one place, `src/app/context.py`.

**D-013 · Storage.**
- User and community data: SQLAlchemy Core. SQLite in dev and tests, Postgres in production.
- Analytics: the existing DuckDB warehouse, read-only.
- [owner: "cost effective but scalable"]
- Accepted.

**D-014 · Auth: built-in email and password with argon2 hashes and HS256 JWT.** Accepted. [owner]
- Alternative considered: Clerk. Deferred; the `AuthProvider` interface can take it later.

**D-015 · Admin rights are granted only by CLI (`python -m src.app.cli make-admin`).** Accepted. [code review finding]
- This supersedes the earlier `PLOTLINE_ADMIN_EMAILS` auto-admin.
- Reason: emails are unverified, so anyone could register an admin address first.

**D-016 · Policy lives in config, not code.**
- Entitlements, KPI visibility, thresholds and model parameters are in YAML under `config/policy/`.
- Accepted. [proposal]

**D-017 · Market index = a chain-linked reach index.** Accepted. [code]
- It uses total views of titles observed on consecutive days, rebased to 1,000.
- Rationale: the warehouse has no per-day PlotScore (`src/db/warehouse.py`), so the prototype's PlotScore-weighted index can't be computed.

**D-018 · Adaptation readiness is ported from the explorer's JavaScript (`template.html:614-625`) to Python, with identical weights.** Accepted. [code]

**D-019 · Rename "galleries" to "fanboards" everywhere.** Accepted. [owner]
- Covers UI, docs, API (`/fanboards…`), tables (`fanboards`, `fanboard_mods`, `posts.fanboard_id`) and tests.
- No migration is needed, because there is no production database yet.

## Frontend and design

**D-020 · Visual direction: dark editorial terminal modeled on stock-market pages (finviz, stock.naver.com).** Accepted. [owner]
- Includes a ticker, indices, a heat map, movers, and an IPO-style banner for new listings.
- Both reference sites were blocked from the build environment, so the patterns come from general knowledge, not live pages.

**D-021 · Light and dark themes with a toggle.** Accepted. [owner: "bright"/"bridge" read as light]
- Which theme loads: your saved choice first, then the claude.ai viewer's theme, then the OS setting.
- Colors live only in the theme-token layer (see `frontend-guide.md`).

**D-022 · Up/down colors: KR convention (red up, blue down) by default, US (green up, red down) as a toggle.** Accepted. [proposal]
- The US pair fails the colorblind separation check (validator ΔE 5.5 dark and 1.8 light, deuteranopia). Every change therefore also shows a ▲/▼ glyph and a sign.

**D-023 · Fanboard density: DCInside-style single-line rows, about 30px (`--row-h`).** Accepted. [owner]
- Columns: No., title with [comment count], writer, time, ▲.
- Notices are pinned; concept posts are tinted.

**D-024 · Concept promotion: up ≥ N and up/(up+down) ≥ r.** Accepted. [proposal]
- Product defaults are N=10, r=0.8 (`app.yaml`). The demo uses N=3 for a small audience.
- DCInside's own criteria are not public. [ext] [DCinside, Wikipedia](https://en.wikipedia.org/wiki/DCinside)

**D-025 · Live demo artifact for design review.** Accepted. [owner]
- Community data is live and shared; market data is sample data.
- Each viewer writes only their own document; moderation and seed data are editor-only.
- The "anonymous" option in the demo only changes what is displayed; entries are still stored under account ids.

**D-026 · Frontend stack for production: Next.js + TypeScript.** Accepted. [owner]
- Reason: server rendering for search indexing of title and fanboard pages.
- The demo's token system and screen registry carry over as the design system and route structure.

**D-027 · The demo code is organised for incremental change.**
- Named sections: CONFIG, THEME, DATA, RENDER, ACTIONS, DERIVE, IDENTITY, HOOKS, SCREENS, ROUTING, WIRING, START.
- New screens are added with `SCREENS.register(route, render, wire)`.
- Accepted. [owner: "incrementally updated"]

**D-028 · Typeface: NAVER's NanumSquare Neo for UI and headings; JetBrains Mono kept for numbers and tickers.** Accepted. [owner]
- You asked for "the font stock.naver.com uses". That site couldn't be reached from the build environment (proxy 403), and no public source names its font. You chose NanumSquare Neo, NAVER's current brand font (NAVER × Sandoll, 2022), with the understanding that it can be swapped.
- The files are the official, unmodified woff2 webfonts (400/700/800), embedded as data URIs, since the artifact CSP only allows Google Fonts and NanumSquare Neo isn't there. The copyright notice is kept in the stylesheet.
  - Sources: [github.com/moonspam/NanumSquareNeo](https://github.com/moonspam/NanumSquareNeo) · [Sandoll: NanumSquare Neo](https://www.sandoll.co.kr/NanumsquareNEO) · [noonnu: free for commercial use](https://noonnu.cc/en/font_page/1053)
- Numbers stay monospaced. The font's GSUB features are `frac, liga, vert, vrt2`, with no `tnum`, and its digit widths differ (458–716 units). Using it for numbers would misalign table columns.
- Cost: about 1.5 MB added to each page. A production build would subset or self-host the fonts (O-17).
- To swap fonts: change `--display` / `--ui` in scale-token layer 2 and the `0. FONTS` block.

**D-029 · Readability tokens with measured contrast targets.** Accepted. [owner: "color schema … better readability"]
- Before: box vs page 1.07 (dark) / 1.08 (light); borders 1.27; `--faint` text 3.2 (below WCAG AA 4.5); light-theme yellow used as text 3.25.
- After:
  - box vs page ≥ 1.15 (1.16 / 1.18)
  - borders ≥ 1.5 (1.54 / 1.57)
  - every text token ≥ 4.5 on page, box and raised surfaces in both themes
- New tokens:
  - `--mark-text`: the accent when used as text (light `#8A6300`); `--mark` stays for fills.
  - `--elev`: a subtle shadow in light, none in dark.
- The US-mode light up/down colors were darkened to `#167A45` / `#C42A47` to pass 4.5.
- Check with `python docs/product/tools/contrast_check.py`, which must print PASS.

**D-030 · Boxes in one row share top and bottom edges; card grids show only complete rows, with "See more".** Accepted. [owner]
- In a `.g12` row, every column is a flex column, and its last box grows (`flex:1`). Box headers share `--ph-h` (46px).
- `completeRows(key, items, {kind, sortBy})`:
  - shows whole rows only, largest items first
  - puts the remainder behind "See N more ▾" / "Show less ▴"
  - column counts mirror the CSS breakpoints (cards 3/2/1, index strips 8/4/2) and re-render when the breakpoint changes
  - the open state is kept per section in `STATE.more`
- Applied to: Sectors (sorted by constituents, then reach), the market index strip, and the author dashboard strip. The portfolio strip is fixed at 4 cards.
- Verified with a DOM check (sibling bottoms within 1px) on 9 screens × 2 themes: 0 misaligned rows, every index strip full.

---

## Phase 2b: deployable backend

Survey answers from the backend discussion, plus decisions made while building. Evidence: 85 tests pass on SQLite and on a local Postgres 16. A uvicorn smoke test ran against the image's file set: sign-up → verify → image post → feed.

**D-031 · Hosting: keep the documented stack.** Accepted. [owner] Resolves O-11.
- API: Fly.io, as a new app `plotline-app` (`fly.app.toml`, `Dockerfile.app`). The legacy `plotline-api` (`fly.toml`) stays until it is retired.
- App state: Neon Postgres. Analytics: the DuckDB warehouse, downloaded on boot from `PLOTLINE_WAREHOUSE_URL`.
- Uploads (claim documents, images): a **private** R2 bucket (`R2_APP_BUCKET`), separate from the public warehouse bucket.
- Frontend on Vercel; scheduled jobs on GitHub Actions.
- Behind a `BlobStore` registry (`local` | `r2`). Production refuses `local`.

**D-032 · Accounts: Resend email, verification gate, reset, throttling.** Accepted. [owner: Resend] Resolves O-12.
- Email goes through an `EmailSender` registry (`resend` | `console`). Production refuses `console`.
- **What needs a confirmed email:** rating, wishes, lists, claims, image uploads, and posting under an account. Guests can still post text.
- **Tokens:** each has one purpose (`access` | `verify` | `reset`) and carries the user's `token_version`. A password reset bumps the version, which signs out every session and makes the reset link single-use.
- **Throttling:** DB-backed (`auth_attempts`), per email and per IP hash, 5 failures per 15 minutes. It is in the DB because machines scale to zero.
- **Timing:** login checks a dummy hash for unknown emails, so the response time doesn't reveal which accounts exist. [code review finding]
- **Known trade-offs:**
  - Anyone who knows a user's email can lock that account out for 15 minutes by failing 5 times.
  - Sign-up still answers "email already registered".
  - Both are left as is; see O-22.

**D-033 · Personal feed, computed when it is read.** Accepted. [owner: feed] Resolves O-01 (the backend side; the screen is still to design).
- `GET /feed` merges four sources, newest first:
  - posts in the fanboards of followed titles
  - rank moves of followed titles, with the `rising` flag
  - new listings by followed authors and publishers
  - new episodes (`fact_episode.upload_date`)
- Paging uses an opaque cursor over (at, id). Sources are switched on in `app.yaml` (`feed.sources`).
- **No feed table (fan-out on read).** Results stay correct after unfollows and deletions, at the cost of per-request work. A stored fan-out can replace it behind the same endpoint.
- **Windows:** posts count back from now. Market events count back from the warehouse's latest crawl date, so a late data refresh does not empty the feed.
- **Title payloads** go through the KPI projector.

**D-034 · English and Korean.** Accepted. [owner] Resolves O-02.
- `posts.lang` and `comments.lang` are `en` | `ko`. They default to the account's `users.locale`, and lists accept `?lang=`.
- The API returns stable error `code`s; the frontend owns the EN/KR text.
- Title names exist in one language only in the warehouse: O-20.

**D-035 · Images in posts.** Accepted. [owner] Resolves O-04 (images; spoiler blocks remain a frontend item).
- **Upload:** `POST /media` accepts JPEG, PNG, WebP or GIF, checked by magic bytes, at most 5 MB.
- **Re-encoding:** every image is re-encoded with Pillow, which drops EXIF and GPS, and capped at 2048 px on the long edge. Random keys are stored in the private bucket.
- **Decoding limits:** at most 40M pixels per frame, 200 frames, and 200M pixels in total. These are checked from the header, before decoding, because Pillow only raises at twice its own limit. [code review finding]
- **Posts:** up to 10 images, and only your own. There is a per-user hourly limit.
- **Moderation:** `POST /admin/media/{id}/remove` removes an image everywhere.
- **Serving:** `nosniff` and `Content-Security-Policy: default-src 'none'`.

**D-036 · Link previews, with guards against server-side request forgery.** Accepted. [owner: link embeds]
- **Fetch rules:**
  - http and https only, default ports only, no credentials in the URL
  - every resolved address must be globally routable
  - redirects are followed by hand, at most 3, and every hop is re-checked
  - 3 s timeout, 512 KB, `text/html` only
- Fetching runs after the response (a background task). Results are cached in `embeds`.
- **Deny list:** `community.embed_deny_domains` suppresses previews. The operator edits it; it is not automated filtering.
- **Residual risk:** DNS can change between the check and the connection (DNS rebinding). See O-19.

**D-037 · Guests post text and links; images need an account.** Accepted. [proposal, accepted in the Phase 2b plan] Resolves O-03.
- Manual moderation combined with anonymous image uploads is the riskiest combination.
- One line (`community.guest_images: true`) reverses this.

**D-038 · Moderation is manual only at launch.** Accepted. [owner] Resolves O-14.
- It uses reports, the moderator queue, bans (account or IP hash) and image removal. There are no automated spam or toxicity filters.

**D-039 · Billing waits for the first verified customers.** Accepted. [owner] Resolves O-13.
- Until then, admins grant plans.
- Prices (O-09) and base multiples (O-10) stay placeholders.

**D-040 · Claim documents are deleted 90 days after the decision.** Accepted. [owner] Resolves O-16.
- `python -m src.app.cli purge-claim-docs` runs daily (`.github/workflows/claim-docs-purge.yml`). It empties `doc_keys` and sets `docs_purged_at`, and keeps the decision record.
- The window is `verification.retention_days_after_decision`.
- `POST /claims/{id}/withdraw` withdraws a pending claim and deletes its documents immediately. It is a conditional update, so it cannot race an approval.
- Pending claims are never purged.

**D-041 · Schema changes go through Alembic.** Accepted. [proposal, accepted in the Phase 2b plan]
- `migrations/` holds revision 0001, which equals the current models.
- Production runs `alembic upgrade head` as Fly's release command. `create_all` runs only outside production.
- A test and CI fail if the models change without a migration (`alembic check`).
- CI (`app-tests.yml`) runs the suite on SQLite and on Postgres 16.

**D-042 · HTTP operations.** Accepted. [proposal; the IP rule is a code review finding]
- **Logs:** JSON in production. Every request gets an `X-Request-ID` (echoed when it is well-formed). The access log records the path only, never the query string.
- **Body caps:** 12 MB by default. `/claims` gets its own cap, derived from the verification policy (files × size + 1 MB).
- **Write limits:** per-IP limits on writes, set in `http.rate_limits`. They are kept in memory, so they are per machine and reset on restart; the DB-backed limits (login, posts per minute, images per hour) are the durable ones.
- **Client IP:** behind a proxy, only the **rightmost** `X-Forwarded-For` entry is trusted, or a header named in `PLOTLINE_CLIENT_IP_HEADER`.
  - The previous code took the leftmost entry, which the client controls, so IP bans and limits could be evaded.
  - uvicorn runs with `--no-proxy-headers` so it doesn't rewrite the peer address.

**D-043 · Phase 2c scope: data.** Accepted. [owner]
- Pipeline events (`episode.released`, `title.entered_rising`), publisher extraction (`dim_publisher`) and upcoming listings. See O-15.

---

## Outstanding decisions

Resolved items keep their row, with the decision that resolved them.

### Frontend
| ID | Question | Why it matters | My suggestion |
|---|---|---|---|
| O-01 | **Resolved → D-033.** Is the market overview the fans' home page, or does fans' home start with their feed (followed titles, new episodes, concept posts) with the market one click away? | Fans' first impression and retention | A feed-first home for signed-in fans, the market page for everyone else |
| O-02 | **Resolved → D-034.** Launch languages: KR, EN or both? This includes board culture terms (개념글, ㅇㅇ). | Copy, SEO and moderation staffing | EN + KR, since both reference communities are Korean |
| O-03 | **Resolved → D-037.** In production, may people post anonymously without an account (true DCInside guests)? | Spam and moderation load vs. friction | Yes on fanboards, with rate limits and an IP-hash ban list; ratings and wishes need an account |
| O-04 | **Resolved → D-035.** Media in posts: images, spoiler blocks, embeds? | Storage cost, moderation, copyright (piracy links) | Spoiler blocks at launch; images once moderation tooling exists |
| O-05 | Are premium panels shown to fans as locked teasers? | Conversion vs. clutter | Keep the teasers (current design) |
| O-06 | Mobile: responsive web only, or apps later? | Scope and push notifications for episode threads | Responsive web and PWA first |
| O-07 | Brand: keep "Plotline"? Keep the ticker-style title codes (e.g. TOLE)? | Identity; codes need a uniqueness rule | Keep both; generate codes deterministically |
| O-08 | Accessibility target (WCAG 2.2 AA?) | Legal exposure and audience | AA |

### Backend
| ID | Question | Why it matters |
|---|---|---|
| O-09 | Plan prices for Author, Publisher and Investor | Billing and landing page |
| O-10 | Valuation base multiples (low, mid, high) and adjustment weights | The valuation stays null until set (D-009) |
| O-11 | **Resolved → D-031.** Hosting: the repo has Fly, Render, Vercel and Cloudflare configs. Pick one API host and a Postgres provider. | Cost and ops |
| O-12 | **Resolved → D-032.** A transactional email provider, for account verification and password reset | Needed before public sign-up |
| O-13 | **Resolved → D-039.** When to switch on Stripe (billing flag) | Revenue timing |
| O-14 | **Resolved → D-038.** Automated moderation (spam or toxicity filters) at launch? | Moderator load |
| O-15 | Real-data gaps: publisher extraction is empty (`dim_publisher`), and the pipeline doesn't emit `episode.released` or `title.entered_rising` | Portfolio, episode threads and scout points depend on them |
| O-17 | Confirm the font stock.naver.com actually uses (DevTools → Computed → font-family), and choose the production font delivery: subset vs self-hosted | Brand match; page weight |
| O-16 | **Resolved → D-040.** Data retention for claim documents, and deletion on request | Privacy and compliance |
| O-18 | Confirm Fly's client-IP header (`Fly-Client-IP`?) and the `[deploy] release_command` key against Fly's docs. fly.io was blocked from this sandbox, so they could not be checked here. | Correct IP bans and limits; migrations on deploy |
| O-19 | Route link-preview fetches through an egress proxy that allows only public ranges (closes the DNS-rebinding gap in D-036) | Server-side request forgery |
| O-20 | Bilingual title names (`title_ko` / `title_en`) need source data; the warehouse has one name per title | KR/EN search and display |
| O-21 | Machine size for `plotline-app` (512 MB is a starting point, not measured) | Cost vs. out-of-memory restarts |
| O-22 | Account-enumeration and lockout trade-offs in D-032: accept, or add CAPTCHA / email-only sign-up responses | Abuse vs. friction |
| O-23 | Phase 2c: pipeline events (`episode.released`, `title.entered_rising`) | Episode threads, scout points, real-time feed items |
| O-24 | Phase 2c: upcoming listings (announced titles) | The "IPO" banner |
