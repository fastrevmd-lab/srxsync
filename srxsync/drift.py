"""Drift detection: compare source vs target over a scoped set of XPaths."""
from __future__ import annotations
from dataclasses import dataclass, field
from lxml import etree
from srxsync.diff import DiffBuilder


@dataclass(frozen=True)
class DriftReport:
    host: str = ""
    differing_paths: list[str] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        return not self.differing_paths


@dataclass(frozen=True)
class DriftDetector:
    paths: list[str]
    prune: list[str]
    exclude: list[str]

    def diff(
        self, source: etree._Element, target: etree._Element, host: str = ""
    ) -> DriftReport:
        builder = DiffBuilder(paths=self.paths, prune=self.prune, exclude=self.exclude)
        src_scoped = builder.build(source)
        tgt_scoped = builder.build(target)

        differing: list[str] = []
        for abs_path in self.paths:
            if abs_path in self.exclude:
                continue
            rel = abs_path.removeprefix("/configuration/")
            src_node = src_scoped.find(rel)
            tgt_node = tgt_scoped.find(rel)
            if _canonicalize(src_node) != _canonicalize(tgt_node):
                differing.append(abs_path)
        return DriftReport(host=host, differing_paths=differing)


def _canonicalize(node: etree._Element | None) -> bytes:
    if node is None:
        return b""
    return etree.tostring(node, method="c14n2")
