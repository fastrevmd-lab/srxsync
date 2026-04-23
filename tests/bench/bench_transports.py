"""Wall-time benchmark: PyEZ vs rustez transport backends.

Reads `inv.yaml` from the current working directory and expects
credentials in the environment (typically populated by sourcing
`~/.srxsync.env`, the same convention used by the integration suite).

Two operations are measured:
  * fetch (20 iterations per backend) — connect, fetch union of all
    target include categories from the source device, close.
  * push  ( 3 iterations per backend) — full merge-push cycle against
    targets[0] with commit-confirmed 1 minute.

Results are printed as a markdown table to stdout. Nothing is written
to disk. See docs/superpowers/specs/2026-04-23-transport-benchmark-design.md
for the rationale behind every knob.

IMPORTANT: Do not run this against production. It mutates the push
target (merge, then commit-confirmed with a 60 s rollback window).
"""

from __future__ import annotations

import sys
from pathlib import Path

from srxsync.categories import CategoryModel
from srxsync.inventory import Inventory, load_inventory


def load_config(inventory_path: Path = Path("inv.yaml")) -> tuple[Inventory, CategoryModel, list[str]]:
    """Load inventory + categories, resolve the fetch include-union.

    Returns:
        (inventory, category_model, union_paths) where union_paths is the
        deduped list of XPath strings that the source device must yield
        to satisfy every target's include list. Same union used by
        Orchestrator.__init__.
    """
    categories = CategoryModel.default()
    inventory = load_inventory(inventory_path, known_categories=categories.known_names())
    union_names: list[str] = []
    seen: set[str] = set()
    for target in inventory.targets:
        for name in target.include:
            if name not in seen:
                union_names.append(name)
                seen.add(name)
    union_paths, _ = categories.resolve(union_names)
    return inventory, categories, union_paths


def main() -> int:
    inventory, _, union_paths = load_config()
    print(f"bench_transports: source={inventory.source.host}")
    print(f"bench_transports: push target={inventory.targets[0].host}")
    print(f"bench_transports: union includes {len(union_paths)} path(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
