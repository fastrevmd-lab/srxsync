# Zone translation — Design Spec

**Date:** 2026-10-16
**Status:** Approved, ready for implementation planning
**Issue:** #11 (add zone translation)
**Branches:** `master` (rustperformance was merged into master in #7, so no separate port)

## Purpose

Master and slave SRXs do not always share a zone layout. The master may have
`APP1`, `APP2`, `APP3` and `UNTRUST` while a slave has only `APPS` and
`UNTRUST`. Each target gets a configurable master→slave zone mapping; srxsync
rewrites every zone reference in the synced config before pushing it.

srxsync runs after every change on the master, so the translation must be
idempotent and must never delete anything on the slave that the operator
created there.

## Inventory

New optional per-target key `zone_map`, master zone → slave zone:

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

- Zones not listed keep their name (identity). `UNTRUST` above stays `UNTRUST`.
- `zone_map` must be a mapping of non-empty strings to non-empty strings;
  anything else is an `InventoryError` at load time.
- Translation is single-pass, never chained: with `{A: B, B: C}`, master `A`
  becomes `B` and master `B` becomes `C`.
- A key that does not exist as a zone on the master is logged as a warning, not
  an error.
- `Target` gains `zone_map: dict[str, str]` (empty when absent). No `zone_map`
  means behaviour is byte-for-byte unchanged.

### Terms

For a target, the **preimage** of a slave zone is the set of master zones that
translate to it (mapped keys plus an identically named, unmapped master zone).

- **1:1 zone** — preimage has exactly one master zone (identity or rename).
- **N:1 zone** — preimage has two or more master zones (e.g. `APPS`).

## Translation — `srxsync/zonemap.py`

`ZoneTranslator(zone_map).apply(config) -> etree._Element` returns a translated
deep copy of the fetched master config; the input is never mutated. The
orchestrator calls it once per target, before `DiffBuilder`. Errors raise
`ZoneTranslationError`, which fails only that target.

Zone references rewritten:

| Category | Element | Rule |
|---|---|---|
| `policies` | `policy` context `from-zone-name` / `to-zone-name` | Rename, then merge contexts (below) |
| `policies` | `global/policy/match/from-zone`, `to-zone` | Rename each entry, de-duplicate, keep first-seen order |
| `nat` | `source`/`destination`/`static` `rule-set/from/zone`, `rule-set/to/zone` | Rename, de-duplicate |
| `objects` | `address-book/attach/zone` | Rename, de-duplicate |
| `zones` | `security-zone/name` | 1:1 renamed and kept; N:1 handled below |

### Merging policy contexts

After renaming, two or more contexts can share a `(from, to)` pair — e.g.
`APP1→UNTRUST`, `APP2→UNTRUST`, `APP3→UNTRUST` all become `APPS→UNTRUST`.

- Contexts are merged into one, its policies concatenated in master document
  order: all of the first context's policies (internal order kept), then the
  second's, and so on. Rule order on the slave therefore matches master order.
- A duplicate policy name within a merged context raises
  `ZoneTranslationError` naming the policy and both source contexts. No
  auto-renaming.
- Contexts between zones that merge (`APP1→APP2`) become intra-zone
  (`APPS→APPS`) and are kept, merged by the same rule.

## Zones are additive only

srxsync never deletes a zone on a slave.

- The `zones` category is always loaded as merge. `DiffBuilder._mark_replace`
  never sets `replace="replace"` on `security/zones`, even under `--replace`.
  Other categories keep their `--replace` behaviour. This also stops
  `--replace` from wiping zone interface bindings, a side effect of the
  interface prune that exists today.
- **1:1 zones** — the translated zone (interfaces pruned as today) is merged
  onto the slave. A zone the slave lacks is created.
- **N:1 zones** — only an empty shell, `<security-zone><name>APPS</name></security-zone>`,
  is pushed. The master zones' settings (host-inbound-traffic, screen,
  zone address-book) are not carried over. In merge mode the shell creates the
  zone if missing and is a no-op if present, so the slave's own settings for
  `APPS` are never touched.

Verified 2026-10-16 with `commit check` on lab `vsrx-ci`: zones with no
interfaces, plus policies and source-NAT rule-sets referencing them, commit
cleanly. An empty zone does not block a push; it only carries no traffic.

## Empty-zone warning

Before loading, the push fetches the target's `/configuration/security/zones`
(one extra RPC). For every zone the translated payload references on the slave:

- missing on the slave → `WARNING <host>: creating zone APPS with no interfaces — bind an interface on the slave (set security zones security-zone APPS interfaces <ifl>)`
- present with no `interfaces` → same message, "zone APPS exists with no interfaces".

Warnings never fail a target or change the exit code. They are emitted for
`push`, `push --dry-run` and `check` (check already fetches target zones when
`zones` is included; otherwise it fetches them for this purpose).

## Results and CLI

- `TargetResult` and `DriftLine` gain `warnings: list[str]` (default empty).
- The CLI prints each warning on its own line after the summary table, prefixed
  with `WARNING`, to stderr.
- `ZoneTranslationError` surfaces as a normal per-target failure (`FAIL` row,
  `--on-error` honoured).

## Drift detection

`check` translates the source with the same `ZoneTranslator` before comparing.

- Policies, NAT and address-book compare the translated source against the target.
- 1:1 zones compare content (interfaces pruned, as today).
- N:1 zones are dropped from the content comparison on both sides; drift is
  reported only when the zone is missing on the slave.

## Known limitation

Address entries defined in a master zone's own address-book (`security-zone
APP1 address-book`) are not carried to an N:1 slave zone. A pushed policy that
references one fails the slave's commit, and commit-confirmed rolls it back.
The fix is to put shared objects in a global address-book.

## Testing

Unit tests with XML fixtures (no devices):

- `zone_map` inventory validation: absent, valid, wrong types, empty strings
- identity when `zone_map` is empty — payload unchanged
- 1:1 rename across policies, global policies, NAT, address-book attach, zones
- N:1 policy contexts concatenated in master order
- duplicate policy name in a merged context → `ZoneTranslationError`
- `APP1→APP2` becomes `APPS→APPS`
- de-duplication of global-policy, NAT and attach zone lists
- N:1 zone pushed as an empty shell; master zone settings absent
- `security/zones` never carries `replace` under `--replace`; other roots do
- warning generated for missing zone and for an existing zone with no interfaces
- drift: translated source in sync with a correctly translated target; N:1 zone
  existence-only

Integration (lab, optional): push a mapped inventory to a lab vSRX and confirm
the commit and the warning.

## Out of scope

- Merging or templating N:1 zone settings
- Translating names other than zones (routing instances, interfaces)
- Deleting slave zones that no longer have a master counterpart
