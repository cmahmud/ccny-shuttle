"""Idempotent, checkpointed ingestion of authorized GPS data."""
from dataclasses import dataclass
from .samsara import SamsaraFeed
from .storage import ObservationStore


@dataclass(frozen=True, slots=True)
class PollResult:
    pages: int
    received: int
    inserted: int


class Collector:
    def __init__(
        self, feed: SamsaraFeed, store: ObservationStore, max_pages: int = 50
    ) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self.feed = feed
        self.store = store
        self.max_pages = max_pages

    def poll(self) -> PollResult:
        cursor = self.store.get_cursor("samsara")
        pages = received = inserted = 0
        while pages < self.max_pages:
            page = self.feed.fetch(cursor)
            if page.has_next_page and page.end_cursor == cursor:
                raise RuntimeError("Feed failed to advance its cursor")
            count = self.store.commit_page("samsara", page.observations, page.end_cursor)
            received += len(page.observations)
            inserted += count
            pages += 1
            cursor = page.end_cursor
            if not page.has_next_page:
                break
        return PollResult(pages, received, inserted)
