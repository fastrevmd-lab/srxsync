from pathlib import Path

import pytest
from lxml import etree

from srxsync.zonemap import ZoneTranslationError, ZoneTranslator

FIXTURE = Path(__file__).parent.parent / "fixtures" / "configs" / "zones_master.xml"
APPS_MAP = {"APP1": "APPS", "APP2": "APPS", "APP3": "APPS"}


def _load() -> etree._Element:
    return etree.parse(str(FIXTURE)).getroot()


def _texts(config: etree._Element, xpath: str) -> list[str]:
    return [node.text for node in config.xpath(xpath)]


def test_empty_map_is_identity():
    source = _load()
    translated = ZoneTranslator({}).apply(source)
    assert etree.tostring(translated) == etree.tostring(source)


def test_apply_does_not_mutate_input():
    source = _load()
    before = etree.tostring(source)
    ZoneTranslator(APPS_MAP).apply(source)
    assert etree.tostring(source) == before


def test_translate_unmapped_is_identity():
    translator = ZoneTranslator(APPS_MAP)
    assert translator.translate("APP1") == "APPS"
    assert translator.translate("UNTRUST") == "UNTRUST"


def test_single_pass_no_chaining():
    translator = ZoneTranslator({"A": "B", "B": "C"})
    assert translator.translate("A") == "B"
    assert translator.translate("B") == "C"


def test_one_to_one_rename_everywhere():
    translated = ZoneTranslator({"UNTRUST": "OUTSIDE"}).apply(_load())
    assert "UNTRUST" not in etree.tostring(translated).decode()
    assert _texts(translated, "security/nat/destination/rule-set/from/zone") == ["OUTSIDE"]
    assert "OUTSIDE" in _texts(translated, "security/zones/security-zone/name")


def test_global_policy_zones_renamed_and_deduped():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    match = "security/policies/global/policy/match"
    assert _texts(translated, f"{match}/from-zone") == ["APPS"]
    assert _texts(translated, f"{match}/to-zone") == ["UNTRUST"]


def test_nat_zone_lists_renamed_and_deduped():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    assert _texts(translated, "security/nat/source/rule-set/from/zone") == ["APPS"]
    assert _texts(translated, "security/nat/source/rule-set/to/zone") == ["UNTRUST"]


def test_address_book_attach_renamed_and_deduped():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    assert _texts(translated, "security/address-book/attach/zone/name") == ["APPS"]


def _context_rules(config: etree._Element, from_zone: str, to_zone: str) -> list[str]:
    contexts = [
        ctx
        for ctx in config.xpath("security/policies/policy")
        if ctx.findtext("from-zone-name") == from_zone and ctx.findtext("to-zone-name") == to_zone
    ]
    assert len(contexts) == 1, f"expected one {from_zone}->{to_zone} context, got {len(contexts)}"
    return [rule.findtext("name") for rule in contexts[0].findall("policy")]


def test_collapsed_contexts_concatenated_in_master_order():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    assert _context_rules(translated, "APPS", "UNTRUST") == [
        "app1-web",
        "app2-web",
        "app2-dns",
        "app3-ssh",
    ]


def test_contexts_between_merged_zones_become_intra_zone():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    assert _context_rules(translated, "APPS", "APPS") == ["app1-to-app2"]


def test_duplicate_rule_name_in_merged_context_raises():
    source = _load()
    app3_rule = source.xpath("security/policies/policy[from-zone-name='APP3']/policy/name")[0]
    app3_rule.text = "app1-web"
    with pytest.raises(ZoneTranslationError, match=r"app1-web.*APP1->UNTRUST.*APP3->UNTRUST"):
        ZoneTranslator(APPS_MAP).apply(source)


def test_merged_zones():
    source = _load()
    assert ZoneTranslator(APPS_MAP).merged_zones(source) == frozenset({"APPS"})
    assert ZoneTranslator({"UNTRUST": "OUTSIDE"}).merged_zones(source) == frozenset()


def test_merged_zones_counts_unmapped_master_zone_with_same_name():
    source = _load()
    assert ZoneTranslator({"APP1": "UNTRUST"}).merged_zones(source) == frozenset({"UNTRUST"})


def test_n_to_one_zone_becomes_single_empty_shell():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    apps = translated.xpath("security/zones/security-zone[name='APPS']")
    assert len(apps) == 1
    assert [child.tag for child in apps[0]] == ["name"]


def test_one_to_one_zone_keeps_settings():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    untrust = translated.xpath("security/zones/security-zone[name='UNTRUST']")[0]
    assert untrust.findtext("screen") == "untrust-screen"


def test_unknown_keys():
    source = _load()
    translator = ZoneTranslator({"APP1": "APPS", "NOPE": "APPS"})
    assert translator.unknown_keys(source) == ["NOPE"]


def test_unknown_keys_empty_when_zones_not_fetched():
    config = etree.fromstring("<configuration><security><policies/></security></configuration>")
    assert ZoneTranslator({"NOPE": "APPS"}).unknown_keys(config) == []


def test_merged_zones_ignores_map_keys_absent_on_master():
    translator = ZoneTranslator({"APP1": "APPS", "TYPO": "APPS"})
    assert translator.merged_zones(_load()) == frozenset()
    translated = translator.apply(_load())
    apps = [
        zone
        for zone in translated.xpath("security/zones/security-zone")
        if zone.findtext("name") == "APPS"
    ]
    assert len(apps) == 1
    assert apps[0].find("host-inbound-traffic") is not None


def test_merged_zones_empty_without_master_zones():
    config = etree.fromstring("<configuration><security/></configuration>")
    assert ZoneTranslator(APPS_MAP).merged_zones(config) == frozenset()


def test_apply_maps_into_existing_zone_yields_single_empty_shell():
    translated = ZoneTranslator({"APP1": "UNTRUST"}).apply(_load())
    untrust = [
        zone
        for zone in translated.xpath("security/zones/security-zone")
        if zone.findtext("name") == "UNTRUST"
    ]
    assert len(untrust) == 1
    assert [child.tag for child in untrust[0]] == ["name"]
