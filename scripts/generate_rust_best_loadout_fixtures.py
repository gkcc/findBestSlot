from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from gear_optimizer.models import (
    CharacterPreset,
    GameRules,
    PositionRule,
    SetPlan,
    SetRequirement,
)
from gear_optimizer import position_ev


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "tests" / "fixtures" / "rust_best_loadout_golden.json"


def _value(score: float, *, preferred: bool = True) -> list[float]:
    return [float(preferred), score, score, score]


def _piece(
    item_id: str,
    position: int,
    set_name: str,
    score: float,
    *,
    locked_current: bool = False,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "position": str(position),
        "set_name": set_name,
        "value": _value(score),
        "locked_current": locked_current,
        "eligible": True,
    }


def fixture_cases() -> list[dict[str, Any]]:
    return [
        {
            "name": "four_plus_two_quality_tradeoff",
            "request": {
                "positions": [str(index) for index in range(1, 7)],
                "pieces": [
                    *[_piece(f"a{index}", index, "A", 10) for index in range(1, 7)],
                    _piece("b5", 5, "B", 4),
                    _piece("b6", 6, "B", 4),
                ],
                "set_plan": {
                    "requirements": [
                        {"set_names": ["A"], "pieces": 4},
                        {"set_names": ["B"], "pieces": 2},
                    ]
                },
                "require_set_plan": False,
            },
        },
        {
            "name": "two_plus_two_plus_two",
            "request": {
                "positions": [str(index) for index in range(1, 7)],
                "pieces": [
                    _piece("a1", 1, "A", 5),
                    _piece("a2", 2, "A", 5),
                    _piece("b3", 3, "B", 5),
                    _piece("b4", 4, "B", 5),
                    _piece("c5", 5, "C", 5),
                    _piece("c6", 6, "C", 5),
                    _piece("a6-high", 6, "A", 20),
                ],
                "set_plan": {
                    "requirements": [
                        {"set_names": ["A"], "pieces": 2},
                        {"set_names": ["B"], "pieces": 2},
                        {"set_names": ["C"], "pieces": 2},
                    ]
                },
                "require_set_plan": False,
            },
        },
        {
            "name": "locked_current_position",
            "request": {
                "positions": ["1", "2"],
                "pieces": [
                    _piece("locked-low", 1, "A", 1, locked_current=True),
                    _piece("inventory-high", 1, "B", 20),
                    _piece("slot-two", 2, "A", 2),
                ],
                "set_plan": None,
                "require_set_plan": False,
            },
        },
        {
            "name": "equal_value_preserves_python_input_order",
            "request": {
                "positions": ["1", "2"],
                "pieces": [
                    _piece("a-first", 1, "A", 5),
                    _piece("b-second", 1, "B", 5),
                    _piece("c-slot-two", 2, "C", 5),
                ],
                "set_plan": {
                    "requirements": [
                        {"set_names": ["A", "B"], "pieces": 1}
                    ]
                },
                "require_set_plan": False,
            },
        },
        {
            "name": "impossible_plan_uses_quality_fallback",
            "request": {
                "positions": ["1", "2"],
                "pieces": [
                    _piece("a1", 1, "A", 3),
                    _piece("a2", 2, "A", 4),
                ],
                "set_plan": {
                    "requirements": [{"set_names": ["B"], "pieces": 2}]
                },
                "require_set_plan": False,
            },
        },
        {
            "name": "impossible_strict_plan_returns_none",
            "request": {
                "positions": ["1", "2"],
                "pieces": [
                    _piece("a1", 1, "A", 3),
                    _piece("a2", 2, "A", 4),
                ],
                "set_plan": {
                    "requirements": [{"set_names": ["B"], "pieces": 2}]
                },
                "require_set_plan": True,
            },
        },
    ]


def _reference_result(request: dict[str, Any]) -> dict[str, Any] | None:
    set_names = sorted({piece["set_name"] for piece in request["pieces"]})
    positions = [
        PositionRule(id=position, name=position, main_stats=["main"])
        for position in request["positions"]
    ]
    game = GameRules(
        id="rust_golden",
        name="Rust golden",
        gear_name="gear",
        sets=set_names,
        positions=positions,
        sub_stats=[],
    )
    raw_plan = request.get("set_plan")
    plan = None
    if raw_plan:
        plan = SetPlan(
            id="golden-plan",
            name="Golden plan",
            requirements=[
                SetRequirement(
                    set_names=requirement["set_names"],
                    pieces=requirement["pieces"],
                )
                for requirement in raw_plan["requirements"]
            ],
        )
    character = CharacterPreset(
        id="rust_golden",
        game=game.id,
        name="Rust golden",
        target_set=set_names[0],
        set_plans=[plan] if plan else [],
        default_set_plan=plan.id if plan else None,
    )
    rows = []
    for piece in request["pieces"]:
        if not piece.get("eligible", True):
            continue
        value = piece["value"]
        rows.append(
            {
                "position": piece["position"],
                "set_name": piece["set_name"],
                "main_preferred": bool(value[0]),
                "quality_vector": (float(value[1]),),
                "effective_rolls": float(value[2]),
                "quality_score": float(value[3]),
                "locked": bool(piece.get("locked_current", False)),
                "source": "current" if piece.get("locked_current") else "inventory",
                "_inventory_id": piece["item_id"],
            }
        )
    combo = position_ev._best_loadout_dp(
        rows,
        game,
        character,
        return_combo=True,
        require_set_plan=bool(request.get("require_set_plan", False)),
    )
    if not combo:
        return None
    counts: dict[str, int] = {}
    for row in combo:
        counts[row["set_name"]] = counts.get(row["set_name"], 0) + 1
    return {
        "selected_item_ids": [row["_inventory_id"] for row in combo],
        "value": list(position_ev._combo_value(combo, character)),
        "set_plan_satisfied": position_ev._set_plan_satisfied(combo, character),
        "set_counts": counts,
    }


def build_fixture() -> dict[str, Any]:
    cases = fixture_cases()
    return {
        "schema_version": 1,
        "description": "Python position_ev reference results for the Rust data-oriented best-loadout core.",
        "cases": [
            {**case, "expected": _reference_result(case["request"])}
            for case in cases
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    expected = json.dumps(build_fixture(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != expected:
            print(f"Rust golden fixture is stale: {args.output}", file=sys.stderr)
            return 1
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
