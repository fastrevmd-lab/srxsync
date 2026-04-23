# rustperformance — Dual-Backend Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `RustezTransport` alongside the existing `PyEZTransport`, selectable at runtime via `--transport {pyez,rustez}`. `rustez` ships as an optional pip extra. Existing lab tests gain a transport parameter so both backends are exercised end-to-end before merge.

**Architecture:** A single new seam in `srxsync/transport/__init__.py` — a `make_transport(name)` factory that returns the right class. CLI resolves the name and passes the class into `Orchestrator.__init__(transport_factory=...)` (already injectable). Everything below `Orchestrator` stays identical. Correctness of `RustezTransport` is validated integration-first against the real vSRX lab (user preference: no device mocks) — a new parity test and the existing three lab tests parameterized over backends.

**Tech Stack:** Python 3.11+, `rustez>=0.8.2` (PyO3 bindings, PyPI), `lxml`, `pytest`, `argparse`, `maturin` wheels (installed transparently via pip).

**Spec:** [`docs/superpowers/specs/2026-04-22-rustperformance-design.md`](../specs/2026-04-22-rustperformance-design.md)

---

## File Structure

New files:
- `srxsync/transport/rustez.py` — `RustezTransport(Transport)` implementation
- `tests/unit/test_transport_factory.py` — factory + error-message unit tests
- `tests/integration/test_parity_fetch.py` — PyEZ vs rustez canonical-XML parity

Modified files:
- `srxsync/transport/__init__.py` — add `make_transport()` and `KNOWN_TRANSPORTS`
- `srxsync/transport/base.py` — change `port` default `22` → `830`
- `srxsync/cli.py` — add `--transport {pyez,rustez}` to both subparsers, wire to orchestrator
- `pyproject.toml` — add `rust` optional-dependency group
- `README.md` — document `--transport` flag and `[rust]` extra
- `tests/integration/test_lab_push.py` — parameterize over `["pyez", "rustez"]`
- `tests/integration/test_lab_check.py` — parameterize over `["pyez", "rustez"]`
- `tests/integration/test_lab_commit_confirmed.py` — parameterize over `["pyez", "rustez"]`

---

## Task 1: Branch setup and pre-flight verification

**Files:** none yet.

This task confirms the lab environment supports the design's assumptions before any code is written. Everything after Task 1 assumes the pre-flight results were positive.

- [ ] **Step 1: Create the branch**

```bash
cd /home/mharman/srxmaster
git checkout master
git pull --ff-only origin master
git checkout -b rustperformance
```

- [ ] **Step 2: Verify NETCONF is reachable on port 830 on all three lab devices**

```bash
source ~/.srxsync.env
for h in 192.168.1.232 192.168.1.233 192.168.1.234; do
  echo "=== $h ==="
  ssh -i ~/.ssh/id_ed25519 -p 830 -o BatchMode=yes -o ConnectTimeout=5 \
      -s srxsync@$h netconf 2>&1 | head -5
done
```

Expected: each host prints the NETCONF `<hello>` greeting (XML starting `<?xml` or `<hello xmlns=`). If any host times out or refuses connection, stop and enable NETCONF on 830:

```
configure
set system services netconf ssh port 830
commit and-quit
```

Then re-run the check. Do not proceed until all three hosts respond.

- [ ] **Step 3: Confirm rustez installs cleanly from PyPI**

```bash
source .venv/bin/activate
pip install 'rustez>=0.8.2' 2>&1 | tail -5
python -c "import rustez; print(rustez.__file__)"
```

Expected: install succeeds (manylinux wheel), import prints a path under `.venv`. Then uninstall so the base install stays clean for Task 2:

```bash
pip uninstall -y rustez
```

- [ ] **Step 4: No commit yet** — nothing has changed.

---

## Task 2: Add the `[rust]` extra to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read current optional-dependencies**

```bash
grep -nA 20 'optional-dependencies' pyproject.toml
```

Expected: existing groups like `dev`, `keyring`, `vault`.

- [ ] **Step 2: Add the `rust` group**

In `pyproject.toml` under `[project.optional-dependencies]`, add (keeping alphabetical order if present):

```toml
rust = ["rustez>=0.8.2"]
```

- [ ] **Step 3: Install the extra and verify import**

```bash
source .venv/bin/activate
pip install -e '.[rust]' 2>&1 | tail -3
python -c "import rustez; from rustez import Device, Config; print('ok')"
```

Expected: install succeeds, final `print('ok')`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add [rust] optional extra for rustez backend"
```

---

## Task 3: Change Transport ABC port default 22 → 830

**Files:**
- Modify: `srxsync/transport/base.py:22` (the `port: int = 22` default)

- [ ] **Step 1: Update the default**

In `srxsync/transport/base.py`, change the `connect` signature:

```python
    @abstractmethod
    def connect(
        self,
        host: str,
        username: str,
        password: str | None = None,
        ssh_key: str | None = None,
        port: int = 830,
    ) -> None: ...
```

- [ ] **Step 2: Check PyEZTransport default propagation**

```bash
grep -n 'port' srxsync/transport/pyez.py
```

If `PyEZTransport.connect` has its own `port: int = 22` default, update it to `830` too so the concrete class matches the ABC.

- [ ] **Step 3: Run the unit tests**

```bash
source .venv/bin/activate
pytest tests/unit/ -q
```

Expected: all pass (34 tests pre-Task-4).

- [ ] **Step 4: Run one integration test to confirm PyEZ still works on 830**

```bash
pytest tests/integration/test_lab_check.py -q
```

Expected: pass. If it fails with a connection error, revert this task and keep port 22 as default — note the decision in the plan margin and skip the spec's "port harmonization" change.

- [ ] **Step 5: Commit**

```bash
git add srxsync/transport/base.py srxsync/transport/pyez.py
git commit -m "refactor: default Transport.port to 830 (NETCONF standard)"
```

---

## Task 4: Transport factory `make_transport`

**Files:**
- Create: `tests/unit/test_transport_factory.py`
- Modify: `srxsync/transport/__init__.py`

- [ ] **Step 1: Read current transport package exports**

```bash
cat srxsync/transport/__init__.py
```

Note which names are already re-exported (e.g. `PyEZTransport`, `Transport`, `TransportError`).

- [ ] **Step 2: Write the failing unit tests**

Create `tests/unit/test_transport_factory.py`:

```python
"""Unit tests for the transport factory."""

from __future__ import annotations

import sys

import pytest

from srxsync.transport import (
    KNOWN_TRANSPORTS,
    PyEZTransport,
    Transport,
    make_transport,
)


def test_known_transports_contains_both_backends():
    assert set(KNOWN_TRANSPORTS) == {"pyez", "rustez"}


def test_make_transport_pyez_returns_pyez_class():
    cls = make_transport("pyez")
    assert cls is PyEZTransport
    assert issubclass(cls, Transport)


def test_make_transport_unknown_raises_value_error():
    with pytest.raises(ValueError, match="unknown transport"):
        make_transport("grpc")


def test_make_transport_rustez_missing_extra_raises_clear_error(monkeypatch):
    """If rustez is not importable, we must fail with an install hint."""
    # Force import to fail even if rustez is installed in this venv
    monkeypatch.setitem(sys.modules, "rustez", None)
    with pytest.raises(ImportError, match=r"pip install.*\[rust\]"):
        make_transport("rustez")


def test_make_transport_rustez_returns_rustez_class_when_available():
    """If rustez is installed, the factory returns RustezTransport."""
    rustez_mod = pytest.importorskip("rustez")
    assert rustez_mod is not None
    from srxsync.transport.rustez import RustezTransport

    cls = make_transport("rustez")
    assert cls is RustezTransport
    assert issubclass(cls, Transport)
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
pytest tests/unit/test_transport_factory.py -v
```

Expected: all fail (likely ImportError on `make_transport` / `KNOWN_TRANSPORTS` not defined).

- [ ] **Step 4: Implement the factory**

Replace `srxsync/transport/__init__.py` with:

```python
"""Transport package — abstract interface plus concrete backends.

Backends are resolved at runtime through `make_transport(name)`. The
rustez backend is imported lazily so users on the base install (no
`[rust]` extra) can still use the pyez backend without ImportError.
"""

from __future__ import annotations

from srxsync.transport.base import Transport, TransportError
from srxsync.transport.pyez import PyEZTransport

__all__ = [
    "KNOWN_TRANSPORTS",
    "PyEZTransport",
    "Transport",
    "TransportError",
    "make_transport",
]

KNOWN_TRANSPORTS: tuple[str, ...] = ("pyez", "rustez")


def make_transport(name: str) -> type[Transport]:
    """Return the Transport subclass for the given backend name.

    Args:
        name: One of `KNOWN_TRANSPORTS`.

    Raises:
        ValueError: If `name` is not a known backend.
        ImportError: If `name == "rustez"` but the `rustez` package is
            not installed; the message points the user at the install
            command.
    """
    if name == "pyez":
        return PyEZTransport
    if name == "rustez":
        try:
            from srxsync.transport.rustez import RustezTransport
        except ImportError as exc:
            raise ImportError(
                "rustez backend selected but 'rustez' is not installed — "
                "run: pip install -e .[rust]"
            ) from exc
        return RustezTransport
    raise ValueError(
        f"unknown transport: {name!r} (known: {', '.join(KNOWN_TRANSPORTS)})"
    )
```

- [ ] **Step 5: Create a stub RustezTransport so the "available" test can import it**

The `test_make_transport_rustez_returns_rustez_class_when_available` test needs `srxsync.transport.rustez:RustezTransport` to exist even though the real implementation lands in Task 5. Create a minimal placeholder that inherits from `Transport` but whose methods raise `NotImplementedError`. Task 5 replaces this wholesale.

Create `srxsync/transport/rustez.py`:

```python
"""Rust-backed Transport via the rustez PyO3 bindings.

Placeholder — real implementation lands in Task 5 of the
rustperformance plan. The class must import without touching rustez so
the factory stub test passes before the implementation is in place.
"""

from __future__ import annotations

from typing import Literal

from lxml import etree

from srxsync.transport.base import Transport, TransportError


class RustezTransport(Transport):  # pragma: no cover — placeholder
    def connect(
        self,
        host: str,
        username: str,
        password: str | None = None,
        ssh_key: str | None = None,
        port: int = 830,
    ) -> None:
        raise NotImplementedError("RustezTransport not yet implemented")

    def fetch(self, paths: list[str]) -> etree._Element:
        raise NotImplementedError

    def load(self, xml: etree._Element, mode: Literal["replace", "merge"]) -> None:
        raise NotImplementedError

    def commit_confirmed(self, minutes: int) -> None:
        raise NotImplementedError

    def confirm(self) -> None:
        raise NotImplementedError

    def rollback(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
```

- [ ] **Step 6: Run the tests, confirm all pass**

```bash
pytest tests/unit/test_transport_factory.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Run the full unit suite — nothing else should regress**

```bash
pytest tests/unit/ -q
```

Expected: all pass (previously 34 + 5 new = 39).

- [ ] **Step 8: Commit**

```bash
git add srxsync/transport/__init__.py srxsync/transport/rustez.py tests/unit/test_transport_factory.py
git commit -m "feat(transport): add make_transport factory with rustez stub"
```

---

## Task 5: RustezTransport real implementation

**Files:**
- Modify: `srxsync/transport/rustez.py` (replace placeholder)

User preference is no mocked device tests — this class is validated end-to-end via the parity test (Task 7) and the parameterized lab tests (Task 8). This task lands a complete implementation that is *syntactically* validated here and behaviorally validated in those later tasks.

- [ ] **Step 1: Read the rustez Python surface once**

```bash
python - <<'PY'
from rustez import Device, Config
help(Device.__init__)
help(Config.load)
help(Config.commit)
PY
```

Confirm: `Device(host, user, passwd, port, ssh_private_key_file, ...)`,
`Config(dev).lock/load(content, format)/commit(confirm=N)/rollback(rb_id=0)/unlock()`,
`dev.rpc.get_config(filter_xml=...)` returns an lxml Element.

- [ ] **Step 2: Replace the placeholder with the real implementation**

Replace `srxsync/transport/rustez.py` in full:

```python
"""Rust-backed Transport via the rustez PyO3 bindings.

rustez is imported at module import time; this module is only imported
by `make_transport("rustez")`, which raises a clear error with an
install hint if rustez is unavailable. Do not import this module from
anywhere else.

Every rustez exception is wrapped as TransportError so the orchestrator
sees a single exception type regardless of backend. Best-effort cleanup
in close() mirrors PyEZTransport.
"""

from __future__ import annotations

import contextlib
from typing import Literal

from lxml import etree
from rustez import Config, Device
from rustez.exceptions import (
    ConfigLoadError,
    ConnectAuthError,
    ConnectError,
    ConnectTimeoutError,
    RpcError,
)

from srxsync.transport.base import Transport, TransportError

_RUSTEZ_ERRORS: tuple[type[Exception], ...] = (
    ConnectError,
    ConnectAuthError,
    ConnectTimeoutError,
    ConfigLoadError,
    RpcError,
    RuntimeError,  # rustez occasionally surfaces bare RuntimeErrors
)


class RustezTransport(Transport):
    def __init__(self) -> None:
        self._dev: Device | None = None
        self._cfg: Config | None = None
        self._locked: bool = False
        self._host: str = ""

    # ------------------------------------------------------------------
    # Connect / close
    # ------------------------------------------------------------------

    def connect(
        self,
        host: str,
        username: str,
        password: str | None = None,
        ssh_key: str | None = None,
        port: int = 830,
    ) -> None:
        self._host = host
        try:
            self._dev = Device(
                host=host,
                user=username,
                passwd=password or "",
                port=port,
                ssh_private_key_file=ssh_key,
            )
            self._dev.open(gather_facts=False)
        except _RUSTEZ_ERRORS as exc:
            raise TransportError(f"connect failed for {host}: {exc}") from exc

    def close(self) -> None:
        if self._cfg is not None and self._locked:
            with contextlib.suppress(Exception):
                self._cfg.unlock()
            self._locked = False
        if self._dev is not None:
            with contextlib.suppress(Exception):
                self._dev.close()
        self._dev = None
        self._cfg = None

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def fetch(self, paths: list[str]) -> etree._Element:
        if self._dev is None:
            raise TransportError("not connected")
        filter_xml = _paths_to_filter(paths)
        try:
            reply = self._dev.rpc.get_config(filter_xml=filter_xml)
        except _RUSTEZ_ERRORS as exc:
            raise TransportError(f"fetch failed on {self._host}: {exc}") from exc
        # rustez strips namespaces and usually returns <rpc-reply><data><configuration>..</>.
        # We want the <configuration> element. Fall back gracefully.
        cfg = reply.find(".//configuration")
        if cfg is None:
            # If rustez returned the <configuration> root directly.
            if reply.tag == "configuration":
                return reply
            raise TransportError(
                f"fetch on {self._host} returned no <configuration> element"
            )
        return cfg

    # ------------------------------------------------------------------
    # Load / commit / rollback
    # ------------------------------------------------------------------

    def load(
        self, xml: etree._Element, mode: Literal["replace", "merge"]
    ) -> None:
        if self._dev is None:
            raise TransportError("not connected")
        if self._cfg is None:
            self._cfg = Config(self._dev)
        if not self._locked:
            try:
                self._cfg.lock()
            except _RUSTEZ_ERRORS as exc:
                raise TransportError(f"lock failed on {self._host}: {exc}") from exc
            self._locked = True
        content = etree.tostring(xml).decode()
        try:
            # Merge vs replace is expressed by replace="replace" attributes
            # already on the payload (DiffBuilder sets them). rustez's
            # load() defaults to merge semantics at the NETCONF layer,
            # which respects our per-element replace attribute.
            self._cfg.load(content, format="xml")
        except _RUSTEZ_ERRORS as exc:
            raise TransportError(f"load failed on {self._host}: {exc}") from exc

    def commit_confirmed(self, minutes: int) -> None:
        if self._cfg is None:
            raise TransportError("not connected")
        try:
            self._cfg.commit(confirm=minutes)
        except _RUSTEZ_ERRORS as exc:
            raise TransportError(
                f"commit confirmed failed on {self._host}: {exc}"
            ) from exc

    def confirm(self) -> None:
        if self._cfg is None:
            raise TransportError("not connected")
        try:
            self._cfg.commit()
        except _RUSTEZ_ERRORS as exc:
            raise TransportError(
                f"confirm commit failed on {self._host}: {exc}"
            ) from exc

    def rollback(self) -> None:
        if self._cfg is None:
            return  # nothing to roll back; match PyEZ behavior
        with contextlib.suppress(Exception):
            self._cfg.rollback(0)


def _paths_to_filter(paths: list[str]) -> str:
    """Build a NETCONF subtree filter XML string for the given paths.

    Each path is an absolute XPath-like string starting with
    /configuration/... We convert the union into a single
    <configuration> filter containing nested empty elements for each
    path so NETCONF returns only those subtrees.
    """
    root = etree.Element("configuration")
    for abs_path in paths:
        parts = abs_path.removeprefix("/configuration/").split("/")
        parent = root
        for part in parts:
            existing = parent.find(part)
            if existing is None:
                existing = etree.SubElement(parent, part)
            parent = existing
    return etree.tostring(root).decode()
```

- [ ] **Step 3: Verify the module imports cleanly and unit suite still passes**

```bash
source .venv/bin/activate
python -c "from srxsync.transport.rustez import RustezTransport; print('ok')"
pytest tests/unit/ -q
```

Expected: `ok`, all 39 unit tests pass. (The factory test `test_make_transport_rustez_returns_rustez_class_when_available` now passes against the real class.)

- [ ] **Step 4: Smoke-test connect+close against the lab master**

```bash
source ~/.srxsync.env
python - <<'PY'
from srxsync.transport.rustez import RustezTransport
t = RustezTransport()
t.connect(
    "192.168.1.232",
    "srxsync",
    ssh_key="/home/mharman/.ssh/id_ed25519",
)
print("connected")
t.close()
print("closed")
PY
```

Expected: `connected` then `closed`. If this fails, fix the transport before moving on — don't leave a broken implementation for Task 7 to trip over.

- [ ] **Step 5: Commit**

```bash
git add srxsync/transport/rustez.py
git commit -m "feat(transport): implement RustezTransport backend"
```

---

## Task 6: CLI `--transport` flag

**Files:**
- Modify: `srxsync/cli.py`
- Create: `tests/unit/test_cli.py` (if not already present; check first)

- [ ] **Step 1: Check for an existing CLI test file**

```bash
ls tests/unit/test_cli.py 2>&1
```

If it exists, read it to understand the current argparse testing pattern. If not, we'll create a new one.

- [ ] **Step 2: Read the current CLI to understand argparse structure**

```bash
cat srxsync/cli.py
```

Identify: the two subparsers (`push`, `check`), where `Orchestrator` is constructed, how `transport_factory` is currently passed (or defaulted).

- [ ] **Step 3: Write failing unit tests for the flag**

Create or append to `tests/unit/test_cli.py`:

```python
"""Unit tests for CLI argument parsing."""

from __future__ import annotations

import pytest

from srxsync.cli import build_parser


def test_push_accepts_transport_flag():
    parser = build_parser()
    args = parser.parse_args(
        ["push", "--inventory", "inv.yaml", "--merge", "--transport", "rustez"]
    )
    assert args.transport == "rustez"


def test_check_accepts_transport_flag():
    parser = build_parser()
    args = parser.parse_args(
        ["check", "--inventory", "inv.yaml", "--transport", "rustez"]
    )
    assert args.transport == "rustez"


def test_push_transport_defaults_to_pyez():
    parser = build_parser()
    args = parser.parse_args(
        ["push", "--inventory", "inv.yaml", "--merge"]
    )
    assert args.transport == "pyez"


def test_check_transport_defaults_to_pyez():
    parser = build_parser()
    args = parser.parse_args(["check", "--inventory", "inv.yaml"])
    assert args.transport == "pyez"


def test_transport_rejects_unknown_value():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["push", "--inventory", "inv.yaml", "--merge", "--transport", "grpc"]
        )
```

- [ ] **Step 4: Run tests and confirm they fail**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: either ImportError on `build_parser` (if it's currently named something else / not exported) or failures on `args.transport`.

- [ ] **Step 5: Refactor CLI to expose `build_parser` and add the flag**

Edit `srxsync/cli.py`. Two required changes:

1. Extract the `argparse.ArgumentParser` construction into a module-level `build_parser() -> ArgumentParser` function (if it isn't already), so tests can import it.
2. Add `--transport` to both subparsers with `choices=list(KNOWN_TRANSPORTS)` and `default="pyez"`.
3. In `main()`, resolve `args.transport` via `make_transport(args.transport)` and pass as `transport_factory=` to `Orchestrator`.

Example diff (adapt to the actual current shape — use Read to see lines first):

```python
from srxsync.transport import KNOWN_TRANSPORTS, make_transport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="srxsync")
    sub = parser.add_subparsers(dest="command", required=True)

    push = sub.add_parser("push")
    push.add_argument("--inventory", required=True)
    mode = push.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replace", action="store_true")
    mode.add_argument("--merge", action="store_true")
    push.add_argument("--commit-confirmed", type=int, default=5)
    push.add_argument("--max-parallel", type=int, default=5)
    push.add_argument("--on-error", choices=["continue", "abort"], default="continue")
    push.add_argument("--dry-run", action="store_true")
    push.add_argument(
        "--transport",
        choices=list(KNOWN_TRANSPORTS),
        default="pyez",
        help="backend transport (default: pyez)",
    )

    check = sub.add_parser("check")
    check.add_argument("--inventory", required=True)
    check.add_argument("--verbose", action="store_true")
    check.add_argument("--max-parallel", type=int, default=5)
    check.add_argument(
        "--transport",
        choices=list(KNOWN_TRANSPORTS),
        default="pyez",
        help="backend transport (default: pyez)",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()
    transport_cls = make_transport(args.transport)
    # ... existing inventory loading, CategoryModel, Orchestrator construction ...
    orch = Orchestrator(inv, cats, transport_factory=transport_cls)
    # ... existing push/check dispatch ...
```

**Important:** do not blindly replace the whole file — preserve the existing inventory loading, logging, and exit-code logic. Only extract `build_parser`, add the flag, and thread `transport_cls` into `Orchestrator(...)`.

- [ ] **Step 6: Run CLI tests**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Run full unit suite — no regressions**

```bash
pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 8: Smoke-test the CLI actually dispatches both backends**

```bash
source ~/.srxsync.env
srxsync check --inventory inv.yaml --transport pyez --verbose | head -20
srxsync check --inventory inv.yaml --transport rustez --verbose | head -20
```

Expected: both produce drift output (content may differ slightly before parity test exists; what matters is neither crashes).

- [ ] **Step 9: Commit**

```bash
git add srxsync/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add --transport {pyez,rustez} flag"
```

---

## Task 7: Integration parity test (PyEZ vs rustez fetch)

**Files:**
- Create: `tests/integration/test_parity_fetch.py`

This is the fastest integration gate — it catches most rustez drift without paying the 75-second commit-confirmed cost.

- [ ] **Step 1: Look at how existing integration tests discover the lab**

```bash
cat tests/integration/conftest.py
```

Note how `LAB_FILE`, the `lab` fixture, and credential resolution work.

- [ ] **Step 2: Write the parity test**

Create `tests/integration/test_parity_fetch.py`:

```python
"""PyEZ vs rustez fetch parity — canonical-XML equality.

Skips if tests/lab.yaml is absent or if rustez is not installed.
"""

from __future__ import annotations

import pytest
from lxml import etree

from srxsync.categories import CategoryModel
from srxsync.inventory import Auth, load_inventory
from srxsync.secrets import get_secret
from srxsync.transport import PyEZTransport

from tests.integration.conftest import LAB_FILE

pytestmark = pytest.mark.integration


def _rustez_available() -> bool:
    try:
        import rustez  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.fixture(scope="module")
def parity_ctx(lab):
    if not _rustez_available():
        pytest.skip("rustez not installed — run: pip install -e .[rust]")
    cats = CategoryModel.default()
    inv = load_inventory(LAB_FILE, known_categories=cats.known_names())
    # Build the union of all target-include paths — same logic the
    # orchestrator uses to fetch from the master.
    union: list[str] = []
    seen: set[str] = set()
    for t in inv.targets:
        for name in t.include:
            if name not in seen:
                union.append(name)
                seen.add(name)
    paths, _ = cats.resolve(union)
    return {"inv": inv, "paths": paths}


def _fetch(transport_cls, host, paths):
    t = transport_cls()
    secret = get_secret(host=host, auth=Auth(provider="env"))
    t.connect(host, secret.username, secret.password, ssh_key=secret.ssh_key_path)
    try:
        return t.fetch(paths)
    finally:
        t.close()


def test_pyez_and_rustez_fetch_produces_same_canonical_xml(parity_ctx):
    from srxsync.transport.rustez import RustezTransport

    host = parity_ctx["inv"].source.host
    paths = parity_ctx["paths"]

    pyez_xml = _fetch(PyEZTransport, host, paths)
    rustez_xml = _fetch(RustezTransport, host, paths)

    pyez_canon = etree.tostring(pyez_xml, method="c14n2")
    rustez_canon = etree.tostring(rustez_xml, method="c14n2")

    if pyez_canon != rustez_canon:
        # Produce a readable diff on failure.
        import difflib
        diff = "\n".join(
            difflib.unified_diff(
                pyez_canon.decode().splitlines(),
                rustez_canon.decode().splitlines(),
                lineterm="",
                fromfile="pyez",
                tofile="rustez",
                n=3,
            )
        )
        pytest.fail(f"fetch parity mismatch:\n{diff[:4000]}")
```

- [ ] **Step 3: Run the parity test**

```bash
source .venv/bin/activate
source ~/.srxsync.env
pytest tests/integration/test_parity_fetch.py -v
```

Expected: pass.

**Common failure modes and how to handle them (do not hide these — fix the root cause):**

- **Whitespace-only diff:** both backends should produce normalized output. If only whitespace differs, investigate whether rustez is returning pretty-printed XML or different attribute ordering. Canonicalization (`c14n2`) should neutralize ordering, so a residual diff means a real content difference.
- **Namespace leak:** rustez strips namespaces per `_strip_namespaces` in `rustez/__init__.py`. PyEZ also strips by default. If one side has `{...}tagname` and the other doesn't, normalize in the test with an explicit strip step *in the test*, not in the transport — transports are verbatim.
- **Element ordering:** if the only diff is sibling order, it's likely a real drift in how rustez issues the get-config. Open a rustez issue; meanwhile `xmlsort`-style normalization can be added to the test as a temporary workaround with a TODO.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_parity_fetch.py
git commit -m "test: rustez vs pyez fetch parity"
```

---

## Task 8: Parameterize existing lab tests over both backends

**Files:**
- Modify: `tests/integration/test_lab_push.py`
- Modify: `tests/integration/test_lab_check.py`
- Modify: `tests/integration/test_lab_commit_confirmed.py`

- [ ] **Step 1: Read the three test files**

```bash
cat tests/integration/test_lab_push.py
cat tests/integration/test_lab_check.py
cat tests/integration/test_lab_commit_confirmed.py
```

Note how `Orchestrator` is currently constructed and where the `lab_ctx` fixture lives.

- [ ] **Step 2: Add a shared `transport_cls` fixture in `conftest.py`**

In `tests/integration/conftest.py`, append:

```python
@pytest.fixture(params=["pyez", "rustez"])
def transport_cls(request):
    """Parameterized transport class for each lab test run."""
    name = request.param
    if name == "rustez":
        try:
            import rustez  # noqa: F401
        except ImportError:
            pytest.skip("rustez not installed — run: pip install -e .[rust]")
    from srxsync.transport import make_transport
    return make_transport(name)
```

- [ ] **Step 3: Update each test to accept and use `transport_cls`**

For each of the three test files, change the `Orchestrator(...)` call to pass
`transport_factory=transport_cls`, and add `transport_cls` to the fixture
parameter list. Example pattern — apply to each file:

```python
# before
@pytest.fixture(scope="module")
def lab_ctx(lab):
    cats = CategoryModel.default()
    inv = load_inventory(LAB_FILE, known_categories=cats.known_names())
    orch = Orchestrator(inv, cats)
    ...

# after
@pytest.fixture
def lab_ctx(lab, transport_cls):
    cats = CategoryModel.default()
    inv = load_inventory(LAB_FILE, known_categories=cats.known_names())
    orch = Orchestrator(inv, cats, transport_factory=transport_cls)
    ...
```

Note the scope drop from `"module"` to function scope — parametrization needs a new fixture instance per transport. If the original test relied on module-scoped state (e.g. a drift policy injected in a setup test), preserve that by keeping the setup as a module-scoped fixture and letting the `orch` be function-scoped.

- [ ] **Step 4: Run the parameterized integration tests (both backends)**

```bash
source ~/.srxsync.env
pytest tests/integration/test_lab_check.py tests/integration/test_lab_push.py -v
```

Expected: 2 test functions × 2 transports = 4 PASS.

- [ ] **Step 5: Run the commit-confirmed test (will take ~150s for both backends)**

```bash
pytest tests/integration/test_lab_commit_confirmed.py -v
```

Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/conftest.py tests/integration/test_lab_push.py tests/integration/test_lab_check.py tests/integration/test_lab_commit_confirmed.py
git commit -m "test: parameterize lab tests over pyez and rustez"
```

---

## Task 9: README documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Find the right spots**

```bash
grep -n '## Install\|## CLI\|## Architecture' README.md
```

- [ ] **Step 2: Update the Install section**

Under the existing `Optional extras:` block (after `keyring` and `vault`), add:

```markdown
pip install -e .[rust]      # Rust-backed transport (rustez)
```

- [ ] **Step 3: Add a new `## Transports` section between `## CLI` and `## Categories`**

```markdown
## Transports

srxsync can drive devices through two NETCONF implementations:

| Name | Library | Install |
|---|---|---|
| `pyez` (default) | Juniper PyEZ | bundled |
| `rustez` | Rust `rustez` (PyO3) | `pip install -e .[rust]` |

Select a backend per-invocation:

```
srxsync push --inventory inv.yaml --merge --transport rustez
srxsync check --inventory inv.yaml --transport rustez
```

Both backends implement the same `Transport` contract — inventory,
policy, and safety behavior is identical. The parity test
(`tests/integration/test_parity_fetch.py`) asserts rustez produces
canonical-XML-equal `get-config` output to PyEZ for every branch merge.
```

- [ ] **Step 4: Update the CLI flag table**

In the existing `## CLI` flag table, add a row:

```markdown
| `--transport {pyez,rustez}` | Select backend (default: pyez). rustez requires the `[rust]` extra. |
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document --transport flag and [rust] extra"
```

---

## Task 10: Final verification and PR

**Files:** none modified in this task.

- [ ] **Step 1: Run the full unit suite**

```bash
source .venv/bin/activate
pytest tests/unit/ -q
```

Expected: all pass (previously 34 + 5 factory + 5 CLI = 44 tests).

- [ ] **Step 2: Run the full integration suite against both backends**

```bash
source ~/.srxsync.env
pytest tests/integration/ -v
```

Expected: every parametrized test passes under both `pyez` and `rustez`. Total wall time ~200 s (dominated by the two 75 s commit-confirmed timers).

- [ ] **Step 3: Lint + type-check**

```bash
python -m ruff check srxsync/ tests/
python -m mypy srxsync/
```

Expected: no issues.

- [ ] **Step 4: Push the branch**

```bash
git push -u origin rustperformance
```

- [ ] **Step 5: Open the PR**

```bash
gh pr create --title "feat: rustperformance — dual-backend transport (pyez | rustez)" \
  --body "$(cat <<'EOF'
## Summary
- Add `RustezTransport` alongside `PyEZTransport`, selectable via `--transport {pyez,rustez}`
- rustez ships as an optional extra: `pip install -e .[rust]`
- Transport ABC port default harmonized to 830 (NETCONF standard)
- Parity test + parameterized lab suite validate both backends end-to-end

## Spec
[docs/superpowers/specs/2026-04-22-rustperformance-design.md](docs/superpowers/specs/2026-04-22-rustperformance-design.md)

## Test plan
- [x] Unit tests pass (`pytest tests/unit/`)
- [x] Parity test passes against lab (PyEZ vs rustez canonical XML)
- [x] `test_lab_push` / `test_lab_check` / `test_lab_commit_confirmed` pass under both backends
- [x] `ruff check` clean
- [x] `mypy srxsync/` clean

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed. Do not merge until manual review.

---

## Self-review notes

Spec coverage — every "Files changed" row in the spec has a corresponding task:

| Spec file | Task |
|---|---|
| `srxsync/transport/__init__.py` | 4 |
| `srxsync/transport/rustez.py` | 4 (stub) + 5 (real) |
| `srxsync/transport/base.py` | 3 |
| `srxsync/transport/pyez.py` | 3 (port default mirror) |
| `srxsync/cli.py` | 6 |
| `srxsync/orchestrator.py` | no change (factory injection already exists) |
| `pyproject.toml` | 2 |
| `README.md` | 9 |
| `tests/unit/test_transport_factory.py` | 4 |
| `tests/integration/test_parity_fetch.py` | 7 |
| `tests/integration/test_lab_*.py` | 8 |

Verification tiers (unit / parity / parameterized integration) are each landed in dedicated tasks before the PR.
