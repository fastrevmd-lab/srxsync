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
