from pathlib import Path

import pytest

from srxsync.inventory import Inventory, InventoryError, load_inventory

FIXTURES = Path(__file__).parent.parent / "fixtures" / "inventory"
KNOWN_CATEGORIES = {
    "objects",
    "policies",
    "nat",
    "qos",
    "zones",
    "name-servers",
    "ntp",
    "syslog",
    "domain-name",
    "time-zone",
}


def test_load_valid_inventory():
    inv = load_inventory(FIXTURES / "valid.yaml", known_categories=KNOWN_CATEGORIES)
    assert isinstance(inv, Inventory)
    assert inv.source.host == "srx-master.example.net"
    assert inv.source.auth.provider == "env"
    assert len(inv.targets) == 2
    assert inv.targets[0].host == "srx-a.example.net"
    assert inv.targets[0].include == [
        "objects",
        "policies",
        "nat",
        "qos",
        "zones",
        "name-servers",
        "ntp",
        "syslog",
        "domain-name",
        "time-zone",
    ]
    assert inv.targets[1].include == ["policies"]


def test_missing_source_raises():
    with pytest.raises(InventoryError, match="source"):
        load_inventory(FIXTURES / "missing_source.yaml", known_categories=KNOWN_CATEGORIES)


def test_unknown_category_raises():
    with pytest.raises(InventoryError, match="not_a_real_category"):
        load_inventory(FIXTURES / "unknown_category.yaml", known_categories=KNOWN_CATEGORIES)


def test_missing_file_raises():
    with pytest.raises(InventoryError, match="not found"):
        load_inventory(FIXTURES / "does_not_exist.yaml", known_categories=KNOWN_CATEGORIES)


def test_zone_map_parsed():
    inv = load_inventory(FIXTURES / "zone_map.yaml", known_categories=KNOWN_CATEGORIES)
    assert inv.targets[0].zone_map == {"APP1": "APPS", "APP2": "APPS", "APP3": "APPS"}


def test_zone_map_defaults_empty():
    inv = load_inventory(FIXTURES / "zone_map.yaml", known_categories=KNOWN_CATEGORIES)
    assert inv.targets[1].zone_map == {}


def test_zone_map_must_be_mapping():
    with pytest.raises(InventoryError, match="zone_map must be a mapping"):
        load_inventory(FIXTURES / "zone_map_bad.yaml", known_categories=KNOWN_CATEGORIES)


@pytest.mark.parametrize("bad_map", [{"APP1": ""}, {"": "APPS"}, {"APP1": 5}, {"APP1": None}])
def test_zone_map_entries_must_be_non_empty_strings(tmp_path, bad_map):
    import yaml

    doc = {
        "source": {"host": "m", "auth": {"provider": "env"}},
        "targets": [
            {"host": "t", "auth": {"provider": "env"}, "include": ["policies"], "zone_map": bad_map}
        ],
    }
    inv_file = tmp_path / "inv.yaml"
    inv_file.write_text(yaml.safe_dump(doc))
    with pytest.raises(InventoryError, match="zone_map entries must be non-empty strings"):
        load_inventory(inv_file, known_categories=KNOWN_CATEGORIES)
