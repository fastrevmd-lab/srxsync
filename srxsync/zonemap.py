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

    def merged_zones(self, config: etree._Element) -> frozenset[str]:
        """Slave zones fed by two or more master zones (N:1); their settings stay slave-owned."""
        master_zones = set(_master_zone_names(config))
        preimage_sizes: dict[str, int] = {}
        for master_zone in self.zone_map:
            slave_zone = self.zone_map[master_zone]
            preimage_sizes[slave_zone] = preimage_sizes.get(slave_zone, 0) + 1
        for master_zone in master_zones:
            if master_zone in self.zone_map:
                continue
            if master_zone in preimage_sizes:
                preimage_sizes[master_zone] += 1
        return frozenset(zone for zone, size in preimage_sizes.items() if size >= 2)

    def unknown_keys(self, config: etree._Element) -> list[str]:
        """zone_map keys that are not zones on the master; empty if zones were not fetched."""
        if not config.xpath("security/zones"):
            return []
        master_zones = set(_master_zone_names(config))
        return [key for key in self.zone_map if key not in master_zones]

    def _rename_policy_contexts(self, config: etree._Element) -> None:
        """Rename context zones and merge contexts that collapse onto the same pair."""
        for policies in config.xpath("security/policies"):
            keepers: dict[tuple[str, str], etree._Element] = {}
            # rule name -> "FROM->TO" of the master context it came from, per kept pair
            rule_origins: dict[tuple[str, str], dict[str, str]] = {}
            for context in policies.findall("policy"):
                from_node = context.find("from-zone-name")
                to_node = context.find("to-zone-name")
                if from_node is None or to_node is None:
                    continue
                origin = f"{from_node.text}->{to_node.text}"
                from_node.text = self.translate(from_node.text or "")
                to_node.text = self.translate(to_node.text or "")
                pair = (from_node.text, to_node.text)
                keeper = keepers.get(pair)
                if keeper is None:
                    keepers[pair] = context
                    rule_origins[pair] = {
                        rule.findtext("name") or "": origin for rule in context.findall("policy")
                    }
                    continue
                origins = rule_origins[pair]
                for rule in context.findall("policy"):
                    rule_name = rule.findtext("name") or ""
                    if rule_name in origins:
                        raise ZoneTranslationError(
                            f"duplicate policy {rule_name} in merged context "
                            f"{pair[0]}->{pair[1]}: from {origins[rule_name]} and {origin}"
                        )
                    origins[rule_name] = origin
                    keeper.append(rule)
                policies.remove(context)

    def _rename_zone_definitions(self, config: etree._Element) -> None:
        """Rename 1:1 zones; reduce N:1 zones to one empty shell (settings stay slave-owned)."""
        merged = self.merged_zones(config)
        for zones in config.xpath("security/zones"):
            shells_written: set[str] = set()
            for zone in zones.findall("security-zone"):
                name = zone.find("name")
                if name is None:
                    continue
                slave_name = self.translate(name.text or "")
                if slave_name not in merged:
                    name.text = slave_name
                    continue
                if slave_name in shells_written:
                    zones.remove(zone)
                    continue
                shell = etree.Element("security-zone")
                etree.SubElement(shell, "name").text = slave_name
                zones.replace(zone, shell)
                shells_written.add(slave_name)


def _master_zone_names(config: etree._Element) -> list[str]:
    return [name.text or "" for name in config.xpath("security/zones/security-zone/name")]
