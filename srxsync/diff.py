"""Build per-target XML payloads by extracting and pruning subtrees."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from lxml import etree


@dataclass(frozen=True)
class DiffBuilder:
    paths: list[str]
    prune: list[str]

    def build(
        self, source: etree._Element, mode: Literal["merge", "replace"] = "merge"
    ) -> etree._Element:
        out = etree.Element("configuration")
        root = source if source.tag == "configuration" else source.getroottree().getroot()

        for abs_path in self.paths:
            rel = abs_path.removeprefix("/configuration/")
            matches = root.xpath(rel)
            for node in matches:
                copy = etree.fromstring(etree.tostring(node))
                self._apply_prune(copy)
                self._graft(out, abs_path, copy)

        if mode == "replace":
            self._mark_replace(out)
        return out

    def _mark_replace(self, out: etree._Element) -> None:
        """Add replace="replace" attribute on each category-root element.

        For each configured path like /configuration/security/policies, find
        the element at that path in the payload and set replace="replace".
        Junos then replaces that subtree wholesale on the target device — the
        semantic users expect from --replace.
        """
        for abs_path in self.paths:
            rel = abs_path.removeprefix("/configuration/")
            for node in out.xpath(rel):
                node.set("replace", "replace")

    def _apply_prune(self, node: etree._Element) -> None:
        for rule in self.prune:
            for victim in node.xpath(rule):
                victim.getparent().remove(victim)

    def _graft(self, out: etree._Element, abs_path: str, node: etree._Element) -> None:
        parts = abs_path.removeprefix("/configuration/").split("/")
        parent = out
        for part in parts[:-1]:
            child = parent.find(part)
            if child is None:
                child = etree.SubElement(parent, part)
            parent = child
        existing = parent.find(node.tag)
        if existing is not None:
            parent.remove(existing)
        parent.append(node)
