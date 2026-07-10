from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from gear_optimizer.action_ev_protocol import ActionEvRowPayload
from gear_optimizer.game_rules import load_characters, load_game, load_probability_models
from gear_optimizer.position_ev import (
    DEFAULT_ACTION_EV_MODE,
    action_ev_cache_sizes,
    clear_action_ev_caches,
    normalize_action_ev_mode,
    position_strategy_efficiency_models,
)
from gear_optimizer.presets import load_current_example
from gear_optimizer.scoring import analyse_current_gear
from gear_optimizer.user_current_gear import load_user_current_gears
from gear_optimizer.user_inventory import load_user_inventory

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
        self.dp_steps = 0
        self.memo_hits = 0
        self.aggregated_outcome_cache_hits = 0
        self.aggregated_outcome_cache_misses = 0
        self.state_transition_cache_hits = 0
        self.state_transition_cache_misses = 0
        self._active_actions: dict[tuple[str, str], tuple[float, str, str, str]] = {}
        self._active_snapshots: dict[tuple[str, str], dict[str, Any]] = {}
        self._active_event_counts: dict[tuple[str, str], Counter[str]] = {}
        self.action_durations: list[dict[str, Any]] = []
        self.action_type_seconds: defaultdict[str, float] = defaultdict(float)
        self.event_counts: Counter[str] = Counter()
        self.inner_event_counts: Counter[str] = Counter()
        self.inner_horizon_counts: Counter[str] = Counter()
        self.inner_depth_counts: Counter[str] = Counter()
        self.inner_action_counts: Counter[str] = Counter()
        self.performance_audit: dict[str, Any] = {}

    def __call__(self, payload: dict[str, object]) -> None:
        now = time.perf_counter()
        event = str(payload.get("event") or "")
        self.event_counts[event] += 1
        performance = payload.get("performance_audit")
        if isinstance(performance, dict):
            self.performance_audit = dict(performance)
        self.action_total = max(self.action_total, int(float(payload.get("spec_total") or 0)))
        self.dp_states = max(self.dp_states, int(float(payload.get("dp_states") or 0)))
        self.dp_steps = max(self.dp_steps, int(float(payload.get("dp_steps") or 0)))
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
        if inner_event:
            self.inner_event_counts[inner_event] += 1
            self.inner_depth_counts[str(payload.get("inner_depth") or 0)] += 1
            self.inner_horizon_counts[str(payload.get("inner_horizon") or "-")] += 1
            action_key = " / ".join(
                str(payload.get(key) or "-")
                for key in ("inner_action_strategy", "inner_action_set", "inner_action_position", "inner_action_main_stat")
            )
            self.inner_action_counts[action_key] += 1

        spec_key = (
            str(payload.get("spec_index") or ""),
            str(payload.get("unit_label") or ""),
        )
        strategy = str(payload.get("action_strategy") or "unknown")
        action_set = str(payload.get("action_set") or "")
        label = str(payload.get("label") or "")
        if event == "unit_start":
            self._active_actions[spec_key] = (now, label, strategy, action_set)
            self._active_snapshots[spec_key] = {
                "dp_states": self.dp_states,
                "dp_steps": self.dp_steps,
                "memo_hits": self.memo_hits,
                "aggregated_outcome_cache_hits": self.aggregated_outcome_cache_hits,
                "aggregated_outcome_cache_misses": self.aggregated_outcome_cache_misses,
                "state_transition_cache_hits": self.state_transition_cache_hits,
                "state_transition_cache_misses": self.state_transition_cache_misses,
            }
            self._active_event_counts[spec_key] = Counter()
        elif event == "unit_progress":
            self._active_event_counts.setdefault(spec_key, Counter())[inner_event or event] += 1
        elif event == "unit_done":
            started = self._active_actions.pop(spec_key, None)
            if started is None:
                return
            started_at, started_label, started_strategy, started_set = started
            before = self._active_snapshots.pop(spec_key, {})
            inner_counts = self._active_event_counts.pop(spec_key, Counter())
            duration = now - started_at
            self.action_type_seconds[started_strategy] += duration
            self.action_durations.append(
                {
                    "label": started_label,
                    "strategy": started_strategy,
                    "set": started_set,
                    "unit": spec_key[1],
                    "seconds": round(duration, 4),
                    "dp_states": self.dp_states - int(before.get("dp_states", self.dp_states)),
                    "dp_steps": self.dp_steps - int(before.get("dp_steps", self.dp_steps)),
                    "memo_hits": self.memo_hits - int(before.get("memo_hits", self.memo_hits)),
                    "aggregated_outcome_cache_hits": self.aggregated_outcome_cache_hits
                    - int(before.get("aggregated_outcome_cache_hits", self.aggregated_outcome_cache_hits)),
                    "aggregated_outcome_cache_misses": self.aggregated_outcome_cache_misses
                    - int(before.get("aggregated_outcome_cache_misses", self.aggregated_outcome_cache_misses)),
                    "state_transition_cache_hits": self.state_transition_cache_hits
                    - int(before.get("state_transition_cache_hits", self.state_transition_cache_hits)),
                    "state_transition_cache_misses": self.state_transition_cache_misses
                    - int(before.get("state_transition_cache_misses", self.state_transition_cache_misses)),
                    "outcomes_start": inner_counts.get("outcomes_start", 0),
                    "outcome_done": inner_counts.get("outcome_done", 0),
                    "state_start": inner_counts.get("state_start", 0),
                    "state_action_start": inner_counts.get("state_action_start", 0),
                    "state_action_done": inner_counts.get("state_action_done", 0),
                    "memo_hit_events": inner_counts.get("memo_hit", 0),
                }
            )

    def result(self, rows: list[ActionEvRowPayload], horizon: int) -> dict[str, Any]:
        total_seconds = time.perf_counter() - self.started_at
        row_strategy_counts = Counter(row.strategy or "unknown" for row in rows)
        action_unit_seconds_total = sum(float(value) for value in self.action_type_seconds.values())
        performance_audit = self.performance_audit if isinstance(self.performance_audit, dict) else {}
        phase_seconds = performance_audit.get("phase_seconds")
        phase_counts = performance_audit.get("phase_counts")
        phase_average_seconds = performance_audit.get("phase_average_seconds")
        top_phase_calls = performance_audit.get("top_20_slowest_phase_calls")
        return {
            "generated_at": _utc_now(),
            "horizon": horizon,
            "total_seconds": round(total_seconds, 4),
            "action_unit_seconds_total": round(action_unit_seconds_total, 4),
            "non_action_unit_seconds": round(max(total_seconds - action_unit_seconds_total, 0.0), 4),
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
            "heatmap_rows": sorted(
                self.action_durations,
                key=lambda row: (
                    str(row["unit"]),
                    -float(row["seconds"]),
                    str(row["strategy"]),
                    str(row["set"]),
                    str(row["label"]),
                ),
            ),
            "event_counts": dict(self.event_counts),
            "inner_event_counts": dict(self.inner_event_counts),
            "inner_horizon_counts": dict(self.inner_horizon_counts),
            "inner_depth_counts": dict(self.inner_depth_counts),
            "top_inner_actions": dict(self.inner_action_counts.most_common(30)),
            "phase_seconds": dict(phase_seconds) if isinstance(phase_seconds, dict) else {},
            "phase_counts": dict(phase_counts) if isinstance(phase_counts, dict) else {},
            "phase_average_seconds": (
                dict(phase_average_seconds) if isinstance(phase_average_seconds, dict) else {}
            ),
            "top_slow_phase_calls": list(top_phase_calls) if isinstance(top_phase_calls, list) else [],
            "performance_audit": performance_audit,
            "max_cache_sizes": action_ev_cache_sizes(),
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
    heatmap_lines = [
        "| "
        f"{row['seconds']} | {row['unit']} | {row['strategy']} | {row['set']} | "
        f"{row.get('dp_states', 0)} | {row.get('dp_steps', 0)} | {row.get('outcome_done', 0)} | "
        f"{row.get('memo_hits', 0)} | {row['label']} |"
        for row in profile.get("heatmap_rows", [])[:40]
    ]
    if not heatmap_lines:
        heatmap_lines = ["| - | - | - | - | - | - | - | - | - |"]
    phase_lines = [
        f"| {phase} | {seconds} | {profile.get('phase_counts', {}).get(phase, '-')} | "
        f"{profile.get('phase_average_seconds', {}).get(phase, '-')} |"
        for phase, seconds in profile.get("phase_seconds", {}).items()
    ][:30]
    if not phase_lines:
        phase_lines = ["| - | - | - | - |"]
    phase_call_lines = [
        "| "
        f"{row.get('seconds', '-')} | {row.get('phase', '-')} | "
        f"{row.get('strategy', row.get('target_set', row.get('reason', '-')))} | "
        f"{row.get('horizon', row.get('remaining_horizon', '-'))} | "
        f"{row.get('inventory_count', row.get('outcome_count', row.get('spec_count', '-')))} |"
        for row in profile.get("top_slow_phase_calls", [])[:30]
        if isinstance(row, dict)
    ]
    if not phase_call_lines:
        phase_call_lines = ["| - | - | - | - | - |"]
    return "\n".join(
        [
            "# Action EV Profile Summary",
            "",
            f"- generated_at: {profile['generated_at']}",
            f"- engine: {profile.get('engine', 'inventory_recursive')}",
            f"- action_mode: {profile.get('action_mode', '-')}",
            f"- horizon: {profile['horizon']}",
            f"- total_seconds: {profile['total_seconds']}",
            f"- action_unit_seconds_total: {profile.get('action_unit_seconds_total', '-')}",
            f"- non_action_unit_seconds: {profile.get('non_action_unit_seconds', '-')}",
            f"- action_count: {profile['action_count']}",
            f"- current_count: {profile.get('current_count', '-')}",
            f"- inventory_count: {profile.get('inventory_count', '-')}",
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
            "## Heatmap Preview",
            "",
            "| seconds | unit | strategy | set | dp_states | dp_steps | outcome_done | memo_hits | label |",
            "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
            *heatmap_lines,
            "",
            "## Phase Seconds",
            "",
            "| phase | seconds | count | avg_seconds |",
            "| --- | ---: | ---: | ---: |",
            *phase_lines,
            "",
            "## Top Slow Phase Calls",
            "",
            "| seconds | phase | detail | horizon | size |",
            "| ---: | --- | --- | ---: | ---: |",
            *phase_call_lines,
            "",
            "## Inner Event Counts",
            "",
            "```json",
            json.dumps(profile.get("inner_event_counts", {}), ensure_ascii=False, indent=2),
            "```",
            "",
            "## Top Inner Actions",
            "",
            "```json",
            json.dumps(profile.get("top_inner_actions", {}), ensure_ascii=False, indent=2),
            "```",
            "",
            "## Cache Sizes",
            "",
            "```json",
            json.dumps(profile["max_cache_sizes"], ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )


def _latest_user_current_pieces(game_id: str, agent_id: str) -> list:
    items = load_user_current_gears(game_id, agent_id)
    return list(items[-1]["pieces"]) if items else []


def _write_heatmap_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "seconds",
        "unit",
        "strategy",
        "set",
        "label",
        "dp_states",
        "dp_steps",
        "memo_hits",
        "aggregated_outcome_cache_hits",
        "aggregated_outcome_cache_misses",
        "state_transition_cache_hits",
        "state_transition_cache_misses",
        "outcomes_start",
        "outcome_done",
        "state_start",
        "state_action_start",
        "state_action_done",
        "memo_hit_events",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_phase_csv(path: Path, profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "kind",
        "phase",
        "seconds",
        "count",
        "average_seconds",
        "strategy",
        "target_set",
        "horizon",
        "depth",
        "inventory_count",
        "outcome_count",
        "spec_count",
        "reason",
        "cache",
    ]
    rows: list[dict[str, Any]] = []
    phase_counts = profile.get("phase_counts", {})
    phase_average_seconds = profile.get("phase_average_seconds", {})
    if not isinstance(phase_counts, dict):
        phase_counts = {}
    if not isinstance(phase_average_seconds, dict):
        phase_average_seconds = {}
    for phase, seconds in profile.get("phase_seconds", {}).items():
        rows.append(
            {
                "kind": "aggregate",
                "phase": phase,
                "seconds": seconds,
                "count": phase_counts.get(phase, ""),
                "average_seconds": phase_average_seconds.get(phase, ""),
            }
        )
    for row in profile.get("top_slow_phase_calls", []):
        if not isinstance(row, dict):
            continue
        rows.append({"kind": "slow_call", **row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_profile(
    game_id: str,
    character_id: str,
    probability_model_id: str,
    current_path: str | Path,
    horizon: int,
    use_state_dp: bool = False,
    action_mode: str = DEFAULT_ACTION_EV_MODE,
    user_data_agent: str = "",
    clear_caches: bool = True,
) -> dict[str, Any]:
    if clear_caches:
        clear_action_ev_caches()
    action_mode = normalize_action_ev_mode(action_mode)
    game = load_game(game_id)
    character = _pick_by_id(load_characters(game_id), character_id, "character")
    probability_model = _pick_by_id(
        load_probability_models(game_id),
        probability_model_id,
        "probability model",
    )
    if user_data_agent:
        current_pieces = _latest_user_current_pieces(game_id, user_data_agent)
        inventory_only_pieces = load_user_inventory(game_id, user_data_agent)
        source = f"user_data:{user_data_agent}"
    else:
        current_pieces = load_current_example(current_path)
        inventory_only_pieces = []
        source = str(current_path)
    analysis = analyse_current_gear(current_pieces, game, character)
    inventory_pieces = [*current_pieces, *inventory_only_pieces]
    profiler = ActionEvProfiler()
    rows = position_strategy_efficiency_models(
        game,
        character,
        probability_model,
        analysis,
        inventory_pieces=inventory_pieces,
        horizon=horizon,
        progress_callback=profiler,
        use_state_dp=use_state_dp,
        action_mode=action_mode,
    )
    profile = profiler.result(rows, horizon)
    profile["engine"] = "state_dp" if use_state_dp else "inventory_recursive"
    profile["action_mode"] = action_mode
    profile["game_id"] = game_id
    profile["character_id"] = character_id
    profile["probability_model_id"] = probability_model_id
    profile["source"] = source
    profile["current_path"] = str(current_path) if not user_data_agent else ""
    profile["user_data_agent"] = user_data_agent
    profile["current_count"] = len(current_pieces)
    profile["inventory_count"] = len(inventory_only_pieces)
    return profile


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile exact Action EV calculation.")
    parser.add_argument("--game", default=DEFAULT_GAME)
    parser.add_argument("--character", default=DEFAULT_CHARACTER)
    parser.add_argument("--probability-model", default=DEFAULT_PROBABILITY_MODEL)
    parser.add_argument("--current", default=DEFAULT_CURRENT)
    parser.add_argument("--horizon", type=int, choices=[1, 2], default=1)
    parser.add_argument("--state-dp", action="store_true", help="Profile the exact EvState transition DP path.")
    parser.add_argument("--action-mode", default=DEFAULT_ACTION_EV_MODE, choices=["fast", "exact"])
    parser.add_argument("--user-data-agent", default="", help="Read current gear and inventory for this local agent id.")
    parser.add_argument("--keep-caches", action="store_true", help="Do not clear Action EV caches before profiling.")
    parser.add_argument("--output", default="reports/action_ev_profile.json")
    parser.add_argument("--summary", default="reports/action_ev_profile_summary.md")
    parser.add_argument("--heatmap-csv", default="reports/action_ev_profile_heatmap.csv")
    parser.add_argument("--phase-csv", default="reports/action_ev_profile_phase_heatmap.csv")
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
        action_mode=args.action_mode,
        user_data_agent=args.user_data_agent,
        clear_caches=not args.keep_caches,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(_summary_markdown(profile), encoding="utf-8")
    heatmap_path = Path(args.heatmap_csv)
    _write_heatmap_csv(heatmap_path, list(profile.get("heatmap_rows", [])))
    phase_path = Path(args.phase_csv)
    _write_phase_csv(phase_path, profile)
    print(f"Wrote Action EV profile: {output_path}")
    print(f"Wrote Action EV profile summary: {summary_path}")
    print(f"Wrote Action EV profile heatmap: {heatmap_path}")
    print(f"Wrote Action EV phase heatmap: {phase_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
