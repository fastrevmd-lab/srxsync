"""Inventory loader — parses YAML into typed dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class InventoryError(ValueError):
    """Raised on malformed or invalid inventory files."""


@dataclass(frozen=True)
class Auth:
    provider: str
    path: str | None = None
    key: str | None = None


@dataclass(frozen=True)
class Device:
    host: str
    auth: Auth


@dataclass(frozen=True)
class Target:
    host: str
    auth: Auth
    exclude: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Inventory:
    source: Device
    targets: list[Target]
    categories: list[str]


def load_inventory(path: Path, *, known_categories: set[str]) -> Inventory:
    """Parse and validate an inventory YAML file."""
    if not path.exists():
        raise InventoryError(f"inventory file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise InventoryError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise InventoryError("inventory root must be a mapping")

    if "source" not in data:
        raise InventoryError("missing required key: source")
    source = _parse_device(data["source"])

    targets = [_parse_target(t) for t in data.get("targets", [])]

    categories = list(data.get("categories", []))
    unknown = [c for c in categories if c not in known_categories]
    if unknown:
        raise InventoryError(f"unknown categories: {unknown}")

    return Inventory(source=source, targets=targets, categories=categories)


def _parse_auth(raw: dict[str, Any]) -> Auth:
    if "provider" not in raw:
        raise InventoryError("auth missing provider")
    return Auth(provider=raw["provider"], path=raw.get("path"), key=raw.get("key"))


def _parse_device(raw: dict[str, Any]) -> Device:
    if "host" not in raw:
        raise InventoryError("device missing host")
    if "auth" not in raw:
        raise InventoryError(f"device {raw.get('host')} missing auth")
    return Device(host=raw["host"], auth=_parse_auth(raw["auth"]))


def _parse_target(raw: dict[str, Any]) -> Target:
    if "host" not in raw:
        raise InventoryError("target missing host")
    if "auth" not in raw:
        raise InventoryError(f"target {raw['host']} missing auth")
    return Target(
        host=raw["host"],
        auth=_parse_auth(raw["auth"]),
        exclude=list(raw.get("exclude", [])),
    )
