"""Orchestrator — drives push and check across targets with concurrency."""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import Literal

from lxml import etree

from srxsync.categories import CategoryModel
from srxsync.diff import DiffBuilder
from srxsync.drift import DriftDetector, DriftReport
from srxsync.inventory import Inventory, Target
from srxsync.results import DriftLine, DriftSummary, PushSummary, TargetResult
from srxsync.secrets import get_secret
from srxsync.transport import PyEZTransport, Transport
from srxsync.zonemap import ZONES_PATH, ZoneTranslator
from srxsync.zonewarn import zone_warnings


@dataclass(frozen=True)
class RunConfig:
    mode: Literal["replace", "merge"]
    commit_confirmed_minutes: int
    max_parallel: int
    on_error: Literal["continue", "abort"]
    dry_run: bool = False


class Orchestrator:
    def __init__(
        self,
        inventory: Inventory,
        categories: CategoryModel,
        transport_factory: type[Transport] = PyEZTransport,
    ) -> None:
        self._inv = inventory
        self._cats = categories
        self._tx = transport_factory
        # Union of every target's include list — what we need to fetch from master.
        union: list[str] = []
        seen: set[str] = set()
        for target in inventory.targets:
            for name in target.include:
                if name not in seen:
                    union.append(name)
                    seen.add(name)
        self._union_paths, _ = categories.resolve(union)

    async def push(self, cfg: RunConfig) -> PushSummary:
        source_xml = self._fetch_source()
        sem = asyncio.Semaphore(cfg.max_parallel)
        abort_event = asyncio.Event()

        async def run_one(target: Target) -> TargetResult:
            async with sem:
                if abort_event.is_set():
                    return TargetResult(host=target.host, ok=False, error="aborted")
                return await asyncio.to_thread(
                    self._push_target, target, source_xml, cfg, abort_event
                )

        raw = await asyncio.gather(*(run_one(t) for t in self._inv.targets), return_exceptions=True)
        results = [
            r if isinstance(r, TargetResult) else TargetResult(host=t.host, ok=False, error=str(r))
            for t, r in zip(self._inv.targets, raw, strict=True)
        ]
        return PushSummary(results=results)

    async def check(self, max_parallel: int) -> DriftSummary:
        source_xml = self._fetch_source()
        sem = asyncio.Semaphore(max_parallel)

        async def check_one(target: Target) -> DriftLine:
            async with sem:
                return await asyncio.to_thread(self._check_target, target, source_xml)

        raw = await asyncio.gather(
            *(check_one(t) for t in self._inv.targets), return_exceptions=True
        )
        lines = [
            r if isinstance(r, DriftLine) else DriftLine(host=t.host, in_sync=False, error=str(r))
            for t, r in zip(self._inv.targets, raw, strict=True)
        ]
        return DriftSummary(reports=lines)

    # --- internals ---

    def _fetch_source(self) -> etree._Element:
        t = self._tx()
        secret = get_secret(host=self._inv.source.host, auth=self._inv.source.auth)
        try:
            t.connect(
                self._inv.source.host,
                secret.username,
                secret.password,
                ssh_key=secret.ssh_key_path,
            )
            return t.fetch(self._union_paths)
        finally:
            t.close()

    def _push_target(
        self,
        target: Target,
        source_xml: etree._Element,
        cfg: RunConfig,
        abort_event: asyncio.Event,
    ) -> TargetResult:
        start = time.monotonic()
        t = self._tx()
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
        except Exception as e:
            # Deliberately broad: lock, timeout, and secret/Vault failures are
            # not TransportError, but a failure on one target must still roll
            # back that target and report it rather than abort the fleet.
            with contextlib.suppress(Exception):
                t.rollback()
            if cfg.on_error == "abort":
                abort_event.set()
            return TargetResult(
                host=target.host,
                ok=False,
                error=str(e),
                duration_s=time.monotonic() - start,
            )
        finally:
            with contextlib.suppress(Exception):
                t.close()

    def _check_target(self, target: Target, source_xml: etree._Element) -> DriftLine:
        t = self._tx()
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
        except Exception as e:
            # See _push_target: lock, timeout, and secret/Vault failures are
            # not TransportError but must still produce a per-target report.
            return DriftLine(host=target.host, in_sync=False, error=str(e))
        finally:
            with contextlib.suppress(Exception):
                t.close()


def _unknown_key_warnings(
    translator: ZoneTranslator, source_xml: etree._Element, host: str
) -> list[str]:
    """Warn about zone_map keys that name no zone on the master (likely typos)."""
    return [
        f"{host}: zone_map key {key} is not a zone on the master"
        for key in translator.unknown_keys(source_xml)
    ]
