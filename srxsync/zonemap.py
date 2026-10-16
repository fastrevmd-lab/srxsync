"""Per-target zone-name translation of a fetched master config."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from lxml import etree

ZONES_PATH = "/configuration/security/zones"

# Leaf-list zone references: (XPath of the parent, child tag holding a zone name).
_ZONE_LISTS = (
    ("security/policies/global/policy/match", "from-zone"),
    ("security/policies/global/policy/match", "to-zone"),
    ("security/nat/*/rule-set/from", "zone"),
    ("security/nat/*/rule-set/to", "zone"),
)


class ZoneTranslationError(ValueError):
    """Raised when a translated config cannot be built for a target."""


@dataclass(frozen=True)
class ZoneTranslator:
    """Rewrites master zone names to a target's zone names (master → slave)."""

    zone_map: dict[str, str]

    def translate(self, zone: str) -> str:
        """Return the slave name for a master zone; unmapped zones keep their name."""
        return self.zone_map.get(zone, zone)

    def apply(self, config: etree._Element) -> etree._Element:
        """Return a translated deep copy of ``config``; the input is never mutated."""
        translated = copy.deepcopy(config)
        if not self.zone_map:
            return translated
        self._rename_zone_lists(translated)
        self._rename_attach_zones(translated)
        self._rename_policy_contexts(translated)
        self._rename_zone_definitions(translated)
        return translated

    def _rename_zone_lists(self, config: etree._Element) -> None:
        for parent_xpath, tag in _ZONE_LISTS:
            for parent in config.xpath(parent_xpath):
                seen: set[str] = set()
                for entry in parent.findall(tag):
                    entry.text = self.translate(entry.text or "")
                    if entry.text in seen:
                        parent.remove(entry)
                        continue
                    seen.add(entry.text)

    def _rename_attach_zones(self, config: etree._Element) -> None:
        for attach in config.xpath("security/address-book/attach"):
            seen: set[str] = set()
            for zone in attach.findall("zone"):
                name = zone.find("name")
                if name is None:
                    continue
                name.text = self.translate(name.text or "")
                if name.text in seen:
                    attach.remove(zone)
                    continue
                seen.add(name.text)

    def _rename_policy_contexts(self, config: etree._Element) -> None:
        for tag in ("from-zone-name", "to-zone-name"):
            for node in config.xpath(f"security/policies/policy/{tag}"):
                node.text = self.translate(node.text or "")

    def _rename_zone_definitions(self, config: etree._Element) -> None:
        for name in config.xpath("security/zones/security-zone/name"):
            name.text = self.translate(name.text or "")
