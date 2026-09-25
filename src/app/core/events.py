"""In-process domain event bus. It sits behind a small interface, so a queue can replace it later."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable

log = logging.getLogger("plotline.events")

CLAIM_APPROVED = "claim.approved"
CLAIM_REVOKED = "claim.revoked"
TITLE_ENTERED_RISING = "title.entered_rising"
EPISODE_RELEASED = "episode.released"
POST_VOTED = "post.voted"


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[dict], None]]] = defaultdict(list)

    def subscribe(self, name: str, fn: Callable[[dict], None]) -> None:
        self._subs[name].append(fn)

    def publish(self, name: str, payload: dict) -> None:
        for fn in self._subs.get(name, []):
            fn(payload)  # synchronous: handler errors surface to the caller
