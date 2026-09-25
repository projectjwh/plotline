# Frontend guide (live demo → production)

This guide covers how the live demo (`docs/product/demo.html`, published at claude.ai/artifact/ARcRp5NXS4fLhn4KC4wbtT) is organised, and how to change it one piece at a time. The same structure carries over to the Next.js app (decision D-026 in `decisions.md`).

## 1. Theming (CSS)

The stylesheet has five layers, in order:

| Layer | Contains | Change it when |
|---|---|---|
| 1. Theme tokens | Colors only, under `:root[data-pl-theme="dark"]` and `:root[data-pl-theme="light"]`; up/down overrides under `:root.us…` | You restyle, add a theme, or retune a color |
| 2. Scale tokens | Fonts, sizes (`--fs-*`), radius, gutter, gap, `--row-h` (fanboard density), `--maxw` | You change type, spacing or density |
| 3. Base | Element defaults | Rarely |
| 4. Components | `.panel .btn .pill .chg .tabs .board …`, built from tokens only | You add a component |
| 5. Screens and motion | Screen-specific layout; reduced-motion rules | You add a screen |

Rules:
- **No hex or rgba values outside layer 1.** Check with:
  `python3 -c "import re;s=open('docs/product/demo.html').read().split('3. BASE')[1].split('</style>')[0];print(re.findall(r'#[0-9A-Fa-f]{3,6}\b|rgba\(',s))"`, which must print `[]`.
- **Adding a theme** (for example high-contrast):
  1. Copy the light block to `:root[data-pl-theme="hc"]` and change the values.
  2. Add `"hc"` to `applyTheme`/`toggleTheme`.
  3. Run any new up/down pair through the dataviz palette validator on that theme's surface.
- **Density:** fanboard row height is `--row-h` (30px). A "comfortable" mode is one token override: `:root[data-density="comfy"]{--row-h:40px}`.
- **Cover art** is generated on a canvas and deliberately doesn't follow the theme, because it stands in for real cover images.

## 2. Script sections

The live layer is split into named sections: **CONFIG · THEME · DATA · RENDER · ACTIONS · DERIVE · IDENTITY · HOOKS · SCREENS · ROUTING · WIRING · START**.

| To… | Touch |
|---|---|
| Change a threshold (concept votes, rating prior, wishlist media) | `CONFIG` |
| Add a screen | `SCREENS` (see §3), then add a `ROUTES` entry for the nav |
| Add shared data | §4 |
| Show a new computed number | `DERIVE`: add a memoized function `M("key", () => …)` |
| Hook a live widget into a market or title page | `HOOKS`: add a function and call it from the page template |

## 3. Adding a screen

```js
SCREENS.register("scouts", () => `
  <div class="pagehead"><div><div class="eyebrow">Scouts ${liveBadge()}</div>
  <h1 class="h1">Top scouts</h1></div></div>
  ${panel("Leaderboard", "…")}`,
  view => { /* optional: attach handlers inside `view` */ });
// nav entry, in ROUTES: ["scouts","Scouts","c"]   (m = market, c = community, p = pro, a = owner-only, h = hidden)
```
- Routes with an argument use `#<route>-<arg>`: `#title-TOLE`, `#fanboard-LOUNGE`, `#post-<id>`. Add new ones to the `renderView` regex.
- Buttons use `data-act="<name>" data-id="…"`, handled in `act()`. Use the same pattern for new actions.
- The skill `.claude/skills/add-screen/SKILL.md` walks through these steps.

## 4. Adding shared (live) data

1. **Collection:** add its name to `COLLS` in CONFIG. Every viewer writes only `<collection>/<their id>`.
2. **Access rules** at publish (`capabilities.db.rules`):
   ```
   {path:"<collection>", read:"view", write:"admin"}
   {path:"<collection>/{self}", write:"interact"}
   ```
   Owner-only data goes under its own path with `write:"admin"`, like `mod` and `seed`.
3. **Writes:** use `saveMine("<collection>", doc => { …; return doc; })`. It queues writes, updates the view immediately, and handles refused writes.
4. **Aggregation:** add a `DERIVE` function that reads `docsOf("<collection>")` or `flat("<collection>")`.
5. **Limits:** at most 5,000 documents per artifact, and 256 KiB per document. Per-user documents keep this bounded. Cap arrays with `.slice(-N)`, as posts and comments already do.

## 5. What stays sample data, and why
- **Market numbers** (indices, heat map, movers, listings) come from the seeded generator, because an artifact can't reach the FastAPI backend or DuckDB. In production they come from `/market/*` (`src/app/market`).
- **"Preview as" personas** only unlock premium panels locally, for design review. In production, entitlement comes from `/me`.

## 6. Mapping to production (Next.js)
| Demo | Production |
|---|---|
| Theme token blocks | CSS variables in `app/globals.css`; the same token names |
| `SCREENS.register` routes | `app/<route>/page.tsx` |
| `DERIVE` functions | API responses (`/market/*`, `/titles/*`, `/fanboards/*`), projected by the KPI projector on the server |
| `saveMine` + db rules | Authenticated REST calls; ownership enforced in `src/app/community` and `src/app/fan` |
| Owner queues | `/admin/*` endpoints |
