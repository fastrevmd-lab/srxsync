from lxml import etree

from srxsync.zonewarn import zone_warnings

BIND_HINT = (
    "bind an interface on the slave "
    "(set security zones security-zone {zone} interfaces <ifl>)"
)


def _xml(text: str) -> etree._Element:
    return etree.fromstring(text)


TARGET = _xml(
    "<configuration><security><zones>"
    "<security-zone><name>UNTRUST</name>"
    "<interfaces><name>ge-0/0/0.0</name></interfaces></security-zone>"
    "<security-zone><name>EMPTY</name></security-zone>"
    "</zones></security></configuration>"
)


def test_creating_zone_warns():
    payload = _xml(
        "<configuration><security><zones>"
        "<security-zone><name>APPS</name></security-zone>"
        "</zones></security></configuration>"
    )
    assert zone_warnings(payload, TARGET, host="srx-a") == [
        f"srx-a: creating zone APPS with no interfaces — {BIND_HINT.format(zone='APPS')}"
    ]


def test_existing_zone_without_interfaces_warns():
    payload = _xml(
        "<configuration><security><policies><policy>"
        "<from-zone-name>EMPTY</from-zone-name><to-zone-name>UNTRUST</to-zone-name>"
        "</policy></policies></security></configuration>"
    )
    assert zone_warnings(payload, TARGET, host="srx-a") == [
        f"srx-a: zone EMPTY exists with no interfaces — {BIND_HINT.format(zone='EMPTY')}"
    ]


def test_zone_with_interfaces_is_silent():
    payload = _xml(
        "<configuration><security><nat><source><rule-set><name>rs</name>"
        "<to><zone>UNTRUST</zone></to></rule-set></source></nat></security></configuration>"
    )
    assert zone_warnings(payload, TARGET, host="srx-a") == []


def test_referenced_but_missing_zone_warns():
    payload = _xml(
        "<configuration><security><policies><global><policy><name>g</name><match>"
        "<from-zone>APPS</from-zone><to-zone>UNTRUST</to-zone>"
        "</match></policy></global></policies></security></configuration>"
    )
    assert zone_warnings(payload, TARGET, host="srx-a") == [
        'srx-a: zone APPS is referenced but missing on the slave — add "zones" to include '
        "or create it"
    ]


def test_special_zones_ignored():
    payload = _xml(
        "<configuration><security><policies><policy>"
        "<from-zone-name>junos-host</from-zone-name><to-zone-name>UNTRUST</to-zone-name>"
        "</policy></policies></security></configuration>"
    )
    assert zone_warnings(payload, TARGET, host="srx-a") == []
