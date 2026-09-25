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
| O-01 … O-16 | open | Outstanding decisions |

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

---

## Outstanding decisions

### Frontend
| ID | Question | Why it matters | My suggestion |
|---|---|---|---|
| O-01 | Is the market overview the fans' home page, or does fans' home start with their feed (followed titles, new episodes, concept posts) with the market one click away? | Fans' first impression and retention | A feed-first home for signed-in fans, the market page for everyone else |
| O-02 | Launch languages: KR, EN or both? This includes board culture terms (개념글, ㅇㅇ). | Copy, SEO and moderation staffing | EN + KR, since both reference communities are Korean |
| O-03 | In production, may people post anonymously without an account (true DCInside guests)? | Spam and moderation load vs. friction | Yes on fanboards, with rate limits and an IP-hash ban list; ratings and wishes need an account |
| O-04 | Media in posts: images, spoiler blocks, embeds? | Storage cost, moderation, copyright (piracy links) | Spoiler blocks at launch; images once moderation tooling exists |
| O-05 | Are premium panels shown to fans as locked teasers? | Conversion vs. clutter | Keep the teasers (current design) |
| O-06 | Mobile: responsive web only, or apps later? | Scope and push notifications for episode threads | Responsive web and PWA first |
| O-07 | Brand: keep "Plotline"? Keep the ticker-style title codes (e.g. TOLE)? | Identity; codes need a uniqueness rule | Keep both; generate codes deterministically |
| O-08 | Accessibility target (WCAG 2.2 AA?) | Legal exposure and audience | AA |

### Backend
| ID | Question | Why it matters |
|---|---|---|
| O-09 | Plan prices for Author, Publisher and Investor | Billing and landing page |
| O-10 | Valuation base multiples (low, mid, high) and adjustment weights | The valuation stays null until set (D-009) |
| O-11 | Hosting: the repo has Fly, Render, Vercel and Cloudflare configs. Pick one API host and a Postgres provider. | Cost and ops |
| O-12 | A transactional email provider, for account verification and password reset | Needed before public sign-up |
| O-13 | When to switch on Stripe (billing flag) | Revenue timing |
| O-14 | Automated moderation (spam or toxicity filters) at launch? | Moderator load |
| O-15 | Real-data gaps: publisher extraction is empty (`dim_publisher`), and the pipeline doesn't emit `episode.released` or `title.entered_rising` | Portfolio, episode threads and scout points depend on them |
| O-16 | Data retention for claim documents, and deletion on request | Privacy and compliance |
