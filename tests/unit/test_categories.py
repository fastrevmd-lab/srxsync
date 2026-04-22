from srxsync.categories import CategoryModel, CategoryError
import pytest


def test_default_registry_loads():
    model = CategoryModel.default()
    assert set(model.known_names()) == {"objects", "policies", "nat", "qos", "zones"}


def test_resolve_single_category():
    model = CategoryModel.default()
    paths, prunes = model.resolve(["policies"])
    assert paths == ["/configuration/security/policies"]
    assert prunes == []


def test_resolve_zones_has_prune():
    model = CategoryModel.default()
    paths, prunes = model.resolve(["zones"])
    assert paths == ["/configuration/security/zones"]
    assert prunes == ["security-zone/*/interfaces"]


def test_resolve_multiple_dedups_paths():
    model = CategoryModel.default()
    paths, _ = model.resolve(["objects", "policies"])
    assert len(paths) == 3


def test_resolve_unknown_raises():
    model = CategoryModel.default()
    with pytest.raises(CategoryError, match="unknown"):
        model.resolve(["not_a_category"])
