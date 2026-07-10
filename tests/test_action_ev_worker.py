import json
from pathlib import Path

from gear_optimizer import position_ev
from gear_optimizer.action_ev_protocol import (
    ACTION_EV_PROTOCOL_SCHEMA_VERSION,
    ActionEvRowPayload,
    parse_action_ev_progress_event,
    parse_action_ev_worker_result,
)
from gear_optimizer.action_ev_worker import (
    ACTION_EV_ENGINE_ENV,
    ACTION_EV_MODE_ENV,
    ProgressJsonlWriter,
    build_action_ev_rows_from_payload,
    main as worker_main,
)
from gear_optimizer.presets import load_current_example
from gear_optimizer.game_rules import load_characters
from gear_optimizer.user_target_templates import save_user_target_template
from gear_optimizer.user_target_templates import target_template_store_path


def _write_worker_input(
    path: Path,
    game_id: str = "zzz",
    engine: str | None = None,
    action_mode: str | None = None,
) -> None:
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    payload = {
        "schema_version": ACTION_EV_PROTOCOL_SCHEMA_VERSION,
        "run_id": "test-run",
        "game_id": game_id,
        "character_id": "zzz_starlight_billy",
        "probability_model_id": "zzz_default",
        "current_pieces": [piece.model_dump(mode="json") for piece in pieces],
        "inventory_pieces": [],
        "horizon": 1,
        "input_audit": "输入指纹：worker-test\n库存：0 件",
        "input_audit_lines": ["输入指纹：worker-test", "库存：0 件"],
    }
    if engine is not None:
        payload["engine"] = engine
    if action_mode is not None:
        payload["action_mode"] = action_mode
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _strategy_values(rows: list[dict]) -> list[str]:
    return [str(row["策略"]) for row in rows]


def test_action_ev_worker_engine_defaults_and_env_override(monkeypatch, tmp_path):
    input_path = tmp_path / "input.json"
    _write_worker_input(input_path, engine="state_dp")
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    captured = []

    def fake_position_strategy_efficiency_rows(*_args, **kwargs):
        captured.append(kwargs.get("use_state_dp"))
        return [ActionEvRowPayload(strategy="fake")]

    monkeypatch.setattr(
        "gear_optimizer.action_ev_worker.position_strategy_efficiency_models",
        fake_position_strategy_efficiency_rows,
    )
    monkeypatch.delenv(ACTION_EV_ENGINE_ENV, raising=False)

    assert _strategy_values(build_action_ev_rows_from_payload(payload)) == ["fake"]
    assert captured[-1] is True

    monkeypatch.setenv(ACTION_EV_ENGINE_ENV, "inventory_recursive")
    assert _strategy_values(build_action_ev_rows_from_payload(payload)) == ["fake"]
    assert captured[-1] is False


def test_action_ev_worker_action_mode_defaults_and_env_override(monkeypatch, tmp_path):
    input_path = tmp_path / "input.json"
    _write_worker_input(input_path, action_mode="exact")
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    captured = []

    def fake_position_strategy_efficiency_rows(*_args, **kwargs):
        captured.append(kwargs.get("action_mode"))
        return [ActionEvRowPayload(strategy="fake")]

    monkeypatch.setattr(
        "gear_optimizer.action_ev_worker.position_strategy_efficiency_models",
        fake_position_strategy_efficiency_rows,
    )
    monkeypatch.delenv(ACTION_EV_MODE_ENV, raising=False)

    assert _strategy_values(build_action_ev_rows_from_payload(payload)) == ["fake"]
    assert captured[-1] == "exact"

    monkeypatch.setenv(ACTION_EV_MODE_ENV, "fast")
    assert _strategy_values(build_action_ev_rows_from_payload(payload)) == ["fake"]
    assert captured[-1] == "fast"


def test_action_ev_worker_loads_user_target_templates(monkeypatch, tmp_path):
    user_data = tmp_path / "user_data"
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(user_data))
    base = next(character for character in load_characters("zzz") if character.id == "zzz_starlight_billy")
    saved = save_user_target_template("zzz", base, "测试目标模板", user_data)
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    payload = {
        "run_id": "test-user-template",
        "game_id": "zzz",
        "character_id": saved.id,
        "probability_model_id": "zzz_default",
        "current_pieces": [piece.model_dump(mode="json") for piece in pieces],
        "inventory_pieces": [],
        "horizon": 1,
    }
    captured = []

    def fake_position_strategy_efficiency_rows(_game, character, *_args, **_kwargs):
        captured.append(character.id)
        return [ActionEvRowPayload(strategy="fake")]

    monkeypatch.setattr(
        "gear_optimizer.action_ev_worker.position_strategy_efficiency_models",
        fake_position_strategy_efficiency_rows,
    )

    assert _strategy_values(build_action_ev_rows_from_payload(payload)) == ["fake"]
    assert captured == [saved.id]


def test_action_ev_worker_builtin_character_ignores_broken_user_target_templates(monkeypatch, tmp_path):
    user_data = tmp_path / "user_data"
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(user_data))
    path = target_template_store_path("zzz", user_data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("templates: [", encoding="utf-8")
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    payload = {
        "run_id": "test-builtin-template",
        "game_id": "zzz",
        "character_id": "zzz_starlight_billy",
        "probability_model_id": "zzz_default",
        "current_pieces": [piece.model_dump(mode="json") for piece in pieces],
        "inventory_pieces": [],
        "horizon": 1,
    }

    monkeypatch.setattr(
        "gear_optimizer.action_ev_worker.position_strategy_efficiency_models",
        lambda *_args, **_kwargs: [ActionEvRowPayload(strategy="fake")],
    )

    assert _strategy_values(build_action_ev_rows_from_payload(payload)) == ["fake"]


def test_action_ev_worker_strips_unsupported_revealed_next_substat(monkeypatch):
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    dirty_piece = pieces[0].model_dump(mode="json")
    dirty_piece["initial_substat_count"] = 3
    dirty_piece["level"] = 0
    dirty_piece["substats"] = [
        {"stat": "暴击率", "rolls": 0},
        {"stat": "暴击伤害", "rolls": 0},
        {"stat": "攻击力百分比", "rolls": 0},
    ]
    dirty_piece["revealed_next_substat"] = "暴击率"
    payload = {
        "run_id": "test-dirty-revealed-next",
        "game_id": "zzz",
        "character_id": "zzz_starlight_billy",
        "probability_model_id": "zzz_default",
        "current_pieces": [dirty_piece, *[piece.model_dump(mode="json") for piece in pieces[1:]]],
        "inventory_pieces": [],
        "horizon": 1,
    }
    captured = []

    def fake_position_strategy_efficiency_rows(_game, _character, _model, analysis, **_kwargs):
        captured.append(analysis.scores[0].position)
        return [ActionEvRowPayload(strategy="fake")]

    monkeypatch.setattr(
        "gear_optimizer.action_ev_worker.position_strategy_efficiency_models",
        fake_position_strategy_efficiency_rows,
    )

    assert _strategy_values(build_action_ev_rows_from_payload(payload)) == ["fake"]
    assert captured


def test_action_ev_worker_strips_invalid_hsr_revealed_next_substat(monkeypatch):
    dirty_current = {
        "position": "body",
        "set_name": "识海迷坠的学者",
        "main_stat": "暴击率",
        "initial_substat_count": 3,
        "level": 0,
        "substats": [
            {"stat": "暴击伤害", "rolls": 0},
            {"stat": "攻击力百分比", "rolls": 0},
            {"stat": "生命值百分比", "rolls": 0},
        ],
        "revealed_next_substat": "暴击伤害",
    }
    dirty_inventory = {
        **dirty_current,
        "revealed_next_substat": "暴击率",
    }
    payload = {
        "run_id": "test-invalid-hsr-revealed-next",
        "game_id": "hsr",
        "character_id": "hsr_placeholder",
        "probability_model_id": "hsr_default",
        "current_pieces": [dirty_current],
        "inventory_pieces": [dirty_inventory],
        "horizon": 1,
    }
    captured = []

    def fake_position_strategy_efficiency_rows(_game, _character, _model, _analysis, **kwargs):
        captured.append([piece.revealed_next_substat for piece in kwargs["inventory_pieces"]])
        return [ActionEvRowPayload(strategy="fake")]

    monkeypatch.setattr(
        "gear_optimizer.action_ev_worker.position_strategy_efficiency_models",
        fake_position_strategy_efficiency_rows,
    )

    assert _strategy_values(build_action_ev_rows_from_payload(payload)) == ["fake"]
    assert captured == [[None, None]]


def test_action_ev_worker_writes_result_progress_and_summary(tmp_path):
    position_ev._ACTION_EV_ROWS_CACHE.clear()
    position_ev._AGGREGATED_ACTION_OUTCOME_CACHE.clear()
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "result.json"
    progress_path = tmp_path / "progress.jsonl"
    error_path = tmp_path / "error.json"
    summary_path = tmp_path / "summary.json"
    _write_worker_input(input_path)

    assert (
        worker_main(
            [
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--progress",
                str(progress_path),
                "--error",
                str(error_path),
                "--summary",
                str(summary_path),
                "--progress-interval-ms",
                "0",
            ]
        )
        == 0
    )

    result = json.loads(output_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    raw_progress_events = [
        json.loads(line)
        for line in progress_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    progress_events = [
        parse_action_ev_progress_event(event).to_flat_dict()
        for event in raw_progress_events
    ]

    assert result["schema_version"] == ACTION_EV_PROTOCOL_SCHEMA_VERSION
    assert summary["schema_version"] == ACTION_EV_PROTOCOL_SCHEMA_VERSION
    assert all(event["schema_version"] == ACTION_EV_PROTOCOL_SCHEMA_VERSION for event in raw_progress_events)
    assert all("payload" in event for event in raw_progress_events)
    assert result["run_id"] == "test-run"
    assert result["engine"] == "inventory_recursive"
    assert result["action_mode"] == "fast"
    assert result["execution_mode"] == "worker_process"
    assert result["input_audit"] == "输入指纹：worker-test\n库存：0 件"
    assert result["input_audit_lines"] == ["输入指纹：worker-test", "库存：0 件"]
    assert result["rows"]
    assert "策略" not in result["rows"][0]
    parsed_result = parse_action_ev_worker_result(result)
    assert parsed_result.to_display_rows()[0]["策略"]
    assert summary["status"] == "ok"
    assert summary["engine"] == "inventory_recursive"
    assert summary["action_mode"] == "fast"
    assert summary["execution_mode"] == "worker_process"
    assert summary["input_audit"] == result["input_audit"]
    assert summary["input_audit_lines"] == result["input_audit_lines"]
    assert summary["rows"] == len(result["rows"])
    assert result["performance_audit"]["action_count"] == len(result["rows"])
    assert summary["performance_audit"]["action_count"] == len(result["rows"])
    assert any(event["event"] == "worker_start" for event in progress_events)
    assert any(event.get("engine") == "inventory_recursive" for event in progress_events)
    assert any(event.get("action_mode") == "fast" for event in progress_events)
    assert any(event["event"] == "worker_done" for event in progress_events)
    assert any(event.get("performance_audit") for event in progress_events)
    assert any(
        event.get("inner_event") == "candidate_generation_step_done"
        for event in progress_events
    )
    assert any("aggregated_outcome_cache_misses" in event for event in progress_events)
    assert not error_path.exists()


def test_action_ev_worker_writes_error_json_for_bad_input(tmp_path):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "result.json"
    progress_path = tmp_path / "progress.jsonl"
    error_path = tmp_path / "error.json"
    summary_path = tmp_path / "summary.json"
    _write_worker_input(input_path, game_id="missing-game")

    assert (
        worker_main(
            [
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--progress",
                str(progress_path),
                "--error",
                str(error_path),
                "--summary",
                str(summary_path),
            ]
        )
        == 1
    )

    error = json.loads(error_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert error["schema_version"] == ACTION_EV_PROTOCOL_SCHEMA_VERSION
    assert summary["schema_version"] == ACTION_EV_PROTOCOL_SCHEMA_VERSION
    assert error["status"] == "error"
    assert "missing-game" in error["message"]
    assert error["input_audit"] == "输入指纹：worker-test\n库存：0 件"
    assert error["input_audit_lines"] == ["输入指纹：worker-test", "库存：0 件"]
    assert "traceback" in error
    assert summary["status"] == "error"
    assert summary["input_audit"] == error["input_audit"]
    assert summary["input_audit_lines"] == error["input_audit_lines"]
    assert not output_path.exists()


def test_action_ev_worker_reports_unsupported_request_schema(tmp_path):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "result.json"
    progress_path = tmp_path / "progress.jsonl"
    error_path = tmp_path / "error.json"
    summary_path = tmp_path / "summary.json"
    _write_worker_input(input_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert worker_main(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--progress",
            str(progress_path),
            "--error",
            str(error_path),
            "--summary",
            str(summary_path),
        ]
    ) == 1

    error = json.loads(error_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert error["error_type"] == "UnsupportedActionEvProtocolVersionError"
    assert "schema_version=2" in error["message"]
    assert summary["status"] == "error"
    assert not output_path.exists()


def test_progress_jsonl_writer_throttles_non_critical_events(tmp_path):
    progress_path = tmp_path / "progress.jsonl"
    with ProgressJsonlWriter(progress_path, "test-run", min_interval_seconds=60.0) as writer:
        writer.emit({"event": "unit_progress", "label": "first"})
        writer.emit({"event": "unit_progress", "label": "skipped"})
        writer.emit({"event": "complete", "label": "done"})

    raw_events = [
        json.loads(line)
        for line in progress_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    events = [parse_action_ev_progress_event(event).to_flat_dict() for event in raw_events]
    assert [event["label"] for event in events] == ["first", "done"]
