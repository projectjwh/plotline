"""Revenue-multiple valuation (the method chosen in the product spec, §5).

    annual_{low,mid,high}    = est_usd × 12 × {LOW_MULT, 1, HIGH_MULT}      (src/models/earnings.py)
    valuation_{low,mid,high} = annual_{low,mid,high} × base_multiple_{low,mid,high} × adj
    adj = clamp(1 + w_m·(momentum_pct − 0.5) + w_c·completed + w_x·ln(platforms), lo, hi)

The base multiples are product-owner inputs. No public dataset of story-IP deal
multiples was found, so none are hard-coded. While they are null, this returns the
revenue band and ``valuation: None`` with a reason.
"""
from __future__ import annotations

import math

from src.app.valuation.base import valuation_models
from src.models.earnings import HIGH_MULT, LOW_MULT


@valuation_models.register("revenue_multiple")
class RevenueMultipleModel:
    name = "revenue_multiple"

    def __init__(self, base_multiple: dict, adjustment: dict):
        self.base = base_multiple or {}
        self.adj = adjustment or {}

    def value(self, title: dict) -> dict:
        mid = title.get("est_usd")
        if mid is None:
            return {"is_model": True, "model": self.name, "revenue_annual": None, "valuation": None,
                    "drivers": [], "reason": "no revenue estimate for this title"}
        annual = {"low": mid * 12 * LOW_MULT, "mid": mid * 12, "high": mid * 12 * HIGH_MULT}
        mom = title.get("momentum_pct")
        completed = 1.0 if (title.get("status") or "").lower() == "completed" else 0.0
        platforms = max(1, int(title.get("platform_count") or 1))
        wm, wc, wx = (self.adj.get("momentum_weight", 0), self.adj.get("completed_bonus", 0),
                      self.adj.get("platform_weight", 0))
        lo, hi = self.adj.get("clamp", [0.5, 2.0])
        terms = [("momentum_pct", mom, wm * ((mom if mom is not None else 0.5) - 0.5)),
                 ("completed", bool(completed), wc * completed),
                 ("platform_count", platforms, wx * math.log(platforms))]
        adj = max(lo, min(hi, 1 + sum(t[2] for t in terms)))
        drivers = [{"driver": "annual_revenue_model", "value": {k: round(v, 2) for k, v in annual.items()}, "effect": "base"}]
        drivers += [{"driver": n, "value": v, "effect": round(e, 4)} for n, v, e in terms]
        out = {"is_model": True, "model": self.name, "revenue_annual": {k: round(v, 2) for k, v in annual.items()},
               "adjustment": round(adj, 4), "drivers": drivers,
               "assumptions": {"base_multiple": self.base, "adjustment": self.adj,
                               "revenue_band": [LOW_MULT, 1, HIGH_MULT]}}
        if any(self.base.get(k) is None for k in ("low", "mid", "high")):
            return {**out, "valuation": None, "reason": "base multiples not configured (config/policy/app.yaml: valuation.base_multiple)"}
        val = {k: round(annual[k] * float(self.base[k]) * adj, 2) for k in ("low", "mid", "high")}
        return {**out, "valuation": val}
