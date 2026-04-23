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
            raise TransportError(f"fetch on {self._host} returned no <configuration> element")
        return cfg

    # ------------------------------------------------------------------
    # Load / commit / rollback
    # ------------------------------------------------------------------

    def load(self, xml: etree._Element, mode: Literal["replace", "merge"]) -> None:
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
            raise TransportError(f"commit confirmed failed on {self._host}: {exc}") from exc

    def confirm(self) -> None:
        if self._cfg is None:
            raise TransportError("not connected")
        try:
            self._cfg.commit()
        except _RUSTEZ_ERRORS as exc:
            raise TransportError(f"confirm commit failed on {self._host}: {exc}") from exc

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
    result: bytes = etree.tostring(root)
    return result.decode()
