from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from gear_optimizer.models import CharacterPreset, GearPiece
from gear_optimizer.position_ev import ActionSpec


class PortfolioMode(StrEnum):
    ANY_USEFUL = "ANY_USEFUL"
    WEIGHTED_SUM = "WEIGHTED_SUM"

    @property
    def label(self) -> str:
        if self == PortfolioMode.WEIGHTED_SUM:
            return "加权总收益"
        return "任一代理人有用"

    @property
    def note(self) -> str:
        if self == PortfolioMode.WEIGHTED_SUM:
            return "WEIGHTED_SUM：每个 outcome 对所有选中代理人的正 best_loadout_value delta 按 weight 加权求和。"
        return "ANY_USEFUL：每个 outcome 只取所有选中代理人中最大的正 best_loadout_value delta，用于衡量互补覆盖。"


class PortfolioTarget(BaseModel):
    agent_id: str
    name: str
    character: CharacterPreset
    weight: float = Field(default=1.0, ge=0.0)
    current_pieces: list[GearPiece] | None = None

    @property
    def target_template_id(self) -> str:
        return self.character.id


class PortfolioGain(BaseModel):
    agent_id: str
    name: str
    target_template_id: str
    weight: float = 1.0
    immediate_gain: float = 0.0
    expected_gain: float = 0.0
    useful_probability: float = 0.0
    expected_delta_vector: list[float] = Field(default_factory=list)
    entered_best_loadout_probability: float = 0.0
    build_progress_probability: float = 0.0
    build_progress_gain: float = 0.0
    set_progress_detail: str = "-"
    position_coverage_detail: str = "-"
    main_stat_hit_detail: str = "-"
    candidate_observation_detail: str = "-"


class PortfolioActionRow(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    mode: PortfolioMode
    action_spec: ActionSpec
    action_type: str
    action_label: str
    target_set: str
    position: str
    main_stat: str
    fixed_substats: str
    portfolio_ev: float
    ev_per_mother: float
    useful_probability: float
    build_progress_probability: float = 0.0
    build_progress_gain: float = 0.0
    best_beneficiary_agent: str
    beneficiary_count: int
    target_gains: list[PortfolioGain] = Field(default_factory=list)
    mode_note: str
    mother_cost: float = 0.0
    tuner_cost: float = 0.0
    core_cost: float = 0.0
    entered_best_loadout_summary: str = "-"
    set_progress_detail: str = "-"
    position_coverage_detail: str = "-"
    main_stat_hit_detail: str = "-"
    candidate_observation_detail: str = "-"

    def _agent_gain_summary(self) -> str:
        parts = [
            f"{gain.name} +{gain.expected_gain:.3f} ({gain.useful_probability:.1%})"
            for gain in self.target_gains
            if gain.expected_gain > 0
        ]
        return "；".join(parts) if parts else "-"

    def _build_hint(self) -> str:
        if self.build_progress_probability <= 0:
            return "-"
        if self.portfolio_ev <= 0:
            return f"暂不成型，建设方向命中 {self.build_progress_probability:.1%}"
        return f"另有建设方向命中 {self.build_progress_probability:.1%}"

    def _recommendation_reason(self) -> str:
        if self.portfolio_ev > 0:
            beneficiary = self.best_beneficiary_agent or "至少一名代理人"
            return f"{beneficiary} 的 best_loadout 有正提升；建设审计不参与排序"
        if self.build_progress_probability > 0:
            return "主 EV 为 0；仅提示建设方向，不参与排序"
        return "未进入任何选中代理人的更优搭配"

    def to_recommendation_row(self) -> dict[str, object]:
        return {
            "调律动作": self.action_label,
            "目标套装": self.target_set,
            "位置": self.position,
            "主属性": self.main_stat,
            "主EV": round(self.portfolio_ev, 3),
            "EV/母盘": round(self.ev_per_mother, 4),
            "成型收益概率": f"{self.useful_probability:.1%}",
            "主要受益人": self.best_beneficiary_agent or "-",
            "受益人数": self.beneficiary_count,
            "受益明细": self._agent_gain_summary(),
            "建设提示": self._build_hint(),
            "说明": self._recommendation_reason(),
        }

    def to_display_row(self) -> dict[str, object]:
        details = "；".join(
            f"{gain.name}+{gain.expected_gain:.3f}"
            f"(成型p={gain.useful_probability:.1%},入选p={gain.entered_best_loadout_probability:.1%},"
            f"建设p={gain.build_progress_probability:.1%},w={gain.weight:g})"
            for gain in self.target_gains
        )
        return {
            "模式": self.mode.label,
            "动作类型": self.action_type,
            "调律策略/动作": self.action_label,
            "目标套装": self.target_set,
            "位置": self.position,
            "主属性": self.main_stat,
            "固定副属性": self.fixed_substats,
            "portfolio EV": round(self.portfolio_ev, 3),
            "EV/母盘": round(self.ev_per_mother, 4),
            "至少一人成型收益概率": f"{self.useful_probability:.1%}",
            "建设方向推进概率": f"{self.build_progress_probability:.1%}",
            "建设审计 gain": round(self.build_progress_gain, 3),
            "最佳受益代理人": self.best_beneficiary_agent or "-",
            "受益代理人数": self.beneficiary_count,
            "每代理人 gain 明细": details or "-",
            "outcome 入选更优搭配": self.entered_best_loadout_summary,
            "套装进度审计": self.set_progress_detail,
            "位置覆盖审计": self.position_coverage_detail,
            "主属性命中审计": self.main_stat_hit_detail,
            "胚子观察审计": self.candidate_observation_detail,
            "模式说明": self.mode_note,
        }


class PortfolioPieceCheckRow(BaseModel):
    agent_id: str
    name: str
    target_template_id: str
    immediate_gain: float = 0.0
    immediate_delta_vector: list[float] = Field(default_factory=list)
    upgrade_expected_gain: float = 0.0
    upgrade_expected_delta_vector: list[float] = Field(default_factory=list)
    upgrade_observation_gain: float = 0.0
    worth_observing: bool = False
    note: str = ""

    def to_display_row(self) -> dict[str, object]:
        return {
            "代理人": self.name,
            "目标模板": self.target_template_id,
            "即时 gain": round(self.immediate_gain, 3),
            "强化期望 gain": round(self.upgrade_expected_gain, 3),
            "强化观察增益": round(self.upgrade_observation_gain, 3),
            "是否值得强化观察": "是" if self.worth_observing else "否",
            "说明": self.note,
        }
