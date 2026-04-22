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
from srxsync.transport import PyEZTransport, Transport, TransportError


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
        self._paths, self._prune = categories.resolve(inventory.categories)

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

        results = await asyncio.gather(
            *(run_one(t) for t in self._inv.targets)
        )
        return PushSummary(results=list(results))

    async def check(self, max_parallel: int) -> DriftSummary:
        source_xml = self._fetch_source()
        sem = asyncio.Semaphore(max_parallel)

        async def check_one(target: Target) -> DriftLine:
            async with sem:
                return await asyncio.to_thread(
                    self._check_target, target, source_xml
                )

        lines = await asyncio.gather(
            *(check_one(t) for t in self._inv.targets)
        )
        return DriftSummary(reports=list(lines))

    # --- internals ---

    def _fetch_source(self) -> etree._Element:
        t = self._tx()
        secret = get_secret(host=self._inv.source.host, auth=self._inv.source.auth)
        t.connect(self._inv.source.host, secret.username, secret.password,
                  ssh_key=secret.ssh_key_path)
        try:
            return t.fetch(self._paths)
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
            secret = get_secret(host=target.host, auth=target.auth)
            t.connect(target.host, secret.username, secret.password,
                      ssh_key=secret.ssh_key_path)
            payload = DiffBuilder(
                paths=self._paths, prune=list(self._prune),
                exclude=list(target.exclude),
            ).build(source_xml)

            if cfg.dry_run:
                return TargetResult(
                    host=target.host, ok=True,
                    duration_s=time.monotonic() - start,
                )

            t.load(payload, mode=cfg.mode)
            t.commit_confirmed(cfg.commit_confirmed_minutes)
            t.confirm()
            return TargetResult(
                host=target.host, ok=True,
                duration_s=time.monotonic() - start,
            )
        except TransportError as e:
            with contextlib.suppress(Exception):
                t.rollback()
            if cfg.on_error == "abort":
                abort_event.set()
            return TargetResult(
                host=target.host, ok=False, error=str(e),
                duration_s=time.monotonic() - start,
            )
        finally:
            with contextlib.suppress(Exception):
                t.close()

    def _check_target(self, target: Target, source_xml: etree._Element) -> DriftLine:
        t = self._tx()
        try:
            secret = get_secret(host=target.host, auth=target.auth)
            t.connect(target.host, secret.username, secret.password,
                      ssh_key=secret.ssh_key_path)
            target_xml = t.fetch(self._paths)
            detector = DriftDetector(
                paths=self._paths, prune=list(self._prune),
                exclude=list(target.exclude),
            )
            rep: DriftReport = detector.diff(source_xml, target_xml, host=target.host)
            return DriftLine(
                host=target.host, in_sync=rep.in_sync,
                differing_paths=list(rep.differing_paths),
            )
        except TransportError as e:
            return DriftLine(host=target.host, in_sync=False, error=str(e))
        finally:
            with contextlib.suppress(Exception):
                t.close()
