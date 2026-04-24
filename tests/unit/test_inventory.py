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
