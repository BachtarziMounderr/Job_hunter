"""Small connector contract; partial failures remain visible to the pipeline."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class CollectionResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    pages_fetched: int = 0
    malformed_records: int = 0
    truncated: bool = False
    error: str | None = None


class Collector(Protocol):
    name: str

    def collect(self) -> CollectionResult:
        """Return collected records and explicit source failure information."""
        ...
