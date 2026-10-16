from pathlib import Path

from lxml import etree

from srxsync.zonemap import ZoneTranslator

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
