"""Data-driven Junos config-path registry."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import yaml


class CategoryError(ValueError):
    """Raised on unknown categories or malformed registry."""


@dataclass(frozen=True)
class Category:
    name: str
    paths: tuple[str, ...]
    prune: tuple[str, ...]


class CategoryModel:
    def __init__(self, categories: dict[str, Category]) -> None:
        self._categories = categories

    @classmethod
    def default(cls) -> CategoryModel:
        registry = files("srxsync.data").joinpath("categories.yaml").read_text()
        return cls._from_yaml(registry)

    @classmethod
    def from_file(cls, path: Path) -> CategoryModel:
        return cls._from_yaml(path.read_text())

    @classmethod
    def _from_yaml(cls, text: str) -> CategoryModel:
        raw = yaml.safe_load(text)
        if not isinstance(raw, dict):
            raise CategoryError("registry root must be a mapping")
        cats: dict[str, Category] = {}
        for name, entry in raw.items():
            paths = tuple(entry.get("paths", []))
            prune = tuple(entry.get("prune", []))
            if not paths:
                raise CategoryError(f"category {name} has no paths")
            cats[name] = Category(name=name, paths=paths, prune=prune)
        return cls(cats)

    def known_names(self) -> set[str]:
        return set(self._categories.keys())

    def resolve(self, names: list[str]) -> tuple[list[str], list[str]]:
        """Return (deduped paths, prune rules) for the given category names."""
        paths: list[str] = []
        prunes: list[str] = []
        seen: set[str] = set()
        for name in names:
            if name not in self._categories:
                raise CategoryError(f"unknown category: {name}")
            cat = self._categories[name]
            for p in cat.paths:
                if p not in seen:
                    paths.append(p)
                    seen.add(p)
            prunes.extend(cat.prune)
        return paths, prunes
