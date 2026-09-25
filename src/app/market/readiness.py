"""Adaptation readiness (0–100): a Python port of the explorer formula
(``src/reports/explorer_assets/template.html:614-625``) so the API can serve it.

It measures readiness to option, not confirmed rights availability. That needs external data.
Weights and genre priors are config (``app.yaml: readiness``).
"""
from __future__ import annotations

import math

DEFAULT_WEIGHTS = {"reach": .30, "eng": .15, "mom": .12, "complete": .18, "depth": .10, "prior": .15}
STATUS_SCORE = {"completed": 1.0, "hiatus": 0.3, "ongoing": 0.6}


def components(*, reach_pct: float, like_through_pct: float | None, momentum: float | None,
               status: str | None, units: int | None, genre: str | None, priors: dict, default_prior: float) -> dict:
    return {
        "reach": reach_pct or 0.0,
        "eng": min(1.0, (like_through_pct or 0) / 8),
        "mom": max(0.0, min(1.0, momentum / 50)) if momentum is not None else 0.3,
        "complete": STATUS_SCORE.get((status or "").lower(), 0.55),
        "depth": min(1.0, units / 100) if units else 0.4,
        "prior": priors.get(genre, default_prior) if genre else default_prior,
    }


def score(comp: dict, weights: dict | None = None) -> int:
    w = weights or DEFAULT_WEIGHTS
    # JS Math.round semantics (half rounds up), not Python banker's rounding
    return int(math.floor(100 * sum(w[k] * comp[k] for k in w) + 0.5))
