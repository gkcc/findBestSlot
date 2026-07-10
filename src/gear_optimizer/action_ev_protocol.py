from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gear_optimizer.action_types import (
    DEFAULT_ACTION_EV_ENGINE,
    DEFAULT_ACTION_EV_MODE,
    ActionEvEngine,
    ActionEvMode,
)
from gear_optimizer.models import GearPiece

ACTION_EV_PROTOCOL_SCHEMA_VERSION = 1
ACTION_EV_WORKER_EXECUTION_MODE = "worker_process"


class UnsupportedActionEvProtocolVersionError(ValueError):
    pass


class _ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = ACTION_EV_PROTOCOL_SCHEMA_VERSION
    run_id: str = Field(min_length=1)


class ActionEvSubstatPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stat: str
    rolls: int = Field(default=0, ge=0)


class ActionEvPiecePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int | str
    set_name: str
    main_stat: str
    level: int = Field(default=0, ge=0)
    substats: list[ActionEvSubstatPayload] = Field(default_factory=list)
    locked: bool = False
    initial_substat_count: Literal[3, 4] = 4
    revealed_next_substat: str | None = None


class ActionEvWorkerRequest(_ProtocolModel):
    game_id: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    probability_model_id: str = Field(min_length=1)
    current_pieces: list[ActionEvPiecePayload] = Field(default_factory=list)
    inventory_pieces: list[ActionEvPiecePayload] = Field(default_factory=list)
    horizon: Literal[1, 2] = 1
    engine: ActionEvEngine = ActionEvEngine(DEFAULT_ACTION_EV_ENGINE)
    action_mode: ActionEvMode = ActionEvMode(DEFAULT_ACTION_EV_MODE)
    input_audit: str = ""
    input_audit_lines: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def fill_input_audit_lines(self) -> "ActionEvWorkerRequest":
        if not self.input_audit_lines and self.input_audit:
            self.input_audit_lines = self.input_audit.splitlines()
        return self


class ActionEvConditionBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: str = ""
    probability: float = Field(default=0.0, ge=0.0, le=1.0)
    representative_piece: str = ""
    second_action: str = ""
    second_action_reason: str = ""
    representative_final_loadout: str = ""
    set_constraint: str = ""

    @classmethod
    def from_display_dict(cls, value: Mapping[str, Any]) -> "ActionEvConditionBranch":
        unknown = set(value) - set(_BRANCH_FIELD_TO_DISPLAY_KEY.values())
        if unknown:
            raise ValueError(f"Unsupported Action EV condition-branch fields: {sorted(unknown)}")
        return cls.model_validate(
            {
                field_name: value[display_key]
                for field_name, display_key in _BRANCH_FIELD_TO_DISPLAY_KEY.items()
                if display_key in value
            }
        )

    def to_display_dict(self) -> dict[str, Any]:
        return {
            display_key: getattr(self, field_name)
            for field_name, display_key in _BRANCH_FIELD_TO_DISPLAY_KEY.items()
        }


class ActionEvPlanExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_type: str = ""
    first_action: str = ""
    second_step_summary: str = ""
    condition_branches: list[ActionEvConditionBranch] = Field(default_factory=list)
    representative_path_note: str = ""


class ActionEvRowPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: str = ""
    strategy: str = ""
    target_set: str = ""
    position: str = ""
    main_stat: str = ""
    fixed_substats: str = ""
    horizon: int = Field(default=1, ge=1)
    immediate_ev: str = ""
    option_ev: str = ""
    horizon_ev: str = ""
    expected_gain: str = ""
    plan_type: str = ""
    first_action: str = ""
    second_step_summary: str = ""
    calculation_scope: str = ""
    fixed_main_audit: str = ""
    fixed_substat_audit: str = ""
    representative_path: str = ""
    expected_loadout: str = ""
    representative_branch_loadout: str = ""
    complement_slots: str = ""
    set_constraint: str = ""
    condition_branches: list[ActionEvConditionBranch] = Field(default_factory=list)
    representative_path_note: str = ""
    representative_loadout_rows: list[dict[str, Any]] = Field(default_factory=list)
    upgrade_inventory_id: str = ""
    set_completion_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    set_completion_per_mother: float | str = 0.0
    quality_gain: float = 0.0
    effective_gain: float = 0.0
    mother_cost: float | str = 0.0
    tuner_cost: float | str = 0.0
    resonance_core_cost: float | str = 0.0
    advanced_material_cost: float | str = 0.0
    quality_per_mother: float | str = 0.0
    effective_per_mother: float | str = 0.0
    sort_vector_label: str = ""
    sort_vector: list[float] = Field(default_factory=list)
    relative_to_random: str = ""
    comparison_scope: str = ""

    @classmethod
    def from_display_row(cls, row: Mapping[str, Any]) -> "ActionEvRowPayload":
        unknown = set(row) - set(_ROW_FIELD_TO_DISPLAY_KEY.values())
        if unknown:
            raise ValueError(f"Unsupported Action EV row fields: {sorted(unknown)}")
        values: dict[str, Any] = {}
        for field_name, display_key in _ROW_FIELD_TO_DISPLAY_KEY.items():
            if display_key not in row:
                continue
            value = row[display_key]
            if field_name == "condition_branches":
                if not isinstance(value, list):
                    raise ValueError("Action EV condition branches must be a list")
                if any(not isinstance(item, Mapping) for item in value):
                    raise ValueError("Action EV condition branch must be a JSON object")
                values[field_name] = [
                    ActionEvConditionBranch.from_display_dict(item)
                    for item in value
                ]
            elif field_name == "representative_loadout_rows":
                values[field_name] = encode_protocol_value(value)
            elif field_name == "sort_vector":
                values[field_name] = list(value or [])
            else:
                values[field_name] = value
        return cls.model_validate(values)

    def to_display_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {}
        for field_name, display_key in _ROW_FIELD_TO_DISPLAY_KEY.items():
            value = getattr(self, field_name)
            if field_name == "condition_branches":
                row[display_key] = [branch.to_display_dict() for branch in value]
            elif field_name == "representative_loadout_rows":
                row[display_key] = decode_protocol_value(value)
            elif field_name == "sort_vector":
                row[display_key] = tuple(value)
            else:
                row[display_key] = value
        return row


class ActionEvPerformanceAuditPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_count: int = Field(default=0, ge=0)
    raw_outcome_count: int = Field(default=0, ge=0)
    aggregated_outcome_count: int = Field(default=0, ge=0)
    best_loadout_value_calls: int = Field(default=0, ge=0)
    best_loadout_cache_hits: int = Field(default=0, ge=0)
    best_loadout_cache_misses: int = Field(default=0, ge=0)
    outcome_cache_hits: int = Field(default=0, ge=0)
    outcome_cache_misses: int = Field(default=0, ge=0)
    action_timings: list[dict[str, Any]] = Field(default_factory=list)
    top_10_slowest_actions: list[dict[str, Any]] = Field(default_factory=list)
    phase_seconds: dict[str, float] = Field(default_factory=dict)
    phase_counts: dict[str, int] = Field(default_factory=dict)
    phase_average_seconds: dict[str, float] = Field(default_factory=dict)
    top_20_slowest_phase_calls: list[dict[str, Any]] = Field(default_factory=list)
    total_seconds: float = Field(default=0.0, ge=0.0)


class ActionEvWorkerResult(_ProtocolModel):
    engine: ActionEvEngine
    action_mode: ActionEvMode
    execution_mode: Literal["worker_process"] = ACTION_EV_WORKER_EXECUTION_MODE
    input_audit: str = ""
    input_audit_lines: list[str] = Field(default_factory=list)
    performance_audit: ActionEvPerformanceAuditPayload = Field(
        default_factory=ActionEvPerformanceAuditPayload
    )
    rows: list[ActionEvRowPayload] = Field(default_factory=list)

    def to_display_rows(self) -> list[dict[str, Any]]:
        return [row.to_display_row() for row in self.rows]


class ActionEvProgressEvent(_ProtocolModel):
    event: str = Field(min_length=1)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    wall_time: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_flat_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "elapsed_seconds": self.elapsed_seconds,
            "wall_time": self.wall_time,
            "event": self.event,
            **decode_protocol_value(self.payload),
        }


class ActionEvWorkerError(_ProtocolModel):
    status: Literal["error"] = "error"
    engine: str = ""
    execution_mode: Literal["worker_process"] = ACTION_EV_WORKER_EXECUTION_MODE
    error_type: str = ""
    message: str = ""
    traceback: str = ""
    finished_at: str = ""
    input_audit: str = ""
    input_audit_lines: list[str] = Field(default_factory=list)


class ActionEvWorkerSummary(_ProtocolModel):
    status: Literal["ok", "error", "cancelled"]
    input_path: str = ""
    output_path: str = ""
    progress_path: str = ""
    error_path: str = ""
    engine: str = ""
    action_mode: str = ""
    execution_mode: Literal["worker_process"] = ACTION_EV_WORKER_EXECUTION_MODE
    started_at: str = ""
    finished_at: str = ""
    horizon: Literal[1, 2] = 1
    input_audit: str = ""
    input_audit_lines: list[str] = Field(default_factory=list)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    rows: int | None = Field(default=None, ge=0)
    performance_audit: ActionEvPerformanceAuditPayload | None = None


_BRANCH_FIELD_TO_DISPLAY_KEY = {
    "condition": "条件",
    "probability": "条件概率",
    "representative_piece": "代表新盘",
    "second_action": "第二步 action",
    "second_action_reason": "第二步原因",
    "representative_final_loadout": "代表最终搭配",
    "set_constraint": "套装约束",
}

_ROW_FIELD_TO_DISPLAY_KEY = {
    "action_type": "动作类型",
    "strategy": "策略",
    "target_set": "目标套装",
    "position": "位置",
    "main_stat": "主属性",
    "fixed_substats": "固定副属性",
    "horizon": "horizon",
    "immediate_ev": "immediate_EV",
    "option_ev": "option_EV",
    "horizon_ev": "horizon_EV",
    "expected_gain": "期望提升",
    "plan_type": "方案类型",
    "first_action": "第一步 action",
    "second_step_summary": "第二步策略摘要",
    "calculation_scope": "计算口径",
    "fixed_main_audit": "锁主审计",
    "fixed_substat_audit": "锁副审计",
    "representative_path": "代表路径",
    "expected_loadout": "预期搭配",
    "representative_branch_loadout": "代表分支搭配",
    "complement_slots": "互补位",
    "set_constraint": "套装约束",
    "condition_branches": "条件分支",
    "representative_path_note": "代表路径说明",
    "representative_loadout_rows": "_representative_loadout_rows",
    "upgrade_inventory_id": "_upgrade_inventory_id",
    "set_completion_probability": "成型跃迁概率",
    "set_completion_per_mother": "成型跃迁/母盘",
    "quality_gain": "质量提升",
    "effective_gain": "有效提升",
    "mother_cost": "母盘/次",
    "tuner_cost": "校音器/次",
    "resonance_core_cost": "共鸣核/次",
    "advanced_material_cost": "高级素材/次",
    "quality_per_mother": "质量/母盘",
    "effective_per_mother": "有效/母盘",
    "sort_vector_label": "排序向量/母盘",
    "sort_vector": "_sort_vector",
    "relative_to_random": "相对随机",
    "comparison_scope": "比较口径",
}


def encode_protocol_value(value: Any) -> Any:
    if isinstance(value, GearPiece):
        return {"__gear_piece__": value.model_dump(mode="json")}
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): encode_protocol_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_protocol_value(item) for item in value]
    return value


def decode_protocol_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if set(value) == {"__gear_piece__"}:
            return GearPiece.model_validate(value["__gear_piece__"])
        return {str(key): decode_protocol_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_protocol_value(item) for item in value]
    return value


def _normalise_protocol_payload(
    payload: Any,
    *,
    artifact: str,
    fallback_run_id: str,
) -> tuple[dict[str, Any], bool]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"Action EV {artifact} payload must be a JSON object")
    normalised = dict(payload)
    is_legacy = "schema_version" not in normalised
    raw_version = normalised.get("schema_version", 0)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise ValueError(f"Action EV {artifact} schema_version must be an integer")
    if raw_version not in {0, ACTION_EV_PROTOCOL_SCHEMA_VERSION}:
        raise UnsupportedActionEvProtocolVersionError(
            f"不支持 Action EV {artifact} schema_version={raw_version}；"
            f"当前支持版本为 {ACTION_EV_PROTOCOL_SCHEMA_VERSION}。"
        )
    is_legacy = is_legacy or raw_version == 0
    normalised["schema_version"] = ACTION_EV_PROTOCOL_SCHEMA_VERSION
    normalised["run_id"] = str(normalised.get("run_id") or fallback_run_id)
    return normalised, is_legacy


def parse_action_ev_worker_request(payload: Any) -> ActionEvWorkerRequest:
    normalised, _legacy = _normalise_protocol_payload(
        payload,
        artifact="request",
        fallback_run_id="legacy-request",
    )
    return ActionEvWorkerRequest.model_validate(normalised)


def parse_action_ev_worker_result(
    payload: Any,
    *,
    fallback_run_id: str = "legacy-result",
) -> ActionEvWorkerResult:
    normalised, _legacy = _normalise_protocol_payload(
        payload,
        artifact="result",
        fallback_run_id=fallback_run_id,
    )
    raw_rows = normalised.get("rows", [])
    if not isinstance(raw_rows, list):
        raise ValueError("Action EV result rows must be a list")
    normalised["rows"] = [
        ActionEvRowPayload.from_display_row(row).model_dump(mode="python")
        if isinstance(row, Mapping) and any(ord(char) > 127 for key in row for char in str(key))
        else row
        for row in raw_rows
    ]
    raw_performance = normalised.get("performance_audit")
    if raw_performance in (None, {}):
        normalised["performance_audit"] = {}
    return ActionEvWorkerResult.model_validate(normalised)


def parse_action_ev_progress_event(
    payload: Any,
    *,
    fallback_run_id: str = "legacy-progress",
) -> ActionEvProgressEvent:
    normalised, is_legacy = _normalise_protocol_payload(
        payload,
        artifact="progress",
        fallback_run_id=fallback_run_id,
    )
    if is_legacy:
        reserved = {"schema_version", "run_id", "event", "elapsed_seconds", "wall_time"}
        normalised["payload"] = {
            key: encode_protocol_value(value)
            for key, value in normalised.items()
            if key not in reserved
        }
        normalised = {
            key: value
            for key, value in normalised.items()
            if key in reserved or key == "payload"
        }
    return ActionEvProgressEvent.model_validate(normalised)


def parse_action_ev_worker_error(
    payload: Any,
    *,
    fallback_run_id: str = "legacy-error",
) -> ActionEvWorkerError:
    normalised, is_legacy = _normalise_protocol_payload(
        payload,
        artifact="error",
        fallback_run_id=fallback_run_id,
    )
    if is_legacy and "type" in normalised:
        normalised["error_type"] = normalised.pop("type")
    return ActionEvWorkerError.model_validate(normalised)


def parse_action_ev_worker_summary(
    payload: Any,
    *,
    fallback_run_id: str = "legacy-summary",
) -> ActionEvWorkerSummary:
    normalised, is_legacy = _normalise_protocol_payload(
        payload,
        artifact="summary",
        fallback_run_id=fallback_run_id,
    )
    if is_legacy:
        path_aliases = {
            "input": "input_path",
            "output": "output_path",
            "progress": "progress_path",
            "error": "error_path",
        }
        for legacy_key, field_name in path_aliases.items():
            if legacy_key in normalised:
                normalised[field_name] = normalised.pop(legacy_key)
    return ActionEvWorkerSummary.model_validate(normalised)


def protocol_json_data(model: BaseModel) -> dict[str, Any]:
    return encode_protocol_value(model.model_dump(mode="json", exclude_none=True))
