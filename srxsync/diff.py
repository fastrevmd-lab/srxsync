"""Build per-target XML payloads by extracting, pruning, and excluding subtrees."""
from __future__ import annotations
from dataclasses import dataclass
from lxml import etree


@dataclass(frozen=True)
class DiffBuilder:
    paths: list[str]
    prune: list[str]
    exclude: list[str]

    def build(self, source: etree._Element) -> etree._Element:
        out = etree.Element("configuration")
        root = (source if source.tag == "configuration"
                else source.getroottree().getroot())

        for abs_path in self.paths:
            rel = abs_path.removeprefix("/configuration/")
            matches = root.xpath(rel)
            for node in matches:
                copy = etree.fromstring(etree.tostring(node))
                self._apply_prune(copy)
                self._graft(out, abs_path, copy)

        self._apply_excludes(out)
        return out

    def _apply_prune(self, node: etree._Element) -> None:
        for rule in self.prune:
            for victim in node.xpath(rule):
                victim.getparent().remove(victim)

    def _apply_excludes(self, out: etree._Element) -> None:
        for xpath in self.exclude:
            rel = xpath.removeprefix("/configuration/")
            for victim in out.xpath(rel):
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
