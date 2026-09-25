"""PromotionRule decides when a post becomes a "concept" post (개념글). Replaceable from config."""
from __future__ import annotations

from typing import Protocol

from src.app.core.registry import Registry

promotion_rules = Registry("promotion rule")


class PromotionRule(Protocol):
    def is_concept(self, up: int, down: int) -> bool: ...


@promotion_rules.register("threshold")
class ThresholdRule:
    """Concept when up ≥ min_up and up / (up + down) ≥ min_ratio."""

    def __init__(self, min_up: int, min_ratio: float):
        self.min_up, self.min_ratio = min_up, min_ratio

    def is_concept(self, up: int, down: int) -> bool:
        return up >= self.min_up and up / max(up + down, 1) >= self.min_ratio
