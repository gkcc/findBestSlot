from __future__ import annotations

from math import isclose
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PositionId = int | str


def position_key(position: PositionId) -> str:
    return str(position)


class EnhancementRule(BaseModel):
    max_level: int = 15
    step: int = 3
    initial_add_level: int = 3

    @property
    def event_levels(self) -> list[int]:
        return list(range(self.step, self.max_level + self.step, self.step))


class PositionRule(BaseModel):
    id: PositionId
    name: str
    main_stats: list[str]


class SetRequirement(BaseModel):
    set_name: str | None = None
    set_names: list[str] = Field(default_factory=list)
    pieces: int = Field(ge=1)
    role: str | None = None
    priority: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def normalize_set_names(self) -> "SetRequirement":
        names = list(self.set_names)
        if self.set_name:
            names.insert(0, self.set_name)
        unique_names = list(dict.fromkeys(name for name in names if name))
        if not unique_names:
            raise ValueError("set requirement must define set_name or set_names")
        self.set_names = unique_names
        self.set_name = unique_names[0]
        return self

    @property
    def primary_set(self) -> str:
        return self.set_names[0]


class SetPlan(BaseModel):
    id: str
    name: str
    requirements: list[SetRequirement] = Field(default_factory=list)
    notes: str | None = None

    @property
    def target_sets(self) -> list[str]:
        values: list[str] = []
        for requirement in self.requirements:
            values.extend(requirement.set_names)
        return list(dict.fromkeys(values))

    @property
    def is_unrestricted(self) -> bool:
        return not self.requirements


class SetEffect(BaseModel):
    two_piece: str | None = None
    four_piece: str | None = None


class SubstatPriority(BaseModel):
    core: list[str] = Field(default_factory=list)
    usable: list[str] = Field(default_factory=list)
    core_tiers: list[list[str]] = Field(default_factory=list)
    usable_tiers: list[list[str]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_tier_syntax(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        for field_name in ("core", "usable"):
            raw_items = normalized.get(field_name) or []
            if not isinstance(raw_items, list):
                continue
            tiers: list[list[str]] = []
            flat: list[str] = []
            has_nested = False
            for item in raw_items:
                if isinstance(item, list):
                    has_nested = True
                    tier = [str(value) for value in item if str(value)]
                else:
                    tier = [str(item)] if str(item) else []
                if not tier:
                    continue
                tiers.append(tier)
                flat.extend(tier)
            if has_nested:
                normalized[field_name] = flat
                normalized[f"{field_name}_tiers"] = tiers
        return normalized

    @model_validator(mode="after")
    def validate_no_duplicate_priority_stats(self) -> "SubstatPriority":
        if not self.core_tiers:
            self.core_tiers = [[stat] for stat in self.core]
        if not self.usable_tiers:
            self.usable_tiers = [[stat] for stat in self.usable]
        all_stats = self.core + self.usable
        if len(all_stats) != len(set(all_stats)):
            raise ValueError("substat_priority contains duplicate stats")
        return self

    def tiers(self) -> list[list[str]]:
        return [*self.core_tiers, *self.usable_tiers]


def weights_from_priority_groups(
    core_stats: list[str],
    usable_stats: list[str],
) -> dict[str, float]:
    return {
        stat: 1.0
        for stat in [*core_stats, *usable_stats]
        if stat
    }


def priority_groups_from_legacy_weights(
    effective_substats: dict[str, float],
) -> SubstatPriority:
    ordered = [
        (stat, value)
        for stat, value in sorted(
            effective_substats.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if value > 0
    ]
    core = [stat for stat, value in ordered if value >= 1.0]
    usable = [stat for stat, value in ordered if 0 < value < 1.0]
    if not core and usable:
        core = usable
        usable = []
    return SubstatPriority(core=core, usable=usable)


class GameRules(BaseModel):
    id: str
    name: str
    gear_name: str
    sets: list[str] = Field(default_factory=list)
    set_icons: dict[str, str] = Field(default_factory=dict)
    set_effects: dict[str, SetEffect] = Field(default_factory=dict)
    position_set_names: dict[str, list[str]] = Field(default_factory=dict)
    random_position_actions: bool = True
    board_layout: list[list[PositionId | None]] = Field(default_factory=list)
    positions: list[PositionRule]
    sub_stats: list[str]
    main_stat_probabilities: dict[str, dict[str, float]] = Field(default_factory=dict)
    sub_stat_probabilities: dict[str, float] = Field(default_factory=dict)
    enhancement: EnhancementRule = Field(default_factory=EnhancementRule)

    @model_validator(mode="after")
    def validate_probability_config(self) -> "GameRules":
        position_stats = {
            position_key(rule.id): set(rule.main_stats)
            for rule in self.positions
        }
        position_keys = set(position_stats)
        unknown_icon_sets = set(self.set_icons) - set(self.sets)
        if unknown_icon_sets:
            raise ValueError(f"set_icons references unknown sets: {sorted(unknown_icon_sets)}")
        unknown_effect_sets = set(self.set_effects) - set(self.sets)
        if unknown_effect_sets:
            raise ValueError(f"set_effects references unknown sets: {sorted(unknown_effect_sets)}")
        for position_id, set_names in self.position_set_names.items():
            if position_id not in position_keys:
                raise ValueError(f"position_set_names references unknown position: {position_id}")
            unknown_position_sets = set(set_names) - set(self.sets)
            if unknown_position_sets:
                raise ValueError(
                    f"position_set_names for {position_id} references unknown sets: "
                    f"{sorted(unknown_position_sets)}"
                )
        if self.board_layout:
            layout_keys = [
                position_key(value)
                for row in self.board_layout
                for value in row
                if value is not None
            ]
            unknown_positions = set(layout_keys) - position_keys
            if unknown_positions:
                raise ValueError(
                    f"board_layout references unknown positions: {sorted(unknown_positions)}"
                )
            duplicate_positions = sorted(
                key for key in set(layout_keys) if layout_keys.count(key) > 1
            )
            if duplicate_positions:
                raise ValueError(
                    f"board_layout contains duplicate positions: {duplicate_positions}"
                )
            missing_positions = position_keys - set(layout_keys)
            if missing_positions:
                raise ValueError(
                    f"board_layout is missing positions: {sorted(missing_positions)}"
                )

        for position_id, probabilities in self.main_stat_probabilities.items():
            if position_id not in position_stats:
                raise ValueError(f"main_stat_probabilities references unknown position: {position_id}")
            configured_stats = set(probabilities)
            expected_stats = position_stats[position_id]
            if configured_stats != expected_stats:
                missing = expected_stats - configured_stats
                extra = configured_stats - expected_stats
                details = []
                if missing:
                    details.append(f"missing {sorted(missing)}")
                if extra:
                    details.append(f"unknown {sorted(extra)}")
                raise ValueError(
                    f"main_stat_probabilities for {position_id} must match main_stats: "
                    + ", ".join(details)
                )
            if any(probability < 0 for probability in probabilities.values()):
                raise ValueError(f"main_stat_probabilities for {position_id} contains negative values")
            total = sum(probabilities.values())
            if not isclose(total, 1.0, rel_tol=1e-6, abs_tol=1e-6):
                raise ValueError(
                    f"main_stat_probabilities for {position_id} must sum to 1.0, got {total}"
                )

        sub_stats = set(self.sub_stats)
        unknown_substats = set(self.sub_stat_probabilities) - sub_stats
        if unknown_substats:
            raise ValueError(f"sub_stat_probabilities references unknown stats: {sorted(unknown_substats)}")
        if any(probability < 0 for probability in self.sub_stat_probabilities.values()):
            raise ValueError("sub_stat_probabilities contains negative values")
        return self

    def position(self, position: PositionId) -> PositionRule:
        key = position_key(position)
        for rule in self.positions:
            if position_key(rule.id) == key:
                return rule
        raise KeyError(f"Unknown position: {position}")

    def position_name(self, position: PositionId) -> str:
        return self.position(position).name

    def main_stats_for(self, position: PositionId) -> list[str]:
        return self.position(position).main_stats

    def set_icon_path(self, set_name: str) -> str | None:
        return self.set_icons.get(set_name)

    def set_effect(self, set_name: str) -> SetEffect | None:
        return self.set_effects.get(set_name)

    def sets_for_position(self, position: PositionId) -> list[str]:
        allowed = self.position_set_names.get(position_key(position))
        return list(allowed) if allowed else list(self.sets)

    def set_available_for_position(self, set_name: str, position: PositionId) -> bool:
        return set_name in self.sets_for_position(position)

    def main_stat_probability(self, position: PositionId, stat: str) -> float:
        key = position_key(position)
        explicit = self.main_stat_probabilities.get(key, {})
        if explicit:
            return explicit.get(stat, 0.0)
        stats = self.main_stats_for(position)
        if stat not in stats or not stats:
            return 0.0
        return 1.0 / len(stats)

    def available_substats(self, main_stat: str, existing: list[str] | None = None) -> list[str]:
        existing_set = set(existing or [])
        return [
            stat
            for stat in self.sub_stats
            if stat != main_stat and stat not in existing_set
        ]


class CharacterPreset(BaseModel):
    id: str
    game: str
    name: str
    target_set: str
    effective_substats: dict[str, float] = Field(default_factory=dict)
    substat_priority: SubstatPriority | None = None
    preferred_main_stats: dict[str, list[str]] = Field(default_factory=dict)
    set_plans: list[SetPlan] = Field(default_factory=list)
    default_set_plan: str | None = None
    target_effective_rolls: float = 6.0
    target_weighted_score: float | None = None
    rating_thresholds: dict[str, float] = Field(
        default_factory=lambda: {"usable": 2.0, "good": 4.0, "excellent": 6.0}
    )
    notes: str | None = None

    @model_validator(mode="after")
    def validate_character_basics(self) -> "CharacterPreset":
        if any(weight < 0 for weight in self.effective_substats.values()):
            raise ValueError("effective_substats contains negative weights")
        if self.substat_priority is None and self.effective_substats:
            self.substat_priority = priority_groups_from_legacy_weights(
                self.effective_substats
            )
        if self.substat_priority:
            self.effective_substats = weights_from_priority_groups(
                self.substat_priority.core,
                self.substat_priority.usable,
            )
        if self.target_weighted_score is not None and self.target_weighted_score < 0:
            raise ValueError("target_weighted_score cannot be negative")
        plan_ids = [plan.id for plan in self.set_plans]
        if len(plan_ids) != len(set(plan_ids)):
            raise ValueError("set_plans contains duplicate ids")
        if self.default_set_plan and self.default_set_plan not in plan_ids:
            raise ValueError(f"default_set_plan does not reference a known plan: {self.default_set_plan}")
        thresholds = self.rating_thresholds
        if (
            thresholds.get("usable", 2.0)
            > thresholds.get("good", 4.0)
            or thresholds.get("good", 4.0)
            > thresholds.get("excellent", 6.0)
        ):
            raise ValueError("rating_thresholds must be ordered usable <= good <= excellent")
        return self

    def is_effective(self, stat: str) -> bool:
        return stat in self.priority_stats()

    def weight_for(self, stat: str) -> float:
        return 1.0 if self.is_effective(stat) else 0.0

    def priority_stats(self) -> list[str]:
        if self.substat_priority is None:
            return [
                stat
                for stat, value in self.effective_substats.items()
                if value > 0
            ]
        return list(dict.fromkeys(self.substat_priority.core + self.substat_priority.usable))

    def priority_tiers(self, exclude: str | None = None) -> list[list[str]]:
        if self.substat_priority is None:
            return [[stat] for stat in self.priority_stats() if stat != exclude]
        tiers: list[list[str]] = []
        for tier in self.substat_priority.tiers():
            filtered = [stat for stat in tier if stat != exclude]
            if filtered:
                tiers.append(filtered)
        return tiers

    def ordered_effective_substats(self, exclude: str | None = None) -> list[str]:
        return [
            stat
            for stat in self.priority_stats()
            if stat != exclude
        ]

    def priority_group_for(self, stat: str) -> str | None:
        if self.substat_priority is None:
            return "核心" if stat in self.effective_substats else None
        if stat in self.substat_priority.core:
            return "核心"
        if stat in self.substat_priority.usable:
            return "可用"
        return None

    def priority_rank_for(self, stat: str) -> int | None:
        for index, tier in enumerate(self.priority_tiers(), start=1):
            if stat in tier:
                return index
        return None

    def priority_sort_index(self, stat: str) -> int:
        rank = self.priority_rank_for(stat)
        return rank if rank is not None else 999

    @property
    def weighted_target_score(self) -> float:
        target_weighted_score = getattr(self, "target_weighted_score", None)
        target_effective_rolls = getattr(self, "target_effective_rolls", 6.0)
        return (
            target_weighted_score
            if target_weighted_score is not None
            else target_effective_rolls
        )

    def preferred_mains_for(self, position: PositionId) -> list[str]:
        return self.preferred_main_stats.get(position_key(position), [])

    def active_set_plan(self) -> SetPlan | None:
        if not self.set_plans:
            return None
        if self.default_set_plan:
            for plan in self.set_plans:
                if plan.id == self.default_set_plan:
                    return plan
        return self.set_plans[0]


class ProbabilityModel(BaseModel):
    id: str
    game: str
    name: str
    target_set_probability: float = Field(default=0.5, ge=0.0, le=1.0)
    initial_substat_count_probabilities: dict[str, float] = Field(
        default_factory=lambda: {"3": 0.8, "4": 0.2}
    )
    resource_costs: dict[str, float] = Field(default_factory=dict)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_probability_model(self) -> "ProbabilityModel":
        expected_counts = {"3", "4"}
        configured_counts = set(self.initial_substat_count_probabilities)
        if configured_counts != expected_counts:
            raise ValueError("initial_substat_count_probabilities must define exactly 3 and 4")
        if any(value < 0 for value in self.initial_substat_count_probabilities.values()):
            raise ValueError("initial_substat_count_probabilities contains negative values")
        total = sum(self.initial_substat_count_probabilities.values())
        if not isclose(total, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError(
                f"initial_substat_count_probabilities must sum to 1.0, got {total}"
            )
        if any(value < 0 for value in self.resource_costs.values()):
            raise ValueError("resource_costs contains negative values")
        return self

    def resource_cost(self, key: str, default: float = 0.0) -> float:
        return self.resource_costs.get(key, default)


class SubstatLine(BaseModel):
    stat: str
    rolls: int = Field(default=0, ge=0)


class GearPiece(BaseModel):
    position: PositionId
    set_name: str
    main_stat: str
    level: int = Field(default=0, ge=0)
    substats: list[SubstatLine] = Field(default_factory=list)
    locked: bool = False
    initial_substat_count: Literal[3, 4] = 4

    @field_validator("substats")
    @classmethod
    def unique_substats(cls, value: list[SubstatLine]) -> list[SubstatLine]:
        names = [line.stat for line in value if line.stat]
        if len(names) != len(set(names)):
            raise ValueError("substats must be unique")
        return value

    @model_validator(mode="after")
    def main_stat_cannot_repeat_as_substat(self) -> "GearPiece":
        if self.main_stat and any(line.stat == self.main_stat for line in self.substats):
            raise ValueError("main_stat cannot appear in substats")
        return self


class CandidatePiece(GearPiece):
    pass


class PieceScore(BaseModel):
    position: PositionId
    position_name: str
    set_name: str
    main_stat: str
    level: int
    locked: bool = False
    effective_lines: int
    effective_rolls: float
    weighted_score: float
    rating: Literal["weak", "usable", "good", "excellent"]
    main_stat_preferred: bool
    set_plan_preferred: bool = True
    substat_details: list[dict[str, Any]] = Field(default_factory=list)


class CurrentGearAnalysis(BaseModel):
    scores: list[PieceScore]
    weakest_position: PositionId | None
    weakest_position_name: str | None
    relative_priority: list[dict[str, Any]]
    set_plan: dict[str, Any] | None = None


class DistributionPoint(BaseModel):
    effective_rolls: float
    probability: float


class WeightedDistributionPoint(BaseModel):
    weighted_score: float
    probability: float


class CandidateEvaluation(BaseModel):
    current_effective_rolls: float
    current_effective_lines: int
    current_weighted_score: float
    remaining_upgrade_events: int
    remaining_roll_events: int
    per_event_hit_probabilities: list[float]
    per_event_expected_weighted_gains: list[float] = Field(default_factory=list)
    event_rows: list[dict[str, Any]] = Field(default_factory=list)
    event_descriptions: list[str]
    final_expected_effective_rolls: float
    final_expected_weighted_score: float
    distribution: list[DistributionPoint]
    weighted_distribution: list[WeightedDistributionPoint] = Field(default_factory=list)
    recommendation: Literal["继续", "暂停", "放弃", "仅过渡"]
    reason: str
    warnings: list[str] = Field(default_factory=list)


class StrategyRow(BaseModel):
    strategy_name: str
    target_set: str
    target_set_options: list[str] = Field(default_factory=list)
    target_position: PositionId
    target_position_name: str
    target_main_stat: str
    fixed_position: bool
    fixed_main_stat: bool
    fixed_substats: list[str]
    fixed_substat_details: list[dict[str, Any]] = Field(default_factory=list)
    probability_breakdown: dict[str, float] = Field(default_factory=dict)
    candidate_probability: float
    expected_mother_disks: float
    expected_tuners: float
    expected_cores: float
    long_term_value_score: float
    current_relative_gain_score: float
    recommendation: str
