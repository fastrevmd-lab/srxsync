from pathlib import Path

from lxml import etree

from srxsync.diff import DiffBuilder

FIXTURE = Path(__file__).parent.parent / "fixtures" / "configs" / "source_minimal.xml"


def _load() -> etree._Element:
    return etree.parse(str(FIXTURE)).getroot()


def test_single_path_extract():
    src = _load()
    builder = DiffBuilder(paths=["/configuration/security/policies"], prune=[], exclude=[])
    out = builder.build(src)
    assert out.tag == "configuration"
    assert out.find(".//policies") is not None
    assert out.find(".//address-book") is None


def test_prune_strips_interface_bindings():
    src = _load()
    builder = DiffBuilder(
        paths=["/configuration/security/zones"],
        prune=["security-zone/interfaces"],
        exclude=[],
    )
    out = builder.build(src)
    zones = out.find(".//zones")
    assert zones is not None
    assert zones.find(".//security-zone/interfaces") is None
    assert zones.find(".//security-zone/host-inbound-traffic") is not None


def test_target_exclude_removes_matching_rule():
    src = _load()
    builder = DiffBuilder(
        paths=["/configuration/security/nat"],
        prune=[],
        exclude=['/configuration/security/nat/static/rule-set/rule[name="SITE_LOCAL"]'],
    )
    out = builder.build(src)
    rules = out.findall(".//rule")
    names = [r.find("name").text for r in rules]
    assert "SITE_LOCAL" not in names
    assert "COMMON" in names


def test_multiple_paths_all_included():
    src = _load()
    builder = DiffBuilder(
        paths=[
            "/configuration/security/policies",
            "/configuration/security/nat",
        ],
        prune=[],
        exclude=[],
    )
    out = builder.build(src)
    assert out.find(".//policies") is not None
    assert out.find(".//nat") is not None
