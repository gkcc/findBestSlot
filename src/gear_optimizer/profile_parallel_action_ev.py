from __future__ import annotations

import argparse
from pathlib import Path
import time

from gear_optimizer.game_rules import load_characters, load_game, load_probability_models
from gear_optimizer.position_ev import (
    EvState,
    _generation_action_specs,
    inventory_rows_from_pieces,
    parallel_expected_state_action_values,
)
from gear_optimizer.presets import load_current_example


DEFAULT_GAME = "zzz"
DEFAULT_CHARACTER = "zzz_starlight_billy"
DEFAULT_PROBABILITY_MODEL = "zzz_default"
DEFAULT_CURRENT = "examples/zzz_billy_current.yaml"


def _pick_by_id(items, item_id: str, label: str):
    for item in items:
        if item.id == item_id:
            return item
    available = ", ".join(item.id for item in items) or "-"
    raise ValueError(f"Unknown {label}: {item_id}. Available: {available}")


def run_parallel_profile(
    game_id: str,
    character_id: str,
    probability_model_id: str,
    current_path: str,
    horizon: int,
    action_limit: int,
    worker_counts: list[int],
) -> str:
    game = load_game(game_id)
    character = _pick_by_id(load_characters(game_id), character_id, "character")
    probability_model = _pick_by_id(
        load_probability_models(game_id),
        probability_model_id,
        "probability model",
    )
    pieces = load_current_example(current_path)
    rows = inventory_rows_from_pieces(pieces, game, character, current_count=len(pieces))
    state = EvState.from_rows(rows, game, character)
    specs = _generation_action_specs(
        game,
        character,
        include_fixed_main=False,
        include_fixed_substats=False,
    )[:action_limit]

    lines = [
        "# Action EV Parallel Profile",
        "",
        "Generated: 2026-07-03",
        "",
        f"- game: {game_id}",
        f"- character: {character_id}",
        f"- probability_model: {probability_model_id}",
        f"- current: {current_path}",
        f"- horizon: {horizon}",
        f"- action_limit: {len(specs)}",
        "",
        "## Results",
        "",
    ]
    for workers in worker_counts:
        started = time.perf_counter()
        results = parallel_expected_state_action_values(
            state,
            game,
            character,
            probability_model,
            specs,
            horizon=horizon,
            workers=workers,
        )
        elapsed = time.perf_counter() - started
        errors = [result.error for result in results if result.error]
        lines.append(f"### workers={workers}")
        lines.append("")
        lines.append(f"- total_seconds: {elapsed:.4f}")
        lines.append(f"- errors: {len(errors)}")
        lines.append("")
        lines.append("| strategy | set | position | seconds | value_len | error |")
        lines.append("| --- | --- | --- | ---: | ---: | --- |")
        for result in results:
            lines.append(
                "| "
                f"{result.spec.strategy} | "
                f"{result.spec.set_label} | "
                f"{result.spec.target_position or 'random'} | "
                f"{result.seconds:.6f} | "
                f"{len(result.value)} | "
                f"{result.error or '-'} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Interpretation",
            "",
            "This profile verifies process-pool execution from a real module entrypoint, which is required on Windows spawn.",
            "Parallel execution remains optional until larger state-DP profiles show a clear win over process startup and serialization overhead.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile process-pool exact state-DP action values.")
    parser.add_argument("--game", default=DEFAULT_GAME)
    parser.add_argument("--character", default=DEFAULT_CHARACTER)
    parser.add_argument("--probability-model", default=DEFAULT_PROBABILITY_MODEL)
    parser.add_argument("--current", default=DEFAULT_CURRENT)
    parser.add_argument("--horizon", type=int, choices=[1, 2], default=1)
    parser.add_argument("--action-limit", type=int, default=4)
    parser.add_argument("--workers", default="1,2", help="Comma-separated worker counts.")
    parser.add_argument("--output", default="reports/action_ev_parallel_profile.md")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    worker_counts = [
        max(1, int(value.strip()))
        for value in str(args.workers).split(",")
        if value.strip()
    ]
    report = run_parallel_profile(
        args.game,
        args.character,
        args.probability_model,
        args.current,
        args.horizon,
        max(1, args.action_limit),
        worker_counts or [1],
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"Wrote Action EV parallel profile: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
