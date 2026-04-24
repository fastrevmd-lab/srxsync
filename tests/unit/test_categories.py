import pytest

from srxsync.categories import CategoryError, CategoryModel


def test_default_registry_loads():
    model = CategoryModel.default()
    assert set(model.known_names()) == {
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


def test_resolve_name_servers():
    model = CategoryModel.default()
    paths, prunes = model.resolve(["name-servers"])
    assert paths == ["/configuration/system/name-server"]
    assert prunes == []


def test_resolve_ntp():
    model = CategoryModel.default()
    paths, prunes = model.resolve(["ntp"])
    assert paths == ["/configuration/system/ntp"]
    assert prunes == []


def test_resolve_syslog():
    model = CategoryModel.default()
    paths, prunes = model.resolve(["syslog"])
    assert paths == ["/configuration/system/syslog"]
    assert prunes == []


def test_resolve_domain_name():
    model = CategoryModel.default()
    paths, prunes = model.resolve(["domain-name"])
    assert paths == ["/configuration/system/domain-name"]
    assert prunes == []


def test_resolve_time_zone():
    model = CategoryModel.default()
    paths, prunes = model.resolve(["time-zone"])
    assert paths == ["/configuration/system/time-zone"]
    assert prunes == []


def test_resolve_single_category():
    model = CategoryModel.default()
    paths, prunes = model.resolve(["policies"])
    assert paths == ["/configuration/security/policies"]
    assert prunes == []


def test_resolve_zones_has_prune():
    model = CategoryModel.default()
    paths, prunes = model.resolve(["zones"])
    assert paths == ["/configuration/security/zones"]
    assert prunes == ["security-zone/interfaces"]


def test_resolve_multiple_dedups_paths():
    model = CategoryModel.default()
    paths, _ = model.resolve(["objects", "policies"])
    assert len(paths) == 3


def test_resolve_unknown_raises():
    model = CategoryModel.default()
    with pytest.raises(CategoryError, match="unknown"):
        model.resolve(["not_a_category"])
