# Zone Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-target master→slave zone-name translation (`zone_map`) for `push` and `check`, additive-only zone handling, and a console warning for zones with no interfaces.

**Architecture:** A new pure module `srxsync/zonemap.py` translates a deep copy of the fetched master config per target (rename, merge collapsed policy contexts, reduce N:1 zones to empty shells). A second pure module `srxsync/zonewarn.py` compares the payload with the target's live zones and produces warnings. The orchestrator wires both into push and check; `DiffBuilder` stops marking `security/zones` with `replace`; `DriftDetector` learns to ignore N:1 zone content.

**Tech Stack:** Python 3.11, lxml, PyYAML, pytest, ruff, mypy (strict).

**Spec:** `docs/superpowers/specs/2026-10-16-zone-translation-design.md`

**Base:** rebased onto `origin/master` 7f85e0c (includes rustez transport #7, fail-closed drift #3).

## Global Constraints

- Python `>=3.11`; no new runtime dependencies.
- `ruff check srxsync tests` must pass (line length 100, rules `E,F,W,I,UP,B,SIM,RUF`).
- `mypy srxsync` must report no issues (baseline on `origin/master` 7f85e0c is clean; 76 unit tests pass).
- Docstrings on every new public function/class (user preference).
- Descriptive variable names; no single-letter names except loop indices.
- Prefer early returns over nested if/else.
- No `zone_map` ⇒ payload byte-for-byte unchanged versus today.
- srxsync never deletes a zone on a slave; `security/zones` never carries `replace="replace"`.
- Warnings never fail a target or change the exit code.
- Warning text, exact: `<host>: creating zone <Z> with no interfaces — bind an interface on the slave (set security zones security-zone <Z> interfaces <ifl>)` and `<host>: zone <Z> exists with no interfaces — bind an interface on the slave (set security zones security-zone <Z> interfaces <ifl>)`. The CLI prefixes `WARNING ` and prints to stderr.
- Commit message trailer on every commit: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- Work on branch `feat/zone-translation`. Environment: `.venv` already exists (`python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'` if not). Run tests with `.venv/bin/pytest tests/unit -q`.

## Junos XML shapes (fetched config, no namespaces — PyEZ `normalize=True`)

Verified on lab `vsrx-ci` (Junos 26.2R1) on 2026-10-16 for NAT; the others follow the same schema conventions.

```xml
<security>
  <address-book><name>global</name>
    <attach><zone><name>APP1</name></zone><zone><name>APP2</name></zone></attach>
  </address-book>
  <zones><security-zone><name>APP1</name><interfaces><name>ge-0/0/1.0</name></interfaces></security-zone></zones>
  <policies>
    <policy>                                   <!-- a context -->
      <from-zone-name>APP1</from-zone-name><to-zone-name>UNTRUST</to-zone-name>
      <policy><name>allow-web</name>...</policy>   <!-- a rule -->
    </policy>
    <global><policy><name>g1</name>
      <match>...<from-zone>APP1</from-zone><to-zone>UNTRUST</to-zone></match>
    </policy></global>
  </policies>
  <nat><source><rule-set><name>rs</name>
    <from><zone>APP1</zone></from><to><zone>UNTRUST</zone></to>
  </rule-set></source></nat>       <!-- same from/to shape under destination and static -->
</security>
```

Note: `PyEZTransport.fetch` appends one `<security>` child per fetched path, so a fetched config may contain several sibling `<security>` elements. All XPaths below use `security/...` relative to the `<configuration>` root, which matches across siblings.

## File Structure

| File | Responsibility |
|---|---|
| `srxsync/inventory.py` (modify) | Parse/validate per-target `zone_map` |
| `srxsync/zonemap.py` (create) | `ZoneTranslator`, `ZoneTranslationError`, `ZONES_PATH` — pure XML translation |
| `srxsync/zonewarn.py` (create) | `zone_warnings()` — pure payload-vs-target warning generation |
| `srxsync/diff.py` (modify) | Never mark `security/zones` with `replace` |
| `srxsync/drift.py` (modify) | `merged_zones` field: N:1 zones compared by existence only |
| `srxsync/results.py` (modify) | `warnings` field on `TargetResult` and `DriftLine` |
| `srxsync/cli.py` (modify) | Print warnings to stderr |
| `srxsync/orchestrator.py` (modify) | Wire translator + warnings into push and check |
| `tests/fixtures/configs/zones_master.xml` (create) | Master with APP1/APP2/APP3/UNTRUST |
| `tests/fixtures/inventory/zone_map*.yaml` (create) | Inventory fixtures |
| `tests/unit/test_zonemap.py`, `test_zonewarn.py`, `test_orchestrator.py` (create) | Unit tests |
| `README.md` (modify) | "Zone translation" section |

---

### Task 1: Inventory `zone_map`

**Files:**
- Modify: `srxsync/inventory.py`
- Create: `tests/fixtures/inventory/zone_map.yaml`, `tests/fixtures/inventory/zone_map_bad.yaml`
- Test: `tests/unit/test_inventory.py`

**Interfaces:**
- Produces: `Target.zone_map: dict[str, str]` (defaults to `{}`; last field, so existing positional `Target(host, auth, include)` still works).

- [ ] **Step 1: Write fixtures**

`tests/fixtures/inventory/zone_map.yaml`:
```yaml
source:
  host: srx-master.example.net
  auth: { provider: env }
targets:
  - host: srx-a.example.net
    auth: { provider: env }
    include: [policies, zones]
    zone_map:
      APP1: APPS
      APP2: APPS
      APP3: APPS
  - host: srx-b.example.net
    auth: { provider: env }
    include: [policies]
```

`tests/fixtures/inventory/zone_map_bad.yaml`:
```yaml
source:
  host: srx-master.example.net
  auth: { provider: env }
targets:
  - host: srx-a.example.net
    auth: { provider: env }
    include: [policies]
    zone_map: [APP1, APPS]
```

- [ ] **Step 2: Write the failing tests** (append to `tests/unit/test_inventory.py`)

```python
def test_zone_map_parsed():
    inv = load_inventory(FIXTURES / "zone_map.yaml", known_categories=KNOWN_CATEGORIES)
    assert inv.targets[0].zone_map == {"APP1": "APPS", "APP2": "APPS", "APP3": "APPS"}


def test_zone_map_defaults_empty():
    inv = load_inventory(FIXTURES / "zone_map.yaml", known_categories=KNOWN_CATEGORIES)
    assert inv.targets[1].zone_map == {}


def test_zone_map_must_be_mapping():
    with pytest.raises(InventoryError, match="zone_map must be a mapping"):
        load_inventory(FIXTURES / "zone_map_bad.yaml", known_categories=KNOWN_CATEGORIES)


@pytest.mark.parametrize("bad_map", [{"APP1": ""}, {"": "APPS"}, {"APP1": 5}, {"APP1": None}])
def test_zone_map_entries_must_be_non_empty_strings(tmp_path, bad_map):
    import yaml

    doc = {
        "source": {"host": "m", "auth": {"provider": "env"}},
        "targets": [
            {"host": "t", "auth": {"provider": "env"}, "include": ["policies"], "zone_map": bad_map}
        ],
    }
    inv_file = tmp_path / "inv.yaml"
    inv_file.write_text(yaml.safe_dump(doc))
    with pytest.raises(InventoryError, match="zone_map entries must be non-empty strings"):
        load_inventory(inv_file, known_categories=KNOWN_CATEGORIES)
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_inventory.py -q`
Expected: new tests FAIL (`AttributeError: 'Target' object has no attribute 'zone_map'`).

- [ ] **Step 4: Implement**

In `srxsync/inventory.py`: change `from dataclasses import dataclass` to `from dataclasses import dataclass, field`, then:

```python
@dataclass(frozen=True)
class Target:
    host: str
    auth: Auth
    include: list[str]
    zone_map: dict[str, str] = field(default_factory=dict)
```

In `_parse_target`, pass `zone_map=_parse_zone_map(raw["host"], raw.get("zone_map"))` to `Target(...)`, and add:

```python
def _parse_zone_map(host: str, raw: Any) -> dict[str, str]:
    """Validate a target's master→slave zone_map; None or absent means no translation."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise InventoryError(f"target {host} zone_map must be a mapping")
    for master_zone, slave_zone in raw.items():
        valid = (
            isinstance(master_zone, str)
            and isinstance(slave_zone, str)
            and master_zone
            and slave_zone
        )
        if not valid:
            raise InventoryError(
                f"target {host} zone_map entries must be non-empty strings: "
                f"{master_zone!r}: {slave_zone!r}"
            )
    return dict(raw)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests/unit -q && .venv/bin/ruff check srxsync tests`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add srxsync/inventory.py tests/unit/test_inventory.py tests/fixtures/inventory/zone_map.yaml tests/fixtures/inventory/zone_map_bad.yaml
git commit -m "feat(inventory): add per-target zone_map (#11)"
```

---

### Task 2: `ZoneTranslator` — renames and de-duplication

**Files:**
- Create: `srxsync/zonemap.py`, `tests/fixtures/configs/zones_master.xml`
- Test: `tests/unit/test_zonemap.py`

**Interfaces:**
- Produces:
  - `ZONES_PATH = "/configuration/security/zones"`
  - `class ZoneTranslationError(ValueError)`
  - `@dataclass(frozen=True) class ZoneTranslator: zone_map: dict[str, str]`
  - `ZoneTranslator.translate(zone: str) -> str`
  - `ZoneTranslator.apply(config: etree._Element) -> etree._Element` — returns a translated deep copy; never mutates `config`. (Task 3 extends `apply` with context merging and zone handling.)

- [ ] **Step 1: Write the fixture** `tests/fixtures/configs/zones_master.xml`

```xml
<configuration>
  <security>
    <address-book>
      <name>global</name>
      <address><name>WEB</name><ip-prefix>10.1.0.10/32</ip-prefix></address>
      <attach>
        <zone><name>APP1</name></zone>
        <zone><name>APP2</name></zone>
      </attach>
    </address-book>
    <zones>
      <security-zone>
        <name>APP1</name>
        <host-inbound-traffic><system-services><name>ping</name></system-services></host-inbound-traffic>
        <interfaces><name>ge-0/0/1.0</name></interfaces>
      </security-zone>
      <security-zone>
        <name>APP2</name>
        <screen>app2-screen</screen>
        <interfaces><name>ge-0/0/2.0</name></interfaces>
      </security-zone>
      <security-zone>
        <name>APP3</name>
        <interfaces><name>ge-0/0/3.0</name></interfaces>
      </security-zone>
      <security-zone>
        <name>UNTRUST</name>
        <screen>untrust-screen</screen>
        <interfaces><name>ge-0/0/0.0</name></interfaces>
      </security-zone>
    </zones>
    <policies>
      <policy>
        <from-zone-name>APP1</from-zone-name>
        <to-zone-name>UNTRUST</to-zone-name>
        <policy><name>app1-web</name><match><source-address>any</source-address><destination-address>any</destination-address><application>junos-http</application></match><then><permit/></then></policy>
      </policy>
      <policy>
        <from-zone-name>APP1</from-zone-name>
        <to-zone-name>APP2</to-zone-name>
        <policy><name>app1-to-app2</name><match><source-address>any</source-address><destination-address>any</destination-address><application>any</application></match><then><permit/></then></policy>
      </policy>
      <policy>
        <from-zone-name>APP2</from-zone-name>
        <to-zone-name>UNTRUST</to-zone-name>
        <policy><name>app2-web</name><match><source-address>any</source-address><destination-address>any</destination-address><application>junos-http</application></match><then><permit/></then></policy>
        <policy><name>app2-dns</name><match><source-address>any</source-address><destination-address>any</destination-address><application>junos-dns-udp</application></match><then><permit/></then></policy>
      </policy>
      <policy>
        <from-zone-name>APP3</from-zone-name>
        <to-zone-name>UNTRUST</to-zone-name>
        <policy><name>app3-ssh</name><match><source-address>any</source-address><destination-address>any</destination-address><application>junos-ssh</application></match><then><permit/></then></policy>
      </policy>
      <global>
        <policy>
          <name>global-deny-telnet</name>
          <match><source-address>any</source-address><destination-address>any</destination-address><application>junos-telnet</application><from-zone>APP1</from-zone><from-zone>APP2</from-zone><to-zone>UNTRUST</to-zone></match>
          <then><deny/></then>
        </policy>
      </global>
    </policies>
    <nat>
      <source>
        <rule-set>
          <name>apps-out</name>
          <from><zone>APP1</zone><zone>APP2</zone><zone>APP3</zone></from>
          <to><zone>UNTRUST</zone></to>
          <rule><name>r1</name><src-nat-rule-match><source-address>0.0.0.0/0</source-address></src-nat-rule-match><then><source-nat><interface/></source-nat></then></rule>
        </rule-set>
      </source>
      <destination>
        <rule-set>
          <name>inbound</name>
          <from><zone>UNTRUST</zone></from>
          <rule><name>d1</name><dest-nat-rule-match><destination-address><dst-addr>203.0.113.10/32</dst-addr></destination-address></dest-nat-rule-match><then><destination-nat><off/></destination-nat></then></rule>
        </rule-set>
      </destination>
    </nat>
  </security>
</configuration>
```

- [ ] **Step 2: Write the failing tests** `tests/unit/test_zonemap.py`

```python
from pathlib import Path

from lxml import etree

from srxsync.zonemap import ZoneTranslator

FIXTURE = Path(__file__).parent.parent / "fixtures" / "configs" / "zones_master.xml"
APPS_MAP = {"APP1": "APPS", "APP2": "APPS", "APP3": "APPS"}


def _load() -> etree._Element:
    return etree.parse(str(FIXTURE)).getroot()


def _texts(config: etree._Element, xpath: str) -> list[str]:
    return [node.text for node in config.xpath(xpath)]


def test_empty_map_is_identity():
    source = _load()
    translated = ZoneTranslator({}).apply(source)
    assert etree.tostring(translated) == etree.tostring(source)


def test_apply_does_not_mutate_input():
    source = _load()
    before = etree.tostring(source)
    ZoneTranslator(APPS_MAP).apply(source)
    assert etree.tostring(source) == before


def test_translate_unmapped_is_identity():
    translator = ZoneTranslator(APPS_MAP)
    assert translator.translate("APP1") == "APPS"
    assert translator.translate("UNTRUST") == "UNTRUST"


def test_single_pass_no_chaining():
    translator = ZoneTranslator({"A": "B", "B": "C"})
    assert translator.translate("A") == "B"
    assert translator.translate("B") == "C"


def test_one_to_one_rename_everywhere():
    translated = ZoneTranslator({"UNTRUST": "OUTSIDE"}).apply(_load())
    assert "UNTRUST" not in etree.tostring(translated).decode()
    assert _texts(translated, "security/nat/destination/rule-set/from/zone") == ["OUTSIDE"]
    assert "OUTSIDE" in _texts(translated, "security/zones/security-zone/name")


def test_global_policy_zones_renamed_and_deduped():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    match = "security/policies/global/policy/match"
    assert _texts(translated, f"{match}/from-zone") == ["APPS"]
    assert _texts(translated, f"{match}/to-zone") == ["UNTRUST"]


def test_nat_zone_lists_renamed_and_deduped():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    assert _texts(translated, "security/nat/source/rule-set/from/zone") == ["APPS"]
    assert _texts(translated, "security/nat/source/rule-set/to/zone") == ["UNTRUST"]


def test_address_book_attach_renamed_and_deduped():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    assert _texts(translated, "security/address-book/attach/zone/name") == ["APPS"]
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_zonemap.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'srxsync.zonemap'`).

- [ ] **Step 4: Implement** `srxsync/zonemap.py`

```python
"""Per-target zone-name translation of a fetched master config."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from lxml import etree

ZONES_PATH = "/configuration/security/zones"

# Leaf-list zone references: (XPath of the parent, child tag holding a zone name).
_ZONE_LISTS = (
    ("security/policies/global/policy/match", "from-zone"),
    ("security/policies/global/policy/match", "to-zone"),
    ("security/nat/*/rule-set/from", "zone"),
    ("security/nat/*/rule-set/to", "zone"),
)


class ZoneTranslationError(ValueError):
    """Raised when a translated config cannot be built for a target."""


@dataclass(frozen=True)
class ZoneTranslator:
    """Rewrites master zone names to a target's zone names (master → slave)."""

    zone_map: dict[str, str]

    def translate(self, zone: str) -> str:
        """Return the slave name for a master zone; unmapped zones keep their name."""
        return self.zone_map.get(zone, zone)

    def apply(self, config: etree._Element) -> etree._Element:
        """Return a translated deep copy of ``config``; the input is never mutated."""
        translated = copy.deepcopy(config)
        if not self.zone_map:
            return translated
        self._rename_zone_lists(translated)
        self._rename_attach_zones(translated)
        self._rename_policy_contexts(translated)
        self._rename_zone_definitions(translated)
        return translated

    def _rename_zone_lists(self, config: etree._Element) -> None:
        for parent_xpath, tag in _ZONE_LISTS:
            for parent in config.xpath(parent_xpath):
                seen: set[str] = set()
                for entry in parent.findall(tag):
                    entry.text = self.translate(entry.text or "")
                    if entry.text in seen:
                        parent.remove(entry)
                        continue
                    seen.add(entry.text)

    def _rename_attach_zones(self, config: etree._Element) -> None:
        for attach in config.xpath("security/address-book/attach"):
            seen: set[str] = set()
            for zone in attach.findall("zone"):
                name = zone.find("name")
                if name is None:
                    continue
                name.text = self.translate(name.text or "")
                if name.text in seen:
                    attach.remove(zone)
                    continue
                seen.add(name.text)

    def _rename_policy_contexts(self, config: etree._Element) -> None:
        for tag in ("from-zone-name", "to-zone-name"):
            for node in config.xpath(f"security/policies/policy/{tag}"):
                node.text = self.translate(node.text or "")

    def _rename_zone_definitions(self, config: etree._Element) -> None:
        for name in config.xpath("security/zones/security-zone/name"):
            name.text = self.translate(name.text or "")
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests/unit -q && .venv/bin/ruff check srxsync tests && .venv/bin/mypy srxsync`
Expected: tests pass, ruff clean, mypy clean.

- [ ] **Step 6: Commit**

```bash
git add srxsync/zonemap.py tests/unit/test_zonemap.py tests/fixtures/configs/zones_master.xml
git commit -m "feat(zonemap): translate zone references in policies, NAT and address-book (#11)"
```

---

### Task 3: `ZoneTranslator` — merge policy contexts and N:1 zone shells

**Files:**
- Modify: `srxsync/zonemap.py`
- Test: `tests/unit/test_zonemap.py`

**Interfaces:**
- Consumes: Task 2's `ZoneTranslator`, `ZoneTranslationError`.
- Produces:
  - `ZoneTranslator.merged_zones(config: etree._Element) -> frozenset[str]` — slave zone names whose preimage has ≥2 master zones. Preimage = mapped keys translating to the zone, plus an identically named **unmapped** zone defined on the master (`security/zones`).
  - `ZoneTranslator.unknown_keys(config: etree._Element) -> list[str]` — `zone_map` keys not defined as zones on the master; `[]` when the config has no `security/zones` (zones not fetched).
  - `apply()` now: merges contexts that collapse to one `(from, to)` pair (master order; duplicate rule names raise `ZoneTranslationError`), and reduces N:1 zones to one empty `<security-zone><name>Z</name></security-zone>` at the first occurrence's position.

- [ ] **Step 1: Write the failing tests** — add `import pytest` to the imports at the top of `tests/unit/test_zonemap.py`, change the zonemap import to `from srxsync.zonemap import ZoneTranslationError, ZoneTranslator`, then append:

```python
def _context_rules(config: etree._Element, from_zone: str, to_zone: str) -> list[str]:
    contexts = [
        ctx
        for ctx in config.xpath("security/policies/policy")
        if ctx.findtext("from-zone-name") == from_zone and ctx.findtext("to-zone-name") == to_zone
    ]
    assert len(contexts) == 1, f"expected one {from_zone}->{to_zone} context, got {len(contexts)}"
    return [rule.findtext("name") for rule in contexts[0].findall("policy")]


def test_collapsed_contexts_concatenated_in_master_order():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    assert _context_rules(translated, "APPS", "UNTRUST") == [
        "app1-web",
        "app2-web",
        "app2-dns",
        "app3-ssh",
    ]


def test_contexts_between_merged_zones_become_intra_zone():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    assert _context_rules(translated, "APPS", "APPS") == ["app1-to-app2"]


def test_duplicate_rule_name_in_merged_context_raises():
    source = _load()
    app3_rule = source.xpath(
        "security/policies/policy[from-zone-name='APP3']/policy/name"
    )[0]
    app3_rule.text = "app1-web"
    with pytest.raises(ZoneTranslationError, match=r"app1-web.*APP1->UNTRUST.*APP3->UNTRUST"):
        ZoneTranslator(APPS_MAP).apply(source)


def test_merged_zones():
    source = _load()
    assert ZoneTranslator(APPS_MAP).merged_zones(source) == frozenset({"APPS"})
    assert ZoneTranslator({"UNTRUST": "OUTSIDE"}).merged_zones(source) == frozenset()


def test_merged_zones_counts_unmapped_master_zone_with_same_name():
    source = _load()
    assert ZoneTranslator({"APP1": "UNTRUST"}).merged_zones(source) == frozenset({"UNTRUST"})


def test_n_to_one_zone_becomes_single_empty_shell():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    apps = translated.xpath("security/zones/security-zone[name='APPS']")
    assert len(apps) == 1
    assert [child.tag for child in apps[0]] == ["name"]


def test_one_to_one_zone_keeps_settings():
    translated = ZoneTranslator(APPS_MAP).apply(_load())
    untrust = translated.xpath("security/zones/security-zone[name='UNTRUST']")[0]
    assert untrust.findtext("screen") == "untrust-screen"


def test_unknown_keys():
    source = _load()
    translator = ZoneTranslator({"APP1": "APPS", "NOPE": "APPS"})
    assert translator.unknown_keys(source) == ["NOPE"]


def test_unknown_keys_empty_when_zones_not_fetched():
    config = etree.fromstring("<configuration><security><policies/></security></configuration>")
    assert ZoneTranslator({"NOPE": "APPS"}).unknown_keys(config) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_zonemap.py -q`
Expected: new tests FAIL (multiple `APPS->UNTRUST` contexts; `merged_zones` missing).

- [ ] **Step 3: Implement** — in `srxsync/zonemap.py`, replace `_rename_policy_contexts` and `_rename_zone_definitions`, and add the two public methods:

```python
    def merged_zones(self, config: etree._Element) -> frozenset[str]:
        """Slave zones fed by two or more master zones (N:1); their settings stay slave-owned."""
        master_zones = set(_master_zone_names(config))
        preimage_sizes: dict[str, int] = {}
        for master_zone in self.zone_map:
            slave_zone = self.zone_map[master_zone]
            preimage_sizes[slave_zone] = preimage_sizes.get(slave_zone, 0) + 1
        for master_zone in master_zones:
            if master_zone in self.zone_map:
                continue
            if master_zone in preimage_sizes:
                preimage_sizes[master_zone] += 1
        return frozenset(zone for zone, size in preimage_sizes.items() if size >= 2)

    def unknown_keys(self, config: etree._Element) -> list[str]:
        """zone_map keys that are not zones on the master; empty if zones were not fetched."""
        if not config.xpath("security/zones"):
            return []
        master_zones = set(_master_zone_names(config))
        return [key for key in self.zone_map if key not in master_zones]

    def _rename_policy_contexts(self, config: etree._Element) -> None:
        """Rename context zones and merge contexts that collapse onto the same pair."""
        for policies in config.xpath("security/policies"):
            keepers: dict[tuple[str, str], etree._Element] = {}
            # rule name -> "FROM->TO" of the master context it came from, per kept pair
            rule_origins: dict[tuple[str, str], dict[str, str]] = {}
            for context in policies.findall("policy"):
                from_node = context.find("from-zone-name")
                to_node = context.find("to-zone-name")
                if from_node is None or to_node is None:
                    continue
                origin = f"{from_node.text}->{to_node.text}"
                from_node.text = self.translate(from_node.text or "")
                to_node.text = self.translate(to_node.text or "")
                pair = (from_node.text, to_node.text)
                keeper = keepers.get(pair)
                if keeper is None:
                    keepers[pair] = context
                    rule_origins[pair] = {
                        rule.findtext("name") or "": origin for rule in context.findall("policy")
                    }
                    continue
                origins = rule_origins[pair]
                for rule in context.findall("policy"):
                    rule_name = rule.findtext("name") or ""
                    if rule_name in origins:
                        raise ZoneTranslationError(
                            f"duplicate policy {rule_name} in merged context "
                            f"{pair[0]}->{pair[1]}: from {origins[rule_name]} and {origin}"
                        )
                    origins[rule_name] = origin
                    keeper.append(rule)
                policies.remove(context)

    def _rename_zone_definitions(self, config: etree._Element) -> None:
        """Rename 1:1 zones; reduce N:1 zones to one empty shell (settings stay slave-owned)."""
        merged = self.merged_zones(config)
        for zones in config.xpath("security/zones"):
            shells_written: set[str] = set()
            for zone in zones.findall("security-zone"):
                name = zone.find("name")
                if name is None:
                    continue
                slave_name = self.translate(name.text or "")
                if slave_name not in merged:
                    name.text = slave_name
                    continue
                if slave_name in shells_written:
                    zones.remove(zone)
                    continue
                shell = etree.Element("security-zone")
                etree.SubElement(shell, "name").text = slave_name
                zones.replace(zone, shell)
                shells_written.add(slave_name)
```

Note: `_rename_zone_definitions` must call `merged_zones` **before** any renaming of zone names — it does, because `merged_zones` reads master names first and the loop renames afterwards. Keep `apply()` calling `_rename_zone_definitions` last; `merged_zones` only reads `security/zones`, which the earlier steps don't touch.

Add the module-level helper:

```python
def _master_zone_names(config: etree._Element) -> list[str]:
    return [name.text or "" for name in config.xpath("security/zones/security-zone/name")]
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit -q && .venv/bin/ruff check srxsync tests && .venv/bin/mypy srxsync`
Expected: all pass; mypy clean.

- [ ] **Step 5: Commit**

```bash
git add srxsync/zonemap.py tests/unit/test_zonemap.py
git commit -m "feat(zonemap): merge collapsed policy contexts and push N:1 zones as shells (#11)"
```

---

### Task 4: Zones are never replaced

**Files:**
- Modify: `srxsync/diff.py`
- Test: `tests/unit/test_diff.py`

**Interfaces:**
- Consumes: `ZONES_PATH` from `srxsync.zonemap`.
- Produces: `DiffBuilder.build(..., mode="replace")` sets `replace="replace"` on every configured root **except** `security/zones`.

- [ ] **Step 1: Write the failing test** (append to `tests/unit/test_diff.py`)

```python
def test_replace_mode_never_marks_zones():
    src = _load()
    builder = DiffBuilder(
        paths=["/configuration/security/policies", "/configuration/security/zones"],
        prune=["security-zone/interfaces"],
    )
    out = builder.build(src, mode="replace")
    assert out.find(".//policies").get("replace") == "replace"
    assert out.find(".//zones").get("replace") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_diff.py::test_replace_mode_never_marks_zones -q`
Expected: FAIL (`assert 'replace' is None`).

- [ ] **Step 3: Implement** — in `srxsync/diff.py` add `from srxsync.zonemap import ZONES_PATH` and change `_mark_replace`:

```python
    def _mark_replace(self, out: etree._Element) -> None:
        """Add replace="replace" attribute on each category-root element.

        For each configured path like /configuration/security/policies, find
        the element at that path in the payload and set replace="replace".
        Junos then replaces that subtree wholesale on the target device — the
        semantic users expect from --replace.

        security/zones is always merged: srxsync never deletes a slave zone, and
        replacing it would also wipe the (pruned) interface bindings.
        """
        for abs_path in self.paths:
            if abs_path == ZONES_PATH:
                continue
            rel = abs_path.removeprefix("/configuration/")
            for node in out.xpath(rel):
                node.set("replace", "replace")
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit -q && .venv/bin/ruff check srxsync tests`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add srxsync/diff.py tests/unit/test_diff.py
git commit -m "fix(diff): never replace security zones, only merge (#11)"
```

---

### Task 5: Empty-zone warnings

**Files:**
- Create: `srxsync/zonewarn.py`
- Test: `tests/unit/test_zonewarn.py`

**Interfaces:**
- Produces: `zone_warnings(payload: etree._Element, target_config: etree._Element, host: str) -> list[str]`
  - `payload`: the `DiffBuilder` output about to be loaded.
  - `target_config`: the target's fetched `security/zones` (unpruned, so interfaces are visible).
  - Referenced zones = zones defined in `payload` `security/zones` ∪ zones named in payload policy contexts, global-policy `from-zone`/`to-zone`, NAT `from/to zone`, address-book `attach zone`. Ignore `junos-host` and `any`.
  - For each referenced zone, sorted: on target with no `interfaces` → "exists" warning; not on target and defined in payload → "creating" warning; not on target and not in payload → `<host>: zone <Z> is referenced but missing on the slave — add "zones" to include or create it`.

- [ ] **Step 1: Write the failing tests** `tests/unit/test_zonewarn.py`

```python
from lxml import etree

from srxsync.zonewarn import zone_warnings

BIND_HINT = (
    "bind an interface on the slave "
    "(set security zones security-zone {zone} interfaces <ifl>)"
)


def _xml(text: str) -> etree._Element:
    return etree.fromstring(text)


TARGET = _xml(
    "<configuration><security><zones>"
    "<security-zone><name>UNTRUST</name>"
    "<interfaces><name>ge-0/0/0.0</name></interfaces></security-zone>"
    "<security-zone><name>EMPTY</name></security-zone>"
    "</zones></security></configuration>"
)


def test_creating_zone_warns():
    payload = _xml(
        "<configuration><security><zones>"
        "<security-zone><name>APPS</name></security-zone>"
        "</zones></security></configuration>"
    )
    assert zone_warnings(payload, TARGET, host="srx-a") == [
        f"srx-a: creating zone APPS with no interfaces — {BIND_HINT.format(zone='APPS')}"
    ]


def test_existing_zone_without_interfaces_warns():
    payload = _xml(
        "<configuration><security><policies><policy>"
        "<from-zone-name>EMPTY</from-zone-name><to-zone-name>UNTRUST</to-zone-name>"
        "</policy></policies></security></configuration>"
    )
    assert zone_warnings(payload, TARGET, host="srx-a") == [
        f"srx-a: zone EMPTY exists with no interfaces — {BIND_HINT.format(zone='EMPTY')}"
    ]


def test_zone_with_interfaces_is_silent():
    payload = _xml(
        "<configuration><security><nat><source><rule-set><name>rs</name>"
        "<to><zone>UNTRUST</zone></to></rule-set></source></nat></security></configuration>"
    )
    assert zone_warnings(payload, TARGET, host="srx-a") == []


def test_referenced_but_missing_zone_warns():
    payload = _xml(
        "<configuration><security><policies><global><policy><name>g</name><match>"
        "<from-zone>APPS</from-zone><to-zone>UNTRUST</to-zone>"
        "</match></policy></global></policies></security></configuration>"
    )
    assert zone_warnings(payload, TARGET, host="srx-a") == [
        'srx-a: zone APPS is referenced but missing on the slave — add "zones" to include '
        "or create it"
    ]


def test_special_zones_ignored():
    payload = _xml(
        "<configuration><security><policies><policy>"
        "<from-zone-name>junos-host</from-zone-name><to-zone-name>UNTRUST</to-zone-name>"
        "</policy></policies></security></configuration>"
    )
    assert zone_warnings(payload, TARGET, host="srx-a") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_zonewarn.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** `srxsync/zonewarn.py`

```python
"""Warn about slave zones that srxsync creates or references but that carry no interfaces."""

from __future__ import annotations

from lxml import etree

_SPECIAL_ZONES = frozenset({"junos-host", "any"})

_REFERENCE_XPATHS = (
    "security/policies/policy/from-zone-name",
    "security/policies/policy/to-zone-name",
    "security/policies/global/policy/match/from-zone",
    "security/policies/global/policy/match/to-zone",
    "security/nat/*/rule-set/from/zone",
    "security/nat/*/rule-set/to/zone",
    "security/address-book/attach/zone/name",
)


def zone_warnings(payload: etree._Element, target_config: etree._Element, host: str) -> list[str]:
    """Return warnings for payload zones that are new, empty, or missing on the target."""
    defined_in_payload = set(_zone_names(payload))
    referenced = set(defined_in_payload)
    for xpath in _REFERENCE_XPATHS:
        referenced.update(node.text or "" for node in payload.xpath(xpath))
    referenced -= _SPECIAL_ZONES
    referenced.discard("")

    target_has_interfaces = {
        zone.findtext("name") or "": zone.find("interfaces") is not None
        for zone in target_config.xpath("security/zones/security-zone")
    }

    warnings: list[str] = []
    for zone in sorted(referenced):
        warning = _warning_for(zone, host, target_has_interfaces, defined_in_payload)
        if warning is not None:
            warnings.append(warning)
    return warnings


def _warning_for(
    zone: str,
    host: str,
    target_has_interfaces: dict[str, bool],
    defined_in_payload: set[str],
) -> str | None:
    hint = (
        "bind an interface on the slave "
        f"(set security zones security-zone {zone} interfaces <ifl>)"
    )
    if zone in target_has_interfaces:
        if target_has_interfaces[zone]:
            return None
        return f"{host}: zone {zone} exists with no interfaces — {hint}"
    if zone in defined_in_payload:
        return f"{host}: creating zone {zone} with no interfaces — {hint}"
    return (
        f'{host}: zone {zone} is referenced but missing on the slave — add "zones" to include '
        "or create it"
    )


def _zone_names(config: etree._Element) -> list[str]:
    return [name.text or "" for name in config.xpath("security/zones/security-zone/name")]
```

Note: when the payload was pruned of interfaces, a zone created via a 1:1 rename also has none on the slave until bound — the "creating" warning is correct for it too.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit -q && .venv/bin/ruff check srxsync tests && .venv/bin/mypy srxsync`
Expected: all pass; mypy clean.

- [ ] **Step 5: Commit**

```bash
git add srxsync/zonewarn.py tests/unit/test_zonewarn.py
git commit -m "feat(zonewarn): warn about created or empty slave zones (#11)"
```

---

### Task 6: Drift ignores N:1 zone content

**Files:**
- Modify: `srxsync/drift.py`
- Test: `tests/unit/test_drift.py`

**Interfaces:**
- Consumes: `ZONES_PATH`.
- Produces: `DriftDetector(paths, prune, merged_zones: frozenset[str] = frozenset())`. For each zone in `merged_zones`: its `security-zone` element is removed from both scoped trees before comparison; if it is missing on the target, `ZONES_PATH` is reported as differing (only when `ZONES_PATH` is in `paths`).

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_drift.py`)

```python
def _zones(*zones: str) -> etree._Element:
    body = "".join(zones)
    return etree.fromstring(
        f"<configuration><security><zones>{body}</zones></security></configuration>"
    )


ZONES = "/configuration/security/zones"


def test_merged_zone_content_ignored():
    src = _zones("<security-zone><name>APPS</name></security-zone>")
    tgt = _zones("<security-zone><name>APPS</name><screen>local</screen></security-zone>")
    det = DriftDetector(paths=[ZONES], prune=[], merged_zones=frozenset({"APPS"}))
    assert det.diff(src, tgt).in_sync is True


def test_merged_zone_missing_on_target_is_drift():
    src = _zones("<security-zone><name>APPS</name></security-zone>")
    tgt = _zones()
    det = DriftDetector(paths=[ZONES], prune=[], merged_zones=frozenset({"APPS"}))
    assert det.diff(src, tgt).differing_paths == [ZONES]


def test_non_merged_zone_content_still_compared():
    src = _zones("<security-zone><name>UNTRUST</name><screen>a</screen></security-zone>")
    tgt = _zones("<security-zone><name>UNTRUST</name><screen>b</screen></security-zone>")
    det = DriftDetector(paths=[ZONES], prune=[], merged_zones=frozenset({"APPS"}))
    assert det.diff(src, tgt).differing_paths == [ZONES]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_drift.py -q`
Expected: FAIL (`TypeError: unexpected keyword argument 'merged_zones'`).

- [ ] **Step 3: Implement** — `srxsync/drift.py` (upstream #3 already compares `findall()` lists in document order; keep that and its comment, only add the merged-zone handling):

```python
from srxsync.diff import DiffBuilder
from srxsync.zonemap import ZONES_PATH


@dataclass(frozen=True)
class DriftDetector:
    paths: list[str]
    prune: list[str]
    merged_zones: frozenset[str] = frozenset()

    def diff(self, source: etree._Element, target: etree._Element, host: str = "") -> DriftReport:
        builder = DiffBuilder(paths=self.paths, prune=self.prune)
        src_scoped = builder.build(source)
        tgt_scoped = builder.build(target)
        missing_merged = self._missing_merged_zones(tgt_scoped)
        self._drop_merged_zones(src_scoped)
        self._drop_merged_zones(tgt_scoped)

        differing: list[str] = []
        for abs_path in self.paths:
            rel = abs_path.removeprefix("/configuration/")
            # (keep the existing comment block about comparing full sibling lists in order)
            src_nodes = [_canonicalize(n) for n in src_scoped.findall(rel)]
            tgt_nodes = [_canonicalize(n) for n in tgt_scoped.findall(rel)]
            zone_missing = abs_path == ZONES_PATH and bool(missing_merged)
            if zone_missing or src_nodes != tgt_nodes:
                differing.append(abs_path)
        return DriftReport(host=host, differing_paths=differing)

    def _missing_merged_zones(self, target_scoped: etree._Element) -> set[str]:
        """N:1 zones are slave-owned: only their existence on the target is checked."""
        present = {
            name.text for name in target_scoped.xpath("security/zones/security-zone/name")
        }
        return set(self.merged_zones) - present

    def _drop_merged_zones(self, scoped: etree._Element) -> None:
        for zone in scoped.xpath("security/zones/security-zone"):
            if zone.findtext("name") in self.merged_zones:
                zone.getparent().remove(zone)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit -q && .venv/bin/ruff check srxsync tests && .venv/bin/mypy srxsync`
Expected: all pass; mypy clean.

- [ ] **Step 5: Commit**

```bash
git add srxsync/drift.py tests/unit/test_drift.py
git commit -m "feat(drift): compare N:1 zones by existence only (#11)"
```

---

### Task 7: Warnings in results and CLI

**Files:**
- Modify: `srxsync/results.py`, `srxsync/cli.py`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Produces: `TargetResult.warnings: list[str]` and `DriftLine.warnings: list[str]` (default empty, last field). `_print_push_summary` / `_print_drift_summary` print every warning to stderr as `WARNING <warning>` after the table.

- [ ] **Step 1: Write the failing tests** — in `tests/unit/test_cli.py` change the import to `from srxsync.cli import _print_drift_summary, _print_push_summary, build_parser` and add `from srxsync.results import DriftLine, DriftSummary, PushSummary, TargetResult` at the top, then append:

```python
def test_push_summary_prints_warnings_to_stderr(capsys):
    summary = PushSummary(
        results=[TargetResult(host="srx-a", ok=True, warnings=["srx-a: creating zone APPS"])]
    )
    _print_push_summary(summary)
    captured = capsys.readouterr()
    assert "WARNING srx-a: creating zone APPS" in captured.err
    assert "WARNING" not in captured.out


def test_drift_summary_prints_warnings_to_stderr(capsys):
    summary = DriftSummary(
        reports=[DriftLine(host="srx-a", in_sync=True, warnings=["srx-a: zone APPS exists"])]
    )
    _print_drift_summary(summary, verbose=False)
    assert "WARNING srx-a: zone APPS exists" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_cli.py -q`
Expected: FAIL (`unexpected keyword argument 'warnings'`).

- [ ] **Step 3: Implement**

`srxsync/results.py` — add as the last field of both `TargetResult` and `DriftLine`:
```python
    warnings: list[str] = field(default_factory=list)
```

`srxsync/cli.py` — at the end of `_print_push_summary`:
```python
    _print_warnings(warning for result in summary.results for warning in result.warnings)
```
at the end of `_print_drift_summary` (after the loop):
```python
    _print_warnings(warning for line in summary.reports for warning in line.warnings)
```
and add (with `from collections.abc import Iterable` in the imports):
```python
def _print_warnings(warnings: Iterable[str]) -> None:
    for warning in warnings:
        print(f"WARNING {warning}", file=sys.stderr)
```


- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit -q && .venv/bin/ruff check srxsync tests && .venv/bin/mypy srxsync`
Expected: all pass; mypy clean.

- [ ] **Step 5: Commit**

```bash
git add srxsync/results.py srxsync/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): print per-target warnings to stderr (#11)"
```

---

### Task 8: Orchestrator wiring

**Files:**
- Modify: `srxsync/orchestrator.py`
- Test: `tests/unit/test_zone_orchestrator.py` (new — `tests/unit/test_orchestrator.py` already exists upstream with its own `_FakeTransport`; leave it untouched)

**Interfaces:**
- Consumes: `Target.zone_map` (T1), `ZoneTranslator`, `ZoneTranslationError`, `ZONES_PATH` (T2/T3), `zone_warnings` (T5), `DriftDetector(merged_zones=...)` (T6), `warnings` fields (T7).
- Produces: push and check translate the source per target, emit warnings, and fail only the affected target on `ZoneTranslationError`.

Behaviour:
- **push** (`_push_target`): `translator = ZoneTranslator(target.zone_map)`; `translated = translator.apply(source_xml)`; connect; `payload = DiffBuilder(...).build(translated, mode=cfg.mode)`; `target_zones = t.fetch([ZONES_PATH])`; `warnings = unknown-key warnings + zone_warnings(payload, target_zones, host=target.host)`; return warnings on success and on dry-run. The existing broad `except Exception` (upstream #3) already turns `ZoneTranslationError` into a per-target failure — keep it unchanged.
- **check** (`_check_target`): translate the same way; `target_xml = t.fetch(paths)`, and if `ZONES_PATH` not in `paths` also `zone_view = t.fetch([ZONES_PATH])` else `zone_view = target_xml`; detector gets `merged_zones=translator.merged_zones(source_xml)`; warnings from `zone_warnings(DiffBuilder(paths, prune).build(translated), zone_view, host)` plus unknown keys. The existing `except Exception` already maps `ZoneTranslationError` to `DriftLine(error=...)`.
- Unknown-key warning text: `<host>: zone_map key <KEY> is not a zone on the master`.

- [ ] **Step 1: Write the failing tests** `tests/unit/test_zone_orchestrator.py`

```python
import asyncio
from pathlib import Path
from typing import ClassVar, Literal

import pytest
from lxml import etree

from srxsync import orchestrator as orchestrator_module
from srxsync.categories import CategoryModel
from srxsync.diff import DiffBuilder
from srxsync.inventory import Auth, Device, Inventory, Target
from srxsync.orchestrator import Orchestrator, RunConfig
from srxsync.secrets.base import Secret
from srxsync.transport.base import Transport

FX = Path(__file__).parent.parent / "fixtures" / "configs"
APPS_MAP = {"APP1": "APPS", "APP2": "APPS", "APP3": "APPS"}
SLAVE = (
    "<configuration><security><zones>"
    "<security-zone><name>UNTRUST</name><interfaces><name>ge-0/0/0.0</name></interfaces>"
    "</security-zone></zones></security></configuration>"
)


class FakeTransport(Transport):
    configs: ClassVar[dict[str, etree._Element]] = {}
    loaded: ClassVar[dict[str, etree._Element]] = {}

    def connect(
        self,
        host: str,
        username: str,
        password: str | None = None,
        ssh_key: str | None = None,
        port: int = 22,
    ) -> None:
        self._host = host

    def fetch(self, paths: list[str]) -> etree._Element:
        return DiffBuilder(paths=paths, prune=[]).build(self.configs[self._host])

    def load(self, xml: etree._Element, mode: Literal["replace", "merge"]) -> None:
        self.loaded[self._host] = xml

    def commit_confirmed(self, minutes: int) -> None:
        pass

    def confirm(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _fake_world(monkeypatch):
    FakeTransport.configs = {
        "master": etree.parse(str(FX / "zones_master.xml")).getroot(),
        "slave": etree.fromstring(SLAVE),
    }
    FakeTransport.loaded = {}
    monkeypatch.setattr(orchestrator_module, "get_secret", lambda host, auth: Secret(username="u"))


def _orchestrator(zone_map: dict[str, str], include: list[str]) -> Orchestrator:
    auth = Auth(provider="env")
    inventory = Inventory(
        source=Device(host="master", auth=auth),
        targets=[Target(host="slave", auth=auth, include=include, zone_map=zone_map)],
    )
    return Orchestrator(inventory, CategoryModel.default(), transport_factory=FakeTransport)


def _run_config(mode: Literal["replace", "merge"] = "replace") -> RunConfig:
    return RunConfig(mode=mode, commit_confirmed_minutes=1, max_parallel=1, on_error="continue")


def test_push_translates_and_warns():
    summary = asyncio.run(_orchestrator(APPS_MAP, ["policies", "zones"]).push(_run_config()))
    result = summary.results[0]
    assert result.ok, result.error
    payload = FakeTransport.loaded["slave"]
    contexts = {
        (ctx.findtext("from-zone-name"), ctx.findtext("to-zone-name"))
        for ctx in payload.xpath("security/policies/policy")
    }
    assert contexts == {("APPS", "UNTRUST"), ("APPS", "APPS")}
    assert payload.find("security/zones").get("replace") is None
    assert any("creating zone APPS with no interfaces" in w for w in result.warnings)


def test_push_translation_error_fails_only_that_target():
    master = FakeTransport.configs["master"]
    master.xpath("security/policies/policy[from-zone-name='APP3']/policy/name")[0].text = "app1-web"
    summary = asyncio.run(_orchestrator(APPS_MAP, ["policies"]).push(_run_config()))
    assert summary.results[0].ok is False
    assert "duplicate policy app1-web" in (summary.results[0].error or "")
    assert "slave" not in FakeTransport.loaded


def test_push_without_zone_map_payload_unchanged():
    asyncio.run(_orchestrator({}, ["policies"]).push(_run_config("merge")))
    expected = DiffBuilder(paths=["/configuration/security/policies"], prune=[]).build(
        FakeTransport.configs["master"]
    )
    assert etree.tostring(FakeTransport.loaded["slave"]) == etree.tostring(expected)


def test_check_reports_missing_merged_zone_and_warns_unknown_key():
    zone_map = {**APPS_MAP, "NOPE": "APPS"}
    summary = asyncio.run(_orchestrator(zone_map, ["zones"]).check(max_parallel=1))
    line = summary.reports[0]
    assert "/configuration/security/zones" in line.differing_paths
    assert "slave: zone_map key NOPE is not a zone on the master" in line.warnings
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_zone_orchestrator.py -q`
Expected: FAIL (untranslated contexts / no warnings).

- [ ] **Step 3: Implement** — `srxsync/orchestrator.py`

Imports:
```python
from srxsync.zonemap import ZONES_PATH, ZoneTranslator
from srxsync.zonewarn import zone_warnings
```

Replace `_push_target`'s body inside `try` and its `except` header:
```python
        try:
            paths, prune = self._cats.resolve(target.include)
            translator = ZoneTranslator(target.zone_map)
            translated = translator.apply(source_xml)
            secret = get_secret(host=target.host, auth=target.auth)
            t.connect(target.host, secret.username, secret.password, ssh_key=secret.ssh_key_path)
            payload = DiffBuilder(paths=paths, prune=list(prune)).build(translated, mode=cfg.mode)
            warnings = _unknown_key_warnings(translator, source_xml, target.host)
            warnings += zone_warnings(payload, t.fetch([ZONES_PATH]), host=target.host)

            if cfg.dry_run:
                return TargetResult(
                    host=target.host,
                    ok=True,
                    duration_s=time.monotonic() - start,
                    warnings=warnings,
                )

            t.load(payload, mode=cfg.mode)
            t.commit_confirmed(cfg.commit_confirmed_minutes)
            t.confirm()
            return TargetResult(
                host=target.host,
                ok=True,
                duration_s=time.monotonic() - start,
                warnings=warnings,
            )
        except Exception as e:  # unchanged from upstream
```
(rest of the `except Exception`/`finally` unchanged — do **not** narrow it).

Replace `_check_target`'s `try`/`except`:
```python
        try:
            paths, prune = self._cats.resolve(target.include)
            translator = ZoneTranslator(target.zone_map)
            translated = translator.apply(source_xml)
            secret = get_secret(host=target.host, auth=target.auth)
            t.connect(target.host, secret.username, secret.password, ssh_key=secret.ssh_key_path)
            target_xml = t.fetch(paths)
            zone_view = target_xml if ZONES_PATH in paths else t.fetch([ZONES_PATH])
            detector = DriftDetector(
                paths=paths,
                prune=list(prune),
                merged_zones=translator.merged_zones(source_xml),
            )
            rep: DriftReport = detector.diff(translated, target_xml, host=target.host)
            payload = DiffBuilder(paths=paths, prune=list(prune)).build(translated)
            warnings = _unknown_key_warnings(translator, source_xml, target.host)
            warnings += zone_warnings(payload, zone_view, host=target.host)
            return DriftLine(
                host=target.host,
                in_sync=rep.in_sync,
                differing_paths=list(rep.differing_paths),
                warnings=warnings,
            )
        except Exception as e:  # unchanged from upstream
            # unchanged upstream comment + return:
            return DriftLine(host=target.host, in_sync=False, error=str(e))
```

Module-level helper:
```python
def _unknown_key_warnings(
    translator: ZoneTranslator, source_xml: etree._Element, host: str
) -> list[str]:
    """Warn about zone_map keys that name no zone on the master (likely typos)."""
    return [
        f"{host}: zone_map key {key} is not a zone on the master"
        for key in translator.unknown_keys(source_xml)
    ]
```

Note: `merged_zones` takes the **untranslated** `source_xml` — it reads master zone names.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit -q && .venv/bin/ruff check srxsync tests && .venv/bin/mypy srxsync`
Expected: all pass; mypy clean.

- [ ] **Step 5: Commit**

```bash
git add srxsync/orchestrator.py tests/unit/test_zone_orchestrator.py
git commit -m "feat(orchestrator): apply zone translation and warnings in push and check (#11)"
```

---

### Task 9: README

**Files:**
- Modify: `README.md` (new `## Zone translation` section after `## Categories`; add one sentence to the `--replace` row of the CLI table)

- [ ] **Step 1: Edit the `--replace` table row** to append: ` security zones are always merged, never replaced.`

- [ ] **Step 2: Add the section**

````markdown
## Zone translation

A target can use different zone names than the master. Add a `zone_map`
(master zone → slave zone) to the target; unlisted zones keep their name.

```yaml
targets:
  - host: srx-site-a.example.net
    auth: { provider: env }
    include: [objects, policies, nat, zones]
    zone_map:
      APP1: APPS
      APP2: APPS
      APP3: APPS
```

- Zone names are rewritten in policies, global policies, NAT rule-sets and
  address-book `attach`.
- Policy contexts that collapse into one (`APP1→UNTRUST`, `APP2→UNTRUST` →
  `APPS→UNTRUST`) are concatenated in master order. A duplicate policy name in
  a merged context fails that target. `APP1→APP2` becomes `APPS→APPS`.
- **Zones are never deleted.** `security zones` is always merged, even with
  `--replace`. A zone fed by several master zones (`APPS`) is pushed as an
  empty zone: created if missing, otherwise left exactly as the slave has it.
- srxsync warns (stderr, never fails) when it creates a zone, or a zone exists,
  with no interfaces — bind one on the slave.
- Entries in a master zone's *own* address-book are not carried to a merged
  zone; keep shared objects in a global address-book.
````

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document zone translation (#11)"
```

---

### Task 10: Final gate and lab dry run

**Files:** none new.

Note: `rustperformance` was merged into `master` in #7 (rustez transport now lives on master), so no separate port is needed.

- [ ] **Step 1: Full local gate**

Run: `.venv/bin/pytest tests/unit -q && .venv/bin/ruff check srxsync tests && .venv/bin/mypy srxsync`
Expected: all pass; mypy clean.

- [ ] **Step 2: Lab dry run (optional, needs lab inventory)** — with a `tests/lab.yaml` inventory that has a `zone_map`, run `srxsync push --inventory tests/lab.yaml --merge --dry-run` and confirm the `WARNING ... creating zone` line on stderr. Do not run a non-dry push without the user's go-ahead.
