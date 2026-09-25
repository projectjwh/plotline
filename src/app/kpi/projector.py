"""KPI projection: the single place that decides which fields a viewer receives.

Routers never gate KPIs themselves. They pass rows through ``KpiProjector.project``.
Visibility is the most generous level across the viewer's audiences (fans always
count as one). A field that is not declared is hidden.
"""
from __future__ import annotations

import math

_RANK = {"hidden": 0, "rounded": 1, "shown": 2}


def round_sig(v, sig: int = 2):
    if v is None or not isinstance(v, (int, float)) or v == 0 or isinstance(v, bool):
        return v
    digits = sig - int(math.floor(math.log10(abs(v)))) - 1
    r = round(v, digits)
    return int(r) if digits <= 0 else r


class KpiProjector:
    def __init__(self, policy: dict):
        self.audiences = policy.get("audiences", [])
        self.public = set(policy.get("public", []))
        self.fields: dict[str, dict] = policy.get("fields", {})
        for name, spec in self.fields.items():
            for a in self.audiences:
                if spec.get(a) not in _RANK:
                    raise ValueError(f"kpis.yaml: {name}.{a} must be one of {list(_RANK)}")

    def level(self, field: str, audiences) -> str:
        if field in self.public:
            return "shown"
        spec = self.fields.get(field)
        if not spec:
            return "hidden"
        return max((spec.get(a, "hidden") for a in audiences), key=_RANK.__getitem__, default="hidden")

    def is_model(self, field: str) -> bool:
        return bool(self.fields.get(field, {}).get("is_model"))

    def project(self, row: dict, audiences) -> dict:
        out, model = {}, []
        for k, v in row.items():
            lvl = self.level(k, audiences)
            if lvl == "hidden":
                continue
            out[k] = round_sig(v) if lvl == "rounded" else v
            if self.is_model(k):
                model.append(k)
        if model:
            out["model_fields"] = model
        return out

    def project_many(self, rows, audiences) -> list[dict]:
        return [self.project(r, audiences) for r in rows]

    def catalog(self) -> list[dict]:
        """The persona × KPI matrix as data (for docs and the frontend)."""
        return [{"field": k, **{a: v.get(a) for a in self.audiences},
                 "source": v.get("source"), "is_model": bool(v.get("is_model"))} for k, v in self.fields.items()]
