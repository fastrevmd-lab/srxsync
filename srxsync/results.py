"""Result types for push and check runs."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TargetResult:
    host: str
    ok: bool
    error: str | None = None
    duration_s: float = 0.0


@dataclass(frozen=True)
class PushSummary:
    results: list[TargetResult] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(r.ok for r in self.results)


@dataclass(frozen=True)
class DriftLine:
    host: str
    in_sync: bool
    differing_paths: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class DriftSummary:
    reports: list[DriftLine] = field(default_factory=list)

    @property
    def all_in_sync(self) -> bool:
        return all(r.in_sync for r in self.reports)
