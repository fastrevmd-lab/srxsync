"""Warn about slave zones that srxsync creates or references but that carry no interfaces."""

from __future__ import annotations

from lxml import etree

_SPECIAL_ZONES = frozenset({"junos-host", "any"})

_REFERENCE_XPATHS = (
    "security/policies/policy/from-zone-name",
    "security/policies/policy/to-zone-name",
    "security/policies/global/policy/match/from-zone",
    "security/policies/global/policy/match/to-zone",
    "security/nat/*/rule-set/from/zone",
    "security/nat/*/rule-set/to/zone",
    "security/address-book/attach/zone/name",
)


def zone_warnings(
    payload: etree._Element, target_config: etree._Element, host: str
) -> list[str]:
    """Return warnings for payload zones that are new, empty, or missing on the target."""
    defined_in_payload = set(_zone_names(payload))
    referenced = set(defined_in_payload)
    for xpath in _REFERENCE_XPATHS:
        referenced.update(node.text or "" for node in payload.xpath(xpath))
    referenced -= _SPECIAL_ZONES
    referenced.discard("")

    target_has_interfaces = {
        zone.findtext("name") or "": zone.find("interfaces") is not None
        for zone in target_config.xpath("security/zones/security-zone")
    }

    warnings: list[str] = []
    for zone in sorted(referenced):
        warning = _warning_for(zone, host, target_has_interfaces, defined_in_payload)
        if warning is not None:
            warnings.append(warning)
    return warnings


def _warning_for(
    zone: str,
    host: str,
    target_has_interfaces: dict[str, bool],
    defined_in_payload: set[str],
) -> str | None:
    hint = (
        "bind an interface on the slave "
        f"(set security zones security-zone {zone} interfaces <ifl>)"
    )
    if zone in target_has_interfaces:
        if target_has_interfaces[zone]:
            return None
        return f"{host}: zone {zone} exists with no interfaces — {hint}"
    if zone in defined_in_payload:
        return f"{host}: creating zone {zone} with no interfaces — {hint}"
    return (
        f'{host}: zone {zone} is referenced but missing on the slave — add "zones" to include '
        "or create it"
    )


def _zone_names(config: etree._Element) -> list[str]:
    return [name.text or "" for name in config.xpath("security/zones/security-zone/name")]
