from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from signalsift.models import ConfigError, load_filter_config, load_sources_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="signalsift")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one collection cycle.")
    run_parser.add_argument("--dry-run", action="store_true", help="Do not notify or write state.")
    run_parser.add_argument(
        "--state-path",
        type=Path,
        default=Path("state/notified.json"),
        help="Notification state file path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "run":  # pragma: no cover - argparse enforces the command
        parser.error("unknown command")

    try:
        load_sources_config(Path("config/sources.yaml"))
        load_filter_config(Path("config/filters.yaml"))
    except ConfigError as exc:
        parser.exit(2, f"configuration error: {exc}\n")

    parser.exit(2, "signalsift run: collection pipeline is not implemented yet\n")
