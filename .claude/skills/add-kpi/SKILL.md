---
name: add-kpi
description: Add or change a KPI in Plotline end to end — compute it in a model, declare its persona visibility, surface it in docs/wireframes, and test the gating. Use whenever a new metric is introduced, a KPI's audience changes (fan / author / publisher / investor), or a KPI is dropped.
---

# Add or change a KPI

Plotline shows each KPI to a set of personas (fan, author, publisher, investor). The source of truth for who sees what is the persona × KPI matrix in `docs/product/product-spec.md` §6. In Phase 2 it moves to `src/kpi/kpis.yaml`, and the matrix is then generated from that file. Never gate a KPI inside a route handler.

## Steps
1. **Evidence first.** Name the exact source: a column in the DuckDB warehouse (`src/db/star_schema.py`), or a function in `src/models/*.py`. Give file and line. If the KPI is new, write down its formula. If it is modeled rather than scraped, mark it `is_model: true` and state its assumptions, as `src/models/earnings.py` does.
2. **Compute.**
   - Put the logic in a model module under `src/models/` (Polars preferred, per CLAUDE.md).
   - Keep tunables in `config.yaml`, never as constants in routes.
   - Deduplicate on `(comic_id, date)`, keeping the latest snapshot.
3. **Declare visibility.** Add one row to the matrix and, once it exists, to `src/kpi/kpis.yaml`. For each persona use one of `shown | rounded | premium | premium_exact | hidden`. Give a one-line rationale tied to that persona's job-to-be-done (spec §2).
4. **Surface.**
   - Add the KPI to the relevant wireframe screen's `kpis` note in `docs/product/wireframes.html`, in the format `[label, gate, source]`.
   - Update `docs/metrics.md` if the KPI is user-facing.
5. **Test** (Phase 2+). Add projector tests asserting that:
   - a fan never receives a premium or hidden field
   - an entitled persona receives it
   - model fields carry `is_model: true`
6. **Drop a KPI.** Set every persona to `hidden`, record the reason in the matrix, and keep it available to admins only if it is a data-quality metric (for example `cover_coverage_pct`).

## Checklist before commit
- [ ] Source path and line verified in the repo
- [ ] Matrix row added or updated, with rationale
- [ ] No gating logic in routers
- [ ] Modeled values labeled `is_model`
- [ ] Wireframe note and docs updated
