"""Unit tests for CLI argument parsing."""

from __future__ import annotations

import pytest

from srxsync.cli import _print_drift_summary, _print_push_summary, build_parser
from srxsync.results import DriftLine, DriftSummary, PushSummary, TargetResult


def test_push_requires_mode():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["push", "--inventory", "x.yaml"])


def test_push_replace_ok():
    parser = build_parser()
    args = parser.parse_args(["push", "--inventory", "x.yaml", "--replace"])
    assert args.mode == "replace"
    assert args.commit_confirmed == 5
    assert args.max_parallel == 5
    assert args.on_error == "continue"


def test_push_merge_with_flags():
    parser = build_parser()
    args = parser.parse_args(
        [
            "push",
            "--inventory",
            "x.yaml",
            "--merge",
            "--commit-confirmed",
            "2",
            "--max-parallel",
            "10",
            "--on-error",
            "abort",
            "--dry-run",
        ]
    )
    assert args.mode == "merge"
    assert args.commit_confirmed == 2
    assert args.max_parallel == 10
    assert args.on_error == "abort"
    assert args.dry_run is True


def test_push_replace_and_merge_mutually_exclusive():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "push",
                "--inventory",
                "x.yaml",
                "--replace",
                "--merge",
            ]
        )


def test_check_subcommand():
    parser = build_parser()
    args = parser.parse_args(["check", "--inventory", "x.yaml", "--verbose"])
    assert args.command == "check"
    assert args.verbose is True


def test_push_accepts_transport_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["push", "--inventory", "inv.yaml", "--merge", "--transport", "rustez"]
    )
    assert args.transport == "rustez"


def test_check_accepts_transport_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["check", "--inventory", "inv.yaml", "--transport", "rustez"])
    assert args.transport == "rustez"


def test_push_transport_defaults_to_pyez() -> None:
    parser = build_parser()
    args = parser.parse_args(["push", "--inventory", "inv.yaml", "--merge"])
    assert args.transport == "pyez"


def test_check_transport_defaults_to_pyez() -> None:
    parser = build_parser()
    args = parser.parse_args(["check", "--inventory", "inv.yaml"])
    assert args.transport == "pyez"


def test_transport_rejects_unknown_value() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["push", "--inventory", "inv.yaml", "--merge", "--transport", "grpc"])


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
