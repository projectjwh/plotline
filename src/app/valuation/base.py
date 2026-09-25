"""ValuationModel: how an IP's value band is estimated. Replaceable from config."""
from __future__ import annotations

from typing import Protocol

from src.app.core.registry import Registry

valuation_models = Registry("valuation model")


class ValuationModel(Protocol):
    name: str

    def value(self, title: dict) -> dict:
        """Return {revenue_annual:{low,mid,high}, valuation:{low,mid,high}|None, drivers:[...],
        assumptions:{...}, is_model: True, reason?: str}."""
        ...
