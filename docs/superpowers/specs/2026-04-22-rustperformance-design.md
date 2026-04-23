# rustperformance — dual-backend transport for srxsync

**Date:** 2026-04-22
**Branch:** `rustperformance`
**Status:** Design approved, ready for implementation plan

## Goal

Add a `RustezTransport` alongside the existing `PyEZTransport` so srxsync can
optionally drive devices through the Rust-native `rustez` library. PyEZ
remains the default; rustez is a runtime-selectable alternative for
performance-sensitive runs and to exercise the Rust stack in production.

## Non-goals

- Replacing or removing `PyEZTransport`. Both backends ship long-term.
- Changing inventory, diff, drift, secrets, or orchestrator semantics.
- Benchmarking rustez vs PyEZ in this branch. Perf claims are out of
  scope; correctness parity is the bar.
- Making rustez a hard dependency. Base install stays lean.

## Architecture

```
CLI --transport {pyez,rustez}
      │
      ▼
make_transport(name) ──► PyEZTransport | RustezTransport
                                │
                                ▼
                      Orchestrator (unchanged)
```

A single new seam: a `make_transport(name)` factory in
`srxsync/transport/__init__.py`. Everything downstream of `Orchestrator`
(Diff, Drift, secrets, inventory) is untouched.

## Files changed

| File | Change |
|---|---|
| `srxsync/transport/__init__.py` | Add `make_transport(name) -> type[Transport]` and `KNOWN_TRANSPORTS = ("pyez", "rustez")`. |
| `srxsync/transport/rustez.py` | **New.** `RustezTransport(Transport)` implementing the 7 ABC methods against `rustez.Device` + `rustez.Config`. |
| `srxsync/transport/base.py` | Default `port` parameter changes from 22 to 830 (NETCONF default). Verified in-lab before flipping; see "Port default change" below. |
| `srxsync/transport/pyez.py` | No change expected — PyEZ honors whatever `port` is passed. |
| `srxsync/cli.py` | Add `--transport {pyez,rustez}` (default `pyez`) to both `push` and `check` subparsers. Pass to `Orchestrator` as `transport_factory=make_transport(name)`. |
| `srxsync/orchestrator.py` | No behavior change — `transport_factory` already injectable. |
| `pyproject.toml` | Add `rust = ["rustez>=0.8.2"]` under `[project.optional-dependencies]`. |
| `README.md` | Document `--transport` flag and `pip install -e .[rust]` extra. |
| `tests/unit/test_transport_factory.py` | **New.** See Verification. |
| `tests/integration/test_parity_fetch.py` | **New.** See Verification. |
| `tests/integration/test_lab_push.py` | Parameterize over transport. |
| `tests/integration/test_lab_check.py` | Parameterize over transport. |
| `tests/integration/test_lab_commit_confirmed.py` | Parameterize over transport. |

## Transport method mapping

`RustezTransport` implements `srxsync.transport.base.Transport`. rustez
installation is verified lazily in `__init__` so a user who never selects
the rustez backend never needs the extra installed.

| `Transport` method | rustez implementation |
|---|---|
| `connect(host, user, pw, ssh_key, port=830)` | `Device(host=host, user=user, passwd=pw, ssh_private_key_file=ssh_key, port=port).open(gather_facts=False)` |
| `fetch(paths)` | Build `<configuration>` filter XML with requested subtrees → `dev.rpc.get_config(filter_xml=...)` → returned `lxml.etree._Element` |
| `load(xml, mode)` | `Config(dev).lock()`, then `Config.load(etree.tostring(xml).decode(), format="xml")`. Merge vs replace is expressed via `replace="replace"` attributes already on the payload from `DiffBuilder`. |
| `commit_confirmed(minutes)` | `Config.commit(confirm=minutes)` (rustez accepts minutes via Python wrapper, converts to seconds internally) |
| `confirm()` | `Config.commit()` (plain commit seals the prior confirmed-commit timer) |
| `rollback()` | `Config.rollback(0)` (revert candidate to running) |
| `close()` | Best-effort `Config.unlock()` then `dev.close()`; swallow both exceptions |

rustez exceptions (`ConnectError`, `RpcError`, `ConfigLoadError` from
`rustez.exceptions`) are caught in `RustezTransport` and re-raised as
`TransportError` with the original message, preserving the orchestrator's
per-target isolation contract.

## Port default change (22 → 830)

rustez defaults to port 830 (the NETCONF/SSH standard). PyEZ works on
whatever port is given — some Junos devices expose NETCONF on 830
explicitly (`set system services netconf port 830`), others allow it
inline on SSH port 22. Harmonizing the ABC default to 830 aligns both
backends on the standard port.

**Verification gate during implementation:**

1. Confirm the lab SRXs (192.168.1.232/.233/.234) accept NETCONF on 830.
   A one-line check: `ssh srxsync@192.168.1.232 -p 830 -o PreferredAuthentications=publickey`
   should open (NETCONF greeting follows). If 830 is not configured on
   the lab, either enable it (`set system services netconf ssh port 830`
   + commit) or keep the ABC default at 22 and skip this change.
2. Run the existing `test_lab_*` suite against PyEZ on 830 before
   committing the default flip.
3. If we keep port 22 as default, the spec stands — rustez accepts
   whatever port is passed, nothing else changes.

## CLI

```
srxsync push  --inventory inv.yaml (--replace | --merge)
              [--transport {pyez,rustez}]
              [--commit-confirmed N] [--max-parallel N]
              [--on-error continue|abort] [--dry-run]

srxsync check --inventory inv.yaml [--transport {pyez,rustez}] [--verbose]
```

- `--transport pyez` (default) — current behavior, no new deps needed.
- `--transport rustez` — selects the Rust backend. If `rustez` is not
  importable, fail fast with: `rustez backend selected but 'rustez' is
  not installed — run: pip install -e .[rust]`.

## Packaging

```toml
[project.optional-dependencies]
# existing extras stay as-is
rust = ["rustez>=0.8.2"]
```

Install command: `pip install -e .[rust]` (or `.[rust,dev]` for devs).

## Verification

Three layers, in increasing cost:

### Unit (fast, always run)
- `tests/unit/test_transport_factory.py`:
  - `make_transport("pyez")` → `PyEZTransport`
  - `make_transport("unknown")` raises `ValueError` listing known names
  - `make_transport("rustez")` with `rustez` stubbed as missing raises
    `ImportError` with the expected install-hint message

### Integration parity (lab required, fast)
- `tests/integration/test_parity_fetch.py`:
  - Connect to `source.host` via `PyEZTransport` and `RustezTransport`
  - Fetch the union of all target `include` paths through both
  - Canonicalize (`lxml.etree.tostring(method="c14n2")`) and assert equal
  - Skips if `tests/lab.yaml` missing OR `rustez` not installed

### Integration end-to-end (lab required, slower)
- `test_lab_push.py`, `test_lab_check.py`, `test_lab_commit_confirmed.py`
  parameterize a `transport` fixture over `["pyez", "rustez"]`.
- Runtime goes from ~100 s (PyEZ only) to ~200 s (both). The
  commit-confirmed test dominates — 75 s Junos rollback wait, runs twice.
- Rustez parameterization is skipped if `rustez` is not installed.

## Failure modes

| Scenario | Behavior |
|---|---|
| User runs `--transport rustez` without the extra | Fail fast with install-hint message before any network I/O. |
| rustez raises on connect/load/commit | Caught, wrapped in `TransportError`, per-target failure — matches existing PyEZ error path. |
| Parity test finds canonical-XML diff | Build fails. Either rustez bug or an ABI drift worth debugging; we do not ship a backend that disagrees with PyEZ on fetch. |
| rustez wheel unavailable on user's platform | Covered by install-hint message; `[rust]` extra install fails at pip layer with maturin error. |

## Safety

All existing srxsync safety guarantees hold unchanged:

1. Commit-confirmed + seal — rustez maps 1:1 onto the same two-step flow.
2. Per-target isolation — each worker creates its own transport instance;
   a rustez failure on one target cannot leak state to another.
3. Best-effort cleanup — `close()` wraps `unlock()` + `dev.close()` in
   `contextlib.suppress(Exception)`.
4. Honest exit code — unchanged, transport-agnostic.

## Branch / merge flow

1. `git checkout -b rustperformance` from `master`.
2. Implementation plan (next step: writing-plans skill).
3. Code + unit tests + parity test + parameterized integration tests.
4. `pip install -e .[rust,dev]`, full test suite green (unit, parity, both
   integration runs against real lab).
5. PR `rustperformance` → `master` with benchmark numbers in the PR body
   (informational; not a merge gate).
