"""Named-implementation registry: the seam that makes behaviour replaceable from config.

    valuation_models = Registry("valuation model")

    @valuation_models.register("revenue_multiple")
    class RevenueMultipleModel: ...

    model = valuation_models.create(policy.app("valuation", "model"), **params)
"""
from __future__ import annotations

from typing import Any, Callable


class Registry:
    def __init__(self, kind: str):
        self.kind = kind
        self._items: dict[str, Callable[..., Any]] = {}

    def register(self, name: str):
        def deco(factory):
            if name in self._items:
                raise ValueError(f"{self.kind} '{name}' already registered")
            self._items[name] = factory
            return factory
        return deco

    def create(self, name: str, **kwargs) -> Any:
        if name not in self._items:
            raise KeyError(f"unknown {self.kind} '{name}'. Known: {sorted(self._items)}")
        return self._items[name](**kwargs)

    def names(self) -> list[str]:
        return sorted(self._items)
