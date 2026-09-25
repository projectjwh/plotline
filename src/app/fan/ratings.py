"""RatingAggregator: how fan votes become the displayed fan rating. Replaceable from config.

IMDb publishes a weighted rating rather than a raw mean, to resist vote manipulation
(IMDb Help, "The vote average for film X should be Y"). Plotline shows its weighting
openly: a Bayesian mean that pulls titles with few votes toward a prior, alongside
the raw mean, the vote count and the histogram.
"""
from __future__ import annotations

from typing import Iterable, Protocol

from src.app.core.registry import Registry

rating_aggregators = Registry("rating aggregator")


class RatingAggregator(Protocol):
    def aggregate(self, scores: Iterable[int]) -> dict: ...


@rating_aggregators.register("bayesian")
class BayesianAggregator:
    def __init__(self, prior_mean: float, prior_weight: float):
        self.m, self.c = prior_mean, prior_weight

    def aggregate(self, scores: Iterable[int]) -> dict:
        s = list(scores)
        n = len(s)
        hist = {str(k): 0 for k in range(1, 11)}
        for x in s:
            hist[str(x)] += 1
        mean = sum(s) / n if n else None
        weighted = (self.c * self.m + sum(s)) / (self.c + n) if n else None
        return {"weighted": round(weighted, 2) if weighted is not None else None,
                "mean": round(mean, 2) if mean is not None else None, "votes": n, "histogram": hist,
                "method": f"bayesian(prior_mean={self.m}, prior_weight={self.c})"}
