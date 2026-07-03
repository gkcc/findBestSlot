from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from gear_optimizer.game_rules import load_characters, load_game, load_probability_models
from gear_optimizer.position_ev import (
    _ACTION_EV_ROWS_CACHE,
    _AGGREGATED_ACTION_OUTCOME_CACHE,
    _BEST_COMBO_VALUE_CACHE,
    _RESOURCE_MARGINAL_EV_ROWS_CACHE,
    _STATE_TRANSITION_CACHE,
    position_strategy_efficiency_rows,
)
from gear_optimizer.presets import load_current_example
from gear_optimizer.scoring import analyse_current_gear

DEFAULT_GAME = "zzz"
DEFAULT_CHARACTER = "zzz_starlight_billy"
DEFAULT_PROBABILITY_MODEL = "zzz_default"
DEFAULT_CURRENT = "examples/zzz_billy_current.yaml"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _pick_by_id(items: list[Any], item_id: str, label: str) -> Any:
    for item in items:
        if item.id == item_id:
            return item
    available = ", ".join(item.id for item in items) or "-"
    raise ValueError(f"Unknown {label}: {item_id}. Available: {available}")


class ActionEvProfiler:
    def __init__(self) -> None:
        self.started_at = time.perf_counter()
        self.action_total = 0
        self.outcome_total = 0
        self.dp_states = 0
        self.memo_hits = 0
        self.aggregated_outcome_cache_hits = 0
        self.aggregated_outcome_cache_misses = 0
        self.state_transition_cache_hits = 0
        self.state_transition_cache_misses = 0
        self._active_actions: dict[tuple[str, str], tuple[float, str, str, str]] = {}
        self.action_durations: list[dict[str, Any]] = []
        self.action_type_seconds: defaultdict[str, float] = defaultdict(float)
        self.event_counts: Counter[str] = Counter()

    def __call__(self, payload: dict[str, object]) -> None:
        now = time.perf_counter()
        event = str(payload.get("event") or "")
        self.event_counts[event] += 1
        self.action_total = max(self.action_total, int(float(payload.get("spec_total") or 0)))
        self.dp_states = max(self.dp_states, int(float(payload.get("dp_states") or 0)))
        self.memo_hits = max(self.memo_hits, int(float(payload.get("memo_hits") or 0)))
        self.aggregated_outcome_cache_hits = max(
            self.aggregated_outcome_cache_hits,
            int(float(payload.get("aggregated_outcome_cache_hits") or 0)),
        )
        self.aggregated_outcome_cache_misses = max(
            self.aggregated_outcome_cache_misses,
            int(float(payload.get("aggregated_outcome_cache_misses") or 0)),
        )
        self.state_transition_cache_hits = max(
            self.state_transition_cache_hits,
            int(float(payload.get("state_transition_cache_hits") or 0)),
        )
        self.state_transition_cache_misses = max(
            self.state_transition_cache_misses,
            int(float(payload.get("state_transition_cache_misses") or 0)),
        )
        inner_event = str(payload.get("inner_event") or "")
        if inner_event == "outcomes_start" and int(float(payload.get("inner_depth") or 0)) == 0:
            self.outcome_total += int(float(payload.get("inner_total") or 0))

        spec_key = (
            str(payload.get("spec_index") or ""),
            str(payload.get("unit_label") or ""),
        )
        strategy = str(payload.get("action_strategy") or "unknown")
        action_set = str(payload.get("action_set") or "")
        label = str(payload.get("label") or "")
        if event == "unit_start":
            self._active_actions[spec_key] = (now, label, strategy, action_set)
        elif event == "unit_done":
            started = self._active_actions.pop(spec_key, None)
            if started is None:
                return
            started_at, started_label, started_strategy, started_set = started
            duration = now - started_at
            self.action_type_seconds[started_strategy] += duration
            self.action_durations.append(
                {
                    "label": started_label,
                    "strategy": started_strategy,
                    "set": started_set,
                    "unit": spec_key[1],
                    "seconds": round(duration, 4),
                }
            )

    def result(self, rows: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
        total_seconds = time.perf_counter() - self.started_at
        row_strategy_counts = Counter(str(row.get("策略") or "unknown") for row in rows)
        return {
            "generated_at": _utc_now(),
            "horizon": horizon,
            "total_seconds": round(total_seconds, 4),
            "row_count": len(rows),
            "action_count": self.action_total or len(rows),
            "row_strategy_counts": dict(row_strategy_counts),
            "outcome_count": self.outcome_total,
            "dp_state_count": self.dp_states,
            "memo_hits": self.memo_hits,
            "aggregated_outcome_cache_hits": self.aggregated_outcome_cache_hits,
            "aggregated_outcome_cache_misses": self.aggregated_outcome_cache_misses,
            "state_transition_cache_hits": self.state_transition_cache_hits,
            "state_transition_cache_misses": self.state_transition_cache_misses,
            "action_type_seconds": {
                key: round(value, 4)
                for key, value in sorted(self.action_type_seconds.items())
            },
            "top_slow_actions": sorted(
                self.action_durations,
                key=lambda row: float(row["seconds"]),
                reverse=True,
            )[:20],
            "event_counts": dict(self.event_counts),
            "max_cache_sizes": {
                "action_ev_rows": len(_ACTION_EV_ROWS_CACHE),
                "resource_marginal_ev_rows": len(_RESOURCE_MARGINAL_EV_ROWS_CACHE),
                "best_combo_value": len(_BEST_COMBO_VALUE_CACHE),
                "aggregated_action_outcome": len(_AGGREGATED_ACTION_OUTCOME_CACHE),
                "state_transition": len(_STATE_TRANSITION_CACHE),
            },
        }


def _summary_markdown(profile: dict[str, Any]) -> str:
    slow_lines = [
        f"| {row['seconds']} | {row['strategy']} | {row['set']} | {row['unit']} | {row['label']} |"
        for row in profile["top_slow_actions"]
    ]
    if not slow_lines:
        slow_lines = ["| - | - | - | - | - |"]
    type_lines = [
        f"| {strategy} | {seconds} |"
        for strategy, seconds in profile["action_type_seconds"].items()
    ]
    if not type_lines:
        type_lines = ["| - | - |"]
    return "\n".join(
        [
            "# Action EV Profile Summary",
            "",
            f"- generated_at: {profile['generated_at']}",
            f"- engine: {profile.get('engine', 'inventory_recursive')}",
            f"- horizon: {profile['horizon']}",
            f"- total_seconds: {profile['total_seconds']}",
            f"- action_count: {profile['action_count']}",
            f"- outcome_count: {profile['outcome_count']}",
            f"- dp_state_count: {profile['dp_state_count']}",
            f"- memo_hits: {profile['memo_hits']}",
            f"- aggregated_outcome_cache_hits: {profile['aggregated_outcome_cache_hits']}",
            f"- aggregated_outcome_cache_misses: {profile['aggregated_outcome_cache_misses']}",
            f"- state_transition_cache_hits: {profile['state_transition_cache_hits']}",
            f"- state_transition_cache_misses: {profile['state_transition_cache_misses']}",
            "",
            "## Action Type Seconds",
            "",
            "| strategy | seconds |",
            "| --- | ---: |",
            *type_lines,
            "",
            "## Top Slow Actions",
            "",
            "| seconds | strategy | set | unit | label |",
            "| ---: | --- | --- | --- | --- |",
            *slow_lines,
            "",
            "## Cache Sizes",
            "",
            "```json",
            json.dumps(profile["max_cache_sizes"], ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )


def run_profile(
    game_id: str,
    character_id: str,
    probability_model_id: str,
    current_path: str | Path,
    horizon: int,
    use_state_dp: bool = False,
) -> dict[str, Any]:
    game = load_game(game_id)
    character = _pick_by_id(load_characters(game_id), character_id, "character")
    probability_model = _pick_by_id(
        load_probability_models(game_id),
        probability_model_id,
        "probability model",
    )
    pieces = load_current_example(current_path)
    analysis = analyse_current_gear(pieces, game, character)
    profiler = ActionEvProfiler()
    rows = position_strategy_efficiency_rows(
        game,
        character,
        probability_model,
        analysis,
        inventory_pieces=pieces,
        horizon=horizon,
        progress_callback=profiler,
        use_state_dp=use_state_dp,
    )
    profile = profiler.result(rows, horizon)
    profile["engine"] = "state_dp" if use_state_dp else "inventory_recursive"
    profile["game_id"] = game_id
    profile["character_id"] = character_id
    profile["probability_model_id"] = probability_model_id
    profile["current_path"] = str(current_path)
    return profile


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile exact Action EV calculation.")
    parser.add_argument("--game", default=DEFAULT_GAME)
    parser.add_argument("--character", default=DEFAULT_CHARACTER)
    parser.add_argument("--probability-model", default=DEFAULT_PROBABILITY_MODEL)
    parser.add_argument("--current", default=DEFAULT_CURRENT)
    parser.add_argument("--horizon", type=int, choices=[1, 2], default=1)
    parser.add_argument("--state-dp", action="store_true", help="Profile the exact EvState transition DP path.")
    parser.add_argument("--output", default="reports/action_ev_profile.json")
    parser.add_argument("--summary", default="reports/action_ev_profile_summary.md")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    profile = run_profile(
        args.game,
        args.character,
        args.probability_model,
        args.current,
        args.horizon,
        use_state_dp=args.state_dp,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(_summary_markdown(profile), encoding="utf-8")
    print(f"Wrote Action EV profile: {output_path}")
    print(f"Wrote Action EV profile summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
