"""Drift detection: compare source vs target over a scoped set of XPaths."""

from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

from srxsync.diff import DiffBuilder
from srxsync.zonemap import ZONES_PATH


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
    merged_zones: frozenset[str] = frozenset()

    def diff(self, source: etree._Element, target: etree._Element, host: str = "") -> DriftReport:
        builder = DiffBuilder(paths=self.paths, prune=self.prune)
        src_scoped = builder.build(source)
        tgt_scoped = builder.build(target)
        missing_merged = self._missing_merged_zones(tgt_scoped)
        if ZONES_PATH in self.paths:
            self._drop_slave_only_zones(src_scoped, tgt_scoped)
        self._drop_merged_zones(src_scoped)
        self._drop_merged_zones(tgt_scoped)

        differing: list[str] = []
        for abs_path in self.paths:
            rel = abs_path.removeprefix("/configuration/")
            # A path can match several sibling list entries (e.g. multiple
            # <name-server> elements). Compare the full list in document
            # order — .find() would only ever look at one element and miss
            # drift in any entry that isn't it. Order matters for Junos list
            # categories (e.g. name-server resolution order), so this must
            # not be sorted: a reordered-but-identical-set list is drift.
            src_nodes = [_canonicalize(n) for n in src_scoped.findall(rel)]
            tgt_nodes = [_canonicalize(n) for n in tgt_scoped.findall(rel)]
            zone_missing = abs_path == ZONES_PATH and bool(missing_merged)
            if zone_missing or src_nodes != tgt_nodes:
                differing.append(abs_path)
        return DriftReport(host=host, differing_paths=differing)

    def _missing_merged_zones(self, target_scoped: etree._Element) -> set[str]:
        """N:1 zones are slave-owned: only their existence on the target is checked."""
        present = {
            name.text for name in target_scoped.xpath("security/zones/security-zone/name")
        }
        return set(self.merged_zones) - present

    def _drop_slave_only_zones(
        self, source_scoped: etree._Element, target_scoped: etree._Element
    ) -> None:
        """Ignore zones only the target has: push never deletes zones, so they are unfixable."""
        source_names = {
            name.text for name in source_scoped.xpath("security/zones/security-zone/name")
        }
        for zone in target_scoped.xpath("security/zones/security-zone"):
            if zone.findtext("name") not in source_names:
                zone.getparent().remove(zone)
        if source_scoped.xpath("security/zones"):
            return
        for zones in target_scoped.xpath("security/zones[not(*)]"):
            zones.getparent().remove(zones)

    def _drop_merged_zones(self, scoped: etree._Element) -> None:
        """Remove merged zones' security-zone elements so their content is not compared."""
        for zone in scoped.xpath("security/zones/security-zone"):
            if zone.findtext("name") in self.merged_zones:
                zone.getparent().remove(zone)


def _canonicalize(node: etree._Element) -> bytes:
    result = etree.tostring(node, method="c14n2")
    return bytes(result) if not isinstance(result, bytes) else result
