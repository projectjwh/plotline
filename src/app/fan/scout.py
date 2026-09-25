"""ScoutRule: points for following a title before it started rising. Replaceable from config.

The assumption that early fan calls predict later gains is a hypothesis (spec §8). The
points are a reward mechanic; they are not a proven signal.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.app.core.registry import Registry

scout_rules = Registry("scout rule")


class ScoutRule(Protocol):
    def points(self, followed_at: datetime, rising_at: datetime) -> int: ...


@scout_rules.register("lead_time")
class LeadTimeRule:
    def __init__(self, points_per_day: int, max_points: int):
        self.ppd, self.cap = points_per_day, max_points

    def points(self, followed_at: datetime, rising_at: datetime) -> int:
        days = (rising_at - followed_at).days
        return max(0, min(self.cap, days * self.ppd))
