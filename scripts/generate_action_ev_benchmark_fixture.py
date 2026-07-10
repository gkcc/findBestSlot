from __future__ import annotations

import argparse
import json
from pathlib import Path

from gear_optimizer.action_ev_protocol import protocol_json_data
from gear_optimizer.desktop_service import DesktopService
from gear_optimizer.user_target_templates import load_user_target_templates


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_USER_DATA = PROJECT_ROOT / "user_data"
DEFAULT_OUTPUT = PROJECT_ROOT / "tests" / "fixtures" / "zzz_ye_shunguang_h2_benchmark.json"


def build_fixture(user_data_root: Path, *, agent_id: str) -> dict[str, object]:
    service = DesktopService(user_data_root)
    request = service._action_job_request(
        "zzz",
        agent_id,
        {
            "horizon": 2,
            "engine": "inventory_recursive",
            "action_mode": "fast",
        },
    ).model_copy(
        update={
            "run_id": "benchmark-zzz-ye-shunguang-h2",
            "input_audit": "冻结的绝区零叶瞬光真实盘面 H=2 性能基准。",
            "input_audit_lines": ["冻结的绝区零叶瞬光真实盘面 H=2 性能基准。"],
        }
    )
    target = next(
        template
        for template in load_user_target_templates("zzz", user_data_root)
        if template.id == request.character_id
    )
    target = target.model_copy(
        update={
            "name": "叶瞬光 H=2 性能基准",
            "notes": "冻结盘面专用目标模板，不作为产品内置默认模板。",
        }
    )
    return {
        "schema_version": 1,
        "description": (
            "Frozen, item-id-free ZZZ Ye Shunguang board used by the exact H=2 "
            "cold/warm performance gate."
        ),
        "source_agent_id": agent_id,
        "target_template": target.model_dump(mode="json", exclude_none=True),
        "request": protocol_json_data(request),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Freeze the current ZZZ board as the committed H=2 benchmark fixture."
    )
    parser.add_argument("--user-data", type=Path, default=DEFAULT_USER_DATA)
    parser.add_argument("--agent-id", default="zzz_ye_shunguang")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    fixture = build_fixture(args.user_data, agent_id=args.agent_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
