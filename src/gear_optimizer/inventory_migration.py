from __future__ import annotations

import argparse
from pathlib import Path

from gear_optimizer.agents import (
    apply_multi_agent_migration,
    dry_run_multi_agent_migration,
    migration_report_json,
    migration_report_markdown,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or apply migration to item_id-based global inventory and agent loadouts."
    )
    parser.add_argument("--game", required=True, help="Game id, for example zzz or hsr.")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Optional user-data root. Defaults to the application's current user-data directory.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write global inventory/loadout files after backup. Without this flag the command is read-only.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    parser.add_argument("--output", type=Path, default=None, help="Optional report output path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = (
        apply_multi_agent_migration(args.game, root=args.root)
        if args.apply
        else dry_run_multi_agent_migration(args.game, root=args.root)
    )
    rendered = migration_report_json(report) if args.json else migration_report_markdown(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 2 if report.blocking_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
