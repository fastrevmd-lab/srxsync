# srxsync

Sync Juniper SRX configuration from a master to a fleet of targets.

See `docs/superpowers/specs/2026-04-22-srxsync-design.md` for the design.

## Install

    python -m venv .venv
    source .venv/bin/activate
    pip install -e .[dev]

## Usage

    srxsync push  --inventory inv.yaml (--replace|--merge) [--commit-confirmed N] [--max-parallel N] [--on-error continue|abort] [--dry-run]
    srxsync check --inventory inv.yaml [--verbose]
