import pytest

from gear_optimizer.action_ev_protocol import (
    ACTION_EV_PROTOCOL_SCHEMA_VERSION,
    ActionEvProgressEvent,
    ActionEvRowPayload,
    ActionEvWorkerRequest,
    ActionEvWorkerResult,
    UnsupportedActionEvProtocolVersionError,
    parse_action_ev_progress_event,
    parse_action_ev_worker_error,
    parse_action_ev_worker_request,
    parse_action_ev_worker_result,
    parse_action_ev_worker_summary,
    protocol_json_data,
)
from gear_optimizer.models import GearPiece


def _piece_payload() -> dict:
    return {
        "position": 1,
        "set_name": "A",
        "main_stat": "main",
        "level": 0,
        "substats": [{"stat": "good", "rolls": 0}],
        "locked": False,
        "initial_substat_count": 3,
        "revealed_next_substat": None,
    }


def _request_payload() -> dict:
    return {
        "schema_version": ACTION_EV_PROTOCOL_SCHEMA_VERSION,
        "run_id": "run-1",
        "game_id": "game",
        "character_id": "character",
        "probability_model_id": "probability",
        "current_pieces": [_piece_payload()],
        "inventory_pieces": [],
        "horizon": 2,
        "engine": "state_dp",
        "action_mode": "exact",
        "input_audit": "line one\nline two",
        "input_audit_lines": ["line one", "line two"],
    }


def test_worker_request_round_trip_uses_versioned_typed_fields():
    request = ActionEvWorkerRequest.model_validate(_request_payload())
    data = protocol_json_data(request)
    parsed = parse_action_ev_worker_request(data)

    assert data["schema_version"] == ACTION_EV_PROTOCOL_SCHEMA_VERSION
    assert parsed == request
    assert parsed.current_pieces[0].substats[0].stat == "good"


def test_legacy_request_without_schema_version_remains_readable():
    payload = _request_payload()
    payload.pop("schema_version")
    payload.pop("input_audit_lines")

    parsed = parse_action_ev_worker_request(payload)

    assert parsed.schema_version == ACTION_EV_PROTOCOL_SCHEMA_VERSION
    assert parsed.input_audit_lines == ["line one", "line two"]


@pytest.mark.parametrize(
    "parser",
    [
        parse_action_ev_worker_request,
        parse_action_ev_worker_result,
        parse_action_ev_progress_event,
        parse_action_ev_worker_error,
        parse_action_ev_worker_summary,
    ],
)
def test_protocol_parsers_reject_future_schema_versions(parser):
    with pytest.raises(UnsupportedActionEvProtocolVersionError, match="当前支持版本为 1"):
        parser({"schema_version": 2, "run_id": "future"})


def test_action_row_wire_keys_are_stable_english_and_round_trip_display_fields():
    piece = GearPiece.model_validate(_piece_payload())
    display_row = {
        "动作类型": "调律母盘",
        "策略": "随机位置",
        "目标套装": "A",
        "位置": "随机",
        "主属性": "随机",
        "固定副属性": "不固定",
        "horizon": 2,
        "条件分支": [
            {
                "条件": "命中 1 号位",
                "条件概率": 0.5,
                "代表新盘": "A / 1",
                "第二步 action": "固定位置",
                "第二步原因": "补齐套装",
                "代表最终搭配": "A2",
                "套装约束": "已满足",
            }
        ],
        "_representative_loadout_rows": [{"position": 1, "_piece": piece}],
        "_sort_vector": (1.0, 2.0),
    }

    row = ActionEvRowPayload.from_display_row(display_row)
    wire = protocol_json_data(row)
    restored = ActionEvRowPayload.model_validate(wire).to_display_row()

    assert "策略" not in wire
    assert "条件" not in wire["condition_branches"][0]
    assert wire["strategy"] == "随机位置"
    assert restored["策略"] == "随机位置"
    assert restored["条件分支"][0]["第二步原因"] == "补齐套装"
    assert isinstance(restored["_representative_loadout_rows"][0]["_piece"], GearPiece)
    assert restored["_sort_vector"] == (1.0, 2.0)


def test_action_row_adapter_rejects_unmapped_internal_fields():
    with pytest.raises(ValueError, match="Unsupported Action EV row fields"):
        ActionEvRowPayload.from_display_row({"策略": "随机位置", "悄悄新增字段": 1})


def test_legacy_result_with_chinese_rows_parses_and_restores():
    result = parse_action_ev_worker_result(
        {
            "run_id": "legacy-result",
            "engine": "inventory_recursive",
            "action_mode": "fast",
            "execution_mode": "worker_process",
            "performance_audit": {},
            "rows": [{"策略": "固定位置", "有效/母盘": 1.25}],
        }
    )

    assert isinstance(result, ActionEvWorkerResult)
    assert result.schema_version == ACTION_EV_PROTOCOL_SCHEMA_VERSION
    assert result.rows[0].strategy == "固定位置"
    assert result.to_display_rows()[0]["有效/母盘"] == 1.25


def test_progress_parser_supports_new_envelope_and_legacy_flat_event():
    current = ActionEvProgressEvent(
        run_id="run-1",
        event="unit_progress",
        elapsed_seconds=1.5,
        wall_time="2026-07-10T00:00:00Z",
        payload={"label": "current", "completed": 2},
    )
    parsed_current = parse_action_ev_progress_event(protocol_json_data(current))
    parsed_legacy = parse_action_ev_progress_event(
        {
            "run_id": "run-1",
            "event": "unit_progress",
            "elapsed_seconds": 1.5,
            "wall_time": "2026-07-10T00:00:00Z",
            "label": "legacy",
            "completed": 1,
        }
    )

    assert parsed_current.to_flat_dict()["label"] == "current"
    assert parsed_legacy.to_flat_dict()["label"] == "legacy"
    assert parsed_legacy.to_flat_dict()["completed"] == 1


def test_legacy_summary_path_keys_are_normalized():
    summary = parse_action_ev_worker_summary(
        {
            "status": "ok",
            "input": "input.json",
            "output": "result.json",
            "progress": "progress.jsonl",
            "error": "error.json",
        },
        fallback_run_id="legacy-run",
    )

    assert summary.run_id == "legacy-run"
    assert summary.input_path == "input.json"
    assert summary.output_path == "result.json"
