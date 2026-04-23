"""Rust-native NETCONF transport (stub — real impl in Task 5)."""

from __future__ import annotations

from typing import Literal

import rustez  # noqa: F401 -- presence-check; real use comes in Task 5
from lxml import etree

from srxsync.transport.base import Transport, TransportError


class RustezTransport(Transport):
    def connect(
        self,
        host: str,
        username: str,
        password: str | None = None,
        ssh_key: str | None = None,
        port: int = 830,
    ) -> None:
        raise TransportError("RustezTransport not yet implemented")

    def fetch(self, paths: list[str]) -> etree._Element:
        raise TransportError("RustezTransport not yet implemented")

    def load(self, xml: etree._Element, mode: Literal["replace", "merge"]) -> None:
        raise TransportError("RustezTransport not yet implemented")

    def commit_confirmed(self, minutes: int) -> None:
        raise TransportError("RustezTransport not yet implemented")

    def confirm(self) -> None:
        raise TransportError("RustezTransport not yet implemented")

    def rollback(self) -> None:
        raise TransportError("RustezTransport not yet implemented")

    def close(self) -> None:
        raise TransportError("RustezTransport not yet implemented")
