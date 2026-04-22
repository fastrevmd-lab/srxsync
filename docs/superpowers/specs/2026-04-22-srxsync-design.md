# srxsync — Design Spec

**Date:** 2026-04-22
**Status:** Approved, ready for implementation planning

## Purpose

A Python CLI that keeps a fleet of Juniper SRX firewalls in sync with a designated master SRX. It reads selected configuration sections from the master and pushes them to a list of target SRXs, with safety rails (commit-confirmed), drift detection, and per-target overrides.

## Scope — what gets synced

Data-driven category registry. Each category maps to one or more Junos config paths. The v1 category list:

| Category | Junos paths |
|---|---|
| `objects` | `security address-book`, `applications`, `applications application-set` |
| `policies` | `security policies` |
| `nat` | `security nat source`, `security nat destination`, `security nat static` |
| `qos` | `class-of-service` |
| `zones` | `security zones` **minus** `security-zone/*/interfaces` (interface bindings are device-specific) |

**Extensibility:** categories live in a YAML registry shipped with the tool. Adding NTP, SNMP, or any other hierarchy is a YAML edit, not a code change.

**Explicitly excluded from sync:** `interfaces`, `routing-options`, `protocols`, `system`, `chassis`, and zone-to-interface bindings. These are device-specific and never cross-synced.

## CLI

```
srxsync push  --inventory inv.yaml (--replace | --merge)
              [--commit-confirmed N] [--max-parallel N]
              [--on-error continue|abort] [--dry-run]

srxsync check --inventory inv.yaml [--verbose]
```

Flag semantics:

- `--replace` / `--merge`: mutually exclusive, required for `push`. Controls Junos load mode.
- `--commit-confirmed N`: commit with N-minute auto-rollback timer; `confirm()` seals it. Default: 5.
- `--max-parallel N`: concurrent target workers. Default: 5.
- `--on-error continue|abort`: on per-target failure, continue (default, exit non-zero at end) or cancel remaining work.
- `--dry-run`: fetch + compute per-target payload, print what would change, do not load or commit.
- `check`: read-only drift detection; no `load`, no `commit`. Exit 0 if all in sync.
- `--verbose` (with `check`): show per-category XML diff for drifted targets.

## Inventory format

```yaml
source:
  host: srx-master.example.net
  auth: { provider: vault, path: secret/srx/master }

targets:
  - host: srx-site-a.example.net
    auth: { provider: keyring, key: srx-site-a }
    exclude: []
  - host: srx-site-b.example.net
    auth: { provider: netrc }
    exclude:
      - /configuration/security/nat/static/rule[name="SITE_B_LOCAL"]

categories: [objects, policies, nat, qos, zones]
```

Per-target `exclude` is a list of Junos XPath expressions. Excluded subtrees are pruned from the payload before push, so the target's existing config at those paths is preserved.

**Credentials** are never in the inventory file. `auth.provider` selects a `SecretProvider`:
- `vault` — HashiCorp Vault at `auth.path`
- `keyring` — OS keyring at `auth.key`
- `netrc` — `~/.netrc` lookup by `host`
- `env` — env vars (e.g., `SRX_PASSWORD_<HOST>`)
- SSH key auth is always attempted first regardless of provider.

## Architecture

```
┌─────────────┐
│   CLI       │  argparse, subcommands: push | check
└──────┬──────┘
       │
┌──────▼──────────────────────────────────────────────────┐
│   Orchestrator                                          │
│   - loads inventory + categories + secrets              │
│   - fetches source config once                          │
│   - schedules per-target work (concurrency-capped)      │
└──────┬──────────────────────────────────────────────────┘
       │
┌──────▼──────┐  ┌───────────┐  ┌───────────────┐  ┌─────────────────┐
│CategoryModel│  │DiffBuilder│  │ DriftDetector │  │ Transport (ABC) │
│ data-driven │  │per-target │  │ source-vs-    │  │  ┌───PyEZImpl──┐│
│ paths +     │  │ payload   │  │ target diff   │  │  └─────────────┘│
│ prune rules │  │ compute   │  │               │  │ (Rust impl: P2) │
└─────────────┘  └───────────┘  └───────────────┘  └─────────────────┘
       │              │                │                   │
       └──────────────┴── SecretProvider ──────────────────┘
```

### Components

1. **CLI** (`srxsync/cli.py`) — argparse, validation, builds `RunConfig`, hands off to Orchestrator.
2. **Inventory** (`srxsync/inventory.py`) — parses YAML into typed dataclasses: `Inventory(source, targets, categories)`.
3. **CategoryModel** (`srxsync/categories.py`) — loads category registry YAML, resolves category names → `(paths, prune_rules)`.
4. **Transport** (`srxsync/transport/base.py`) — abstract interface:
   ```python
   class Transport(ABC):
       def connect(self, host, secret): ...
       def fetch(self, paths: list[str]) -> Element: ...
       def load(self, xml: Element, mode: Literal["replace","merge"]): ...
       def commit_confirmed(self, minutes: int) -> None: ...
       def confirm(self) -> None: ...
       def rollback(self) -> None: ...
       def close(self) -> None: ...
   ```
   `PyEZTransport` (`srxsync/transport/pyez.py`) is the v1 concrete implementation, wrapping `jnpr.junos.Device` + `Config`. Rust backend is a phase-2 drop-in implementing the same interface.
5. **DiffBuilder** (`srxsync/diff.py`) — given source XML, category prune rules, and target-specific excludes, produces the XML payload for `transport.load()`.
6. **DriftDetector** (`srxsync/drift.py`) — given source XML (post-prune+exclude) and target XML (same scope), produces a `DriftReport` listing differing categories.
7. **Orchestrator** (`srxsync/orchestrator.py`) — two entry points: `push()` and `check()`. Manages source fetch, concurrency, per-target lifecycle, error aggregation, exit code.
8. **SecretProvider** (`srxsync/secrets/`) — pluggable: `vault.py`, `keyring.py`, `netrc.py`, `env.py`.

### Rust-backend plan (phase 2)

Out of scope for v1 implementation, but the `Transport` interface is designed to accommodate it. Phase-2 options, in order of preference:
1. **Subprocess wrapper** — invoke user's `rustEZ`/`rustnetconf` CLI, parse structured output (JSON).
2. **PyO3 bindings** — if/when rustEZ exposes a Python module via maturin.

## Data flow

### Push run

1. CLI parses, builds `RunConfig`.
2. Orchestrator loads `Inventory` + `CategoryModel`.
3. Resolves category paths (union across all configured categories).
4. Connects to source via `PyEZTransport`, fetches `source_xml` once.
5. Closes source connection.
6. Creates `asyncio.Semaphore(max_parallel)`; fans out per-target workers.
7. Per target:
   a. Acquire semaphore.
   b. `DiffBuilder.build(source_xml, prune, target.exclude)` → `payload`.
   c. `PyEZTransport.connect(target.host, secret)`.
   d. `transport.load(payload, mode=replace|merge)`.
   e. `transport.commit_confirmed(N)`.
   f. `transport.confirm()`.
   g. `transport.close()`.
   h. Record `TargetResult(ok=True)`.

   On any exception in b–g: best-effort `rollback()` + `close()`, record `TargetResult(ok=False, err=...)`. If `--on-error abort`, cancel remaining workers.
8. Print summary table.
9. Exit 0 only if every target reported `ok=True`.

### Check run

1. Same source fetch as push.
2. Per target: connect (read-only), fetch target config for same paths, close.
3. `DriftDetector.diff(source_scoped, target_scoped)` → `DriftReport`.
4. Print report:
   ```
   Drift report:
     srx-site-a   IN SYNC
     srx-site-b   DRIFT   (3 differences: policies, nat.static, applications)
     srx-site-c   IN SYNC
   ```
5. `--verbose`: print per-category XML diff for drifted targets.
6. Exit 0 if all in sync, non-zero if any drift.

## Error handling

| Class | Example | Behavior |
|---|---|---|
| Pre-flight | bad YAML, missing secret, unknown category | Fail fast, exit non-zero, no device touched |
| Source fetch | can't reach master SRX | Fail fast, exit non-zero (nothing to push) |
| Per-target | connect, load, commit, timeout | Isolated per target; governed by `--on-error` |

**Guarantees:**

1. **No partial commits.** Every `load` is paired with `commit confirmed` + `confirm`. Script crash or network drop between them → SRX auto-rolls back after timer expires. This is the primary safety mechanism.
2. **Per-target isolation.** One target's failure never affects another target's session (separate `Transport` instances).
3. **Best-effort cleanup.** On exception, attempt `rollback()` + `close()`; swallow cleanup errors to preserve the original error.
4. **Honest exit code.** Exit 0 only if every target succeeded. `--on-error continue` does not mask failures in exit code.

**Explicit non-goals for v1:**

- No automatic retry on transient failures — user re-runs; sync is idempotent.
- No cross-target transactionality (no "all commit or none" across the fleet).
- No recovery from script crash *after* `confirm()` on some targets but not others — unconfirmed targets auto-rollback; confirmed ones stay; user re-runs.

## Testing

No mocked tests. Two layers:

**Layer 1 — Unit tests on pure logic**
Pure data-transformation code only. Real SRX XML fixtures live in `tests/fixtures/configs/` (captured from vSRX lab).

- `Inventory` YAML parsing (valid, malformed, missing fields, unknown category)
- `CategoryModel` path/prune-rule resolution
- `DiffBuilder` output vs golden-file fixtures
- `DriftDetector` output vs golden-file fixtures

**Layer 2 — Integration tests against real vSRX lab**

Topology: 1 master + 2 slave vSRXs (user provides connection details when implementation reaches testable state).

Test cases:

- `check` reports in-sync when slaves match master.
- Intentional drift on slave-1 → `check` detects it.
- `--merge` sync makes slave-1 match master; re-check passes.
- `--replace` wipes a slave-specific change not in exclude list.
- `--replace` with `exclude:` entry preserves the excluded path.
- `commit confirmed 1` + script kill mid-run → SRX auto-rolls back after 1 minute.
- `--on-error continue` with one unreachable slave → other slave completes, exit non-zero.
- `--max-parallel 2` actually pushes concurrently (timing assertion).

Tests live in `tests/integration/`; use `pytest`. Lab connection details loaded from env or `tests/lab.yaml` (gitignored).

**Lab setup checkpoint:** at first testable implementation phase, pause and request master + 2 slave IP/credentials from the user before writing integration tests.

## File/module layout

```
srxmaster/
├── srxsync/
│   ├── __init__.py
│   ├── cli.py
│   ├── orchestrator.py
│   ├── inventory.py
│   ├── categories.py
│   ├── diff.py
│   ├── drift.py
│   ├── transport/
│   │   ├── __init__.py
│   │   ├── base.py          # Transport ABC
│   │   └── pyez.py          # PyEZTransport
│   ├── secrets/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── vault.py
│   │   ├── keyring.py
│   │   ├── netrc.py
│   │   └── env.py
│   └── data/
│       └── categories.yaml  # default registry
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/configs/
├── docs/
├── pyproject.toml
└── README.md
```

## Dependencies

- `junos-eznc` (PyEZ)
- `lxml` (XML manipulation, XPath)
- `PyYAML`
- `keyring` (optional, for keyring provider)
- `hvac` (optional, for Vault provider)
- `pytest` (dev)

Python 3.11+.

## Open questions / deferred

- Phase-2 Rust backend concrete impl (subprocess vs PyO3).
- Additional categories beyond v1 (NTP, SNMP, and whatever else the user adds to the registry).
- Snapshot-to-file mode — deferred per user preference; live-only in v1.
