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


def main() -> int:
    print("bench_transports: scaffold only, no work done yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
