---
name: add-screen
description: Add or change a screen in the Plotline live demo (docs/product/demo.html) or its design system — register the route, reuse components and tokens, wire actions, add live data with db rules, then republish the artifact and log the decision. Use whenever a new page, panel or live feature is requested for the demo/frontend.
---

# Add a screen to the Plotline frontend demo

Read `docs/product/frontend-guide.md` first. It is the source of truth for structure.

## Steps
1. **Decide the scope.** Is the data sample (market) or live (community)? Is the screen public, pro, or owner-only?
2. **Render.** Call `SCREENS.register("<route>", () => html, wire?)` in the SCREENS section.
   - Build from existing components: `panel()`, `.board`, `.pill`, `.btn`, `tname()`, `moverTable()`, `postTable()`.
   - Never write a literal color. When a new color is needed, add a token to both theme blocks in layer 1.
3. **Navigate.** Add `[route, label, kind]` to `ROUTES`. If the route takes an argument (`#<route>-<arg>`), add it to the `renderView` regex.
4. **Act.** For buttons, use `data-act` and handle them in `act()`. For forms, give each control a stable `id` and wire it in `wireLive()` or in the screen's `wire`.
5. **Live data** (if any):
   - add the collection to `COLLS` and write through `saveMine`
   - aggregate it in `DERIVE` with `M()`
   - add the two db rules (collection `read:view, write:admin`; `{self}` `write:interact`) to the publish call, and restate every existing rule too, since a declaration replaces the whole set
6. **Layout.** Render card grids through `completeRows()` so no row is left half empty, and keep one growing box per column so row edges align.
7. **Check.**
   - Run the hex-outside-tokens check from the guide and `python docs/product/tools/contrast_check.py` (must PASS).
   - Load the page once in light and once in dark (headless Chromium) and confirm no console errors.
8. **Publish and record.**
   - Republish `docs/product/demo.html` to its existing URL.
   - When the db rules changed, run a `list` and an `as_level: "interact"` write check with ArtifactData.
   - Append a `D-0xx` entry to `docs/product/decisions.md`.
   - Commit.
