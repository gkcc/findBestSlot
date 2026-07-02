from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import sys
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gear_optimizer.candidate_ev import evaluate_candidate
from gear_optimizer.conclusions import (
    candidate_conclusion_rows,
    candidate_contextual_recommendation,
    candidate_next_step_rows,
    candidate_outcome_rows,
    current_gear_conclusion_rows,
    first_version_acceptance_rows,
    first_version_next_action_rows,
    high_priority_closure_rows,
    probability_model_assumption_rows,
    resource_guardrail_rows,
    set_plan_status_text as shared_set_plan_status_text,
    strategy_brief as shared_strategy_brief,
    strategy_conclusion_rows,
    today_action_summary_rows,
)
from gear_optimizer.exporting import (
    candidate_yaml,
    character_target_yaml,
    current_gear_yaml,
    probability_model_yaml,
)
from gear_optimizer.game_rules import (
    load_characters,
    load_games,
    load_probability_models,
    validate_candidate_against_game,
    validate_character_against_game,
    validate_current_gear_against_game,
    validate_gear_piece_against_game,
)
from gear_optimizer.layout import board_center_slot, board_layout_for_game
from gear_optimizer.models import (
    CandidatePiece,
    GearPiece,
    SetPlan,
    SetRequirement,
    SubstatPriority,
    SubstatLine,
    position_key,
)
from gear_optimizer.presets import (
    list_candidate_examples,
    list_current_examples,
    load_candidate_yaml_text,
    load_character_target_yaml_text,
    load_current_yaml_text,
    load_probability_model_yaml_text,
    load_candidate_example,
    load_current_example,
)
from gear_optimizer.position_ev import (
    action_ev_brief,
    best_loadout_rows,
    fixed_main_gain_ladder_rows,
    fixed_substat_gain_ladder_rows,
    initial_substat_tier_rows,
    position_strategy_efficiency_rows,
    recommended_action_ev_row,
    resource_marginal_ev_rows,
)
from gear_optimizer.recommendation import (
    current_priority_text,
    resource_decision_text,
    set_plan_next_action_rows,
    set_plan_stage_rows,
    set_plan_step_text,
    strategy_alignment_text,
    strategy_text,
)
from gear_optimizer.reporting import (
    candidate_analysis_report_markdown,
    current_analysis_report_markdown,
    first_version_acceptance_report_markdown,
)
from gear_optimizer.scoring import analyse_current_gear
from gear_optimizer.strategy import (
    build_strategy_rows,
    build_strategy_sweep,
    fixed_substat_note,
    strategy_context_rows,
    strategy_cost_ladder,
    top_strategy,
)
from gear_optimizer.user_current_gear import (
    current_gear_store_path,
    delete_user_current_gear,
    load_user_current_gears,
    save_user_current_gear,
)
from gear_optimizer.user_inventory import (
    load_user_inventory,
    save_user_inventory,
    user_inventory_store_path,
)


st.set_page_config(page_title="gacha-gear-optimizer", layout="wide")

CATALOG_CACHE_VERSION = 8


@st.cache_data
def _load_catalog(cache_version: int):
    _ = cache_version
    games = load_games()
    characters = load_characters()
    probabilities = load_probability_models()
    return games, characters, probabilities


def _choice_index(options: list[str], value: str | None) -> int:
    if value in options:
        return options.index(value)  # type: ignore[arg-type]
    return 0


def _level_index(level: int) -> int:
    levels = [0, 3, 6, 9, 12, 15]
    return levels.index(level) if level in levels else 0


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(int(value), maximum))


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return max(float(minimum), min(float(value), float(maximum)))


def _safe_filename(value: str) -> str:
    return "".join(
        char.lower() if char.isalnum() else "_"
        for char in value
    ).strip("_") or "export"


def _compact_label(value: str, max_chars: int = 6) -> str:
    return value if len(value) <= max_chars else f"{value[:max_chars]}..."


def _short_stat_label(value: str) -> str:
    replacements = {
        "生命值百分比": "生命%",
        "攻击力百分比": "攻击%",
        "防御力百分比": "防御%",
        "暴击率": "暴率",
        "暴击伤害": "暴伤",
        "物理伤害": "物伤",
        "火属性伤害": "火伤",
        "冰属性伤害": "冰伤",
        "电属性伤害": "电伤",
        "以太伤害": "以太",
        "异常精通": "异常",
        "异常掌控": "掌控",
        "能量自动回复": "回能",
        "冲击力": "冲击",
    }
    return replacements.get(value, _compact_label(value, 4))


def _selectbox(
    container,
    label: str,
    options: list,
    default,
    key: str,
    **kwargs,
):
    fallback = default if default in options else options[0]
    if key in st.session_state and st.session_state[key] not in options:
        st.session_state[key] = fallback
    return container.selectbox(
        label,
        options,
        index=options.index(fallback),
        key=key,
        **kwargs,
    )


def _number_input(
    container,
    label: str,
    key: str,
    value: int,
    maximum: int,
    disabled: bool = False,
) -> int:
    maximum = max(int(maximum), 0)
    if key in st.session_state:
        st.session_state[key] = _clamp_int(st.session_state[key], 0, maximum)
    else:
        st.session_state[key] = _clamp_int(value, 0, maximum)
    return int(
        container.number_input(
            label,
            min_value=0,
            max_value=maximum,
            step=1,
            key=key,
            disabled=disabled,
        )
    )


def _float_number_input(
    container,
    label: str,
    key: str,
    value: float,
    minimum: float = 0.0,
    maximum: float = 20.0,
    step: float = 0.1,
    format: str = "%.1f",
    disabled: bool = False,
) -> float:
    maximum = max(float(maximum), float(minimum))
    if key in st.session_state:
        st.session_state[key] = _clamp_float(st.session_state[key], minimum, maximum)
    else:
        st.session_state[key] = _clamp_float(value, minimum, maximum)
    return float(
        container.number_input(
            label,
            min_value=float(minimum),
            max_value=float(maximum),
            step=float(step),
            format=format,
            key=key,
            disabled=disabled,
        )
    )


def _upgrade_events_at_level(game, level: int) -> int:
    return sum(1 for event_level in game.enhancement.event_levels if event_level <= level)


def _visible_substat_slots(game, level: int, initial_count: int) -> int:
    if initial_count == 4 or level >= game.enhancement.initial_add_level:
        return 4
    return 3


def _max_rolls_at_level(game, level: int, initial_count: int) -> int:
    events = _upgrade_events_at_level(game, level)
    if initial_count == 3 and level >= game.enhancement.initial_add_level:
        events -= 1
    return max(events, 0)


def _safe_substats(
    rows: list[tuple[str, int]],
    key_prefix: str,
    main_stat: str | None = None,
) -> tuple[list[SubstatLine], list[str]]:
    seen: set[str] = set()
    substats: list[SubstatLine] = []
    warnings: list[str] = []
    for stat, rolls in rows:
        if not stat:
            continue
        if main_stat and stat == main_stat:
            warnings.append(f"{key_prefix} 副属性不能与主属性相同：{stat}，已忽略。")
            continue
        if stat in seen:
            warnings.append(f"{key_prefix} 存在重复副属性：{stat}，已只保留第一条。")
            continue
        seen.add(stat)
        substats.append(SubstatLine(stat=stat, rolls=rolls))
    return substats, warnings


def _piece_preview_values(
    substats: list[SubstatLine],
    character,
) -> tuple[int, float, float]:
    effective_line_count = 0
    effective_roll_count = 0.0
    quality_score = 0.0
    for line in substats:
        if not character.is_effective(line.stat):
            continue
        effective_line_count += 1
        total_rolls = 1 + line.rolls
        effective_roll_count += total_rolls
        quality_score += total_rolls
    return effective_line_count, effective_roll_count, quality_score


def _substat_effective_label(substats: list[SubstatLine]) -> str:
    if not substats:
        return "未填写"
    return "；".join(
        f"{line.stat}+{line.rolls}" if line.rolls else line.stat
        for line in substats
    )


def _piece_edit_status_frame(
    visible_slots: int,
    used_rolls: int,
    max_rolls: int,
    substats: list[SubstatLine],
    warnings: list[str],
) -> pd.DataFrame:
    remaining_rolls = max(max_rolls - used_rolls, 0)
    return pd.DataFrame(
        [
            {
                "项目": "实时更新",
                "状态": "已写入当前会话",
                "说明": "每次修改都会重算；长期复用请保存当前盘面。",
            },
            {
                "项目": "可见副属性",
                "状态": f"{len(substats)}/{visible_slots}",
                "说明": "等级或初始词条数变化时，不可见栏位不会计入分析。",
            },
            {
                "项目": "roll 预算",
                "状态": f"{used_rolls}/{max_rolls}",
                "说明": "已用满" if remaining_rolls == 0 else f"还可分配 {remaining_rolls} 次。",
            },
            {
                "项目": "实际生效副属性",
                "状态": _substat_effective_label(substats),
                "说明": "主属性同名、重复或隐藏栏位会被自动过滤。",
            },
            {
                "项目": "校验",
                "状态": f"{len(warnings)} 条自动修正" if warnings else "通过",
                "说明": "有修正时可在页面下方展开查看详情。",
            },
        ]
    )


def _substat_options(
    game,
    main_stat: str,
    selected: str | None = None,
    existing: list[str] | None = None,
) -> list[str]:
    options = [""] + game.available_substats(main_stat, existing)
    if selected and selected != main_stat and selected not in (existing or []) and selected not in options:
        options.append(selected)
    return options


def _piece_state(piece: GearPiece, initial_count: int | None = None) -> dict:
    rows = [{"stat": "", "rolls": 0} for _ in range(4)]
    for index, line in enumerate(piece.substats[:4]):
        rows[index] = {"stat": line.stat, "rolls": line.rolls}
    resolved_initial_count = (
        piece.initial_substat_count
        if initial_count is None
        else initial_count
    )
    return {
        "position": piece.position,
        "set_name": piece.set_name,
        "main_stat": piece.main_stat,
        "level": piece.level,
        "locked": piece.locked,
        "initial_count": resolved_initial_count,
        "substats": rows,
    }


def _blank_current_pieces(game, character) -> list[GearPiece]:
    pieces: list[GearPiece] = []
    for position in game.positions:
        pieces.append(
            GearPiece(
                position=position.id,
                set_name=character.target_set,
                main_stat=position.main_stats[0],
                level=0,
                substats=[],
                locked=False,
            )
        )
    return pieces


def _default_current_pieces(game, character) -> list[GearPiece]:
    examples = list_current_examples(game.id, character.id)
    if examples:
        pieces = load_current_example(examples[0]["path"])
        validate_current_gear_against_game(pieces, game)
        return pieces
    return _blank_current_pieces(game, character)


def _set_options_for_character(game, character, current: str | None = None) -> list[str]:
    values = list(_set_option_groups_for_character(game, character, current))
    return values


def _set_option_groups_for_character(
    game,
    character,
    current: str | None = None,
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    active_plan = character.active_set_plan()
    if active_plan and not active_plan.is_unrestricted:
        for requirement in active_plan.requirements:
            options = list(dict.fromkeys(requirement.set_names))
            groups[_set_group_label(options)] = options
            for set_name in options:
                groups.setdefault(set_name, [set_name])
    values = [character.target_set] + game.sets
    if current:
        values.append(current)
    for set_name in values:
        groups.setdefault(set_name, [set_name])
    return groups


def _set_group_label(set_names: list[str]) -> str:
    if not set_names:
        return "未指定"
    if len(set_names) == 1:
        return set_names[0]
    return " / ".join(set_names)


def _set_requirement_config_label(requirement: SetRequirement) -> str:
    return f"{_set_group_label(requirement.set_names)} {requirement.pieces}"


def _effective_substats_by_priority(character, exclude: str | None = None) -> list[str]:
    return character.ordered_effective_substats(exclude=exclude)


def _priority_groups_from_effective_substats(character) -> tuple[list[str], list[str]]:
    priority = character.substat_priority
    core = list(priority.core) if priority else character.priority_stats()
    usable = list(priority.usable) if priority else []
    return core, usable


def _markers_from_priority_groups(core_stats: list[str], usable_stats: list[str]) -> dict[str, float]:
    return {
        stat: 1.0
        for stat in [*core_stats, *usable_stats]
        if stat
    }


def _substat_priority_preview_frame(core_stats: list[str], usable_stats: list[str]) -> pd.DataFrame:
    rows = []
    for index, stat in enumerate(core_stats, start=1):
        rows.append(
            {
                "分组": "核心",
                "顺位": index,
                "副词条": stat,
                "算法作用": "优先作为评分、候选强化和固定副属性排序目标",
            }
        )
    for index, stat in enumerate(usable_stats, start=1):
        rows.append(
            {
                "分组": "可用/过渡",
                "顺位": index,
                "副词条": stat,
                "算法作用": "参与评分，但低于核心词条；适合作为过渡收益",
            }
        )
    if not rows:
        rows.append(
            {
                "分组": "未配置",
                "顺位": "-",
                "副词条": "-",
                "算法作用": "至少选择一个核心或可用副词条",
            }
        )
    return pd.DataFrame(rows)


def _effective_substat_summary(character) -> str:
    core, usable = _priority_groups_from_effective_substats(character)
    parts = []
    if core:
        parts.append(f"核心：{' > '.join(core)}")
    if usable:
        parts.append(f"可用：{' > '.join(usable)}")
    return "；".join(parts) if parts else "-"


def _set_plan_requirements_summary(plan: SetPlan | None) -> str:
    if plan is None:
        return "-"
    if plan.is_unrestricted:
        return "不限套装"
    return "；".join(
        f"{_set_group_label(requirement.set_names)} {requirement.pieces} 件"
        for requirement in plan.requirements
    )


def _main_stat_target_summary(game, character) -> str:
    values: list[str] = []
    for rule in game.positions:
        preferred = character.preferred_mains_for(rule.id)
        if preferred:
            target = " / ".join(preferred)
        elif len(rule.main_stats) == 1:
            target = rule.main_stats[0]
        else:
            continue
        values.append(f"{rule.name}：{target}")
    return "；".join(values) if values else "不限主属性"


def _render_character_target_summary(game, character) -> None:
    active_plan = character.active_set_plan()
    plan_note = (active_plan.notes if active_plan and active_plan.notes else "").strip()
    summary_rows = [
        {
            "项目": "套装方案",
            "当前配置": active_plan.name if active_plan else character.target_set,
        },
        {
            "项目": "套装要求",
            "当前配置": _set_plan_requirements_summary(active_plan),
        },
        {
            "项目": "主属性倾向",
            "当前配置": _main_stat_target_summary(game, character),
        },
        {
            "项目": "副词条优先级",
            "当前配置": _effective_substat_summary(character),
        },
        {
            "项目": "目标线",
            "当前配置": (
                f"{character.target_effective_rolls:g} 有效词条 / "
                f"{character.weighted_target_score:g} 质量分"
            ),
        },
    ]
    if plan_note:
        summary_rows.insert(
            2,
            {
                "项目": "方案说明",
                "当前配置": plan_note,
            },
        )
    with st.sidebar.expander("当前目标摘要", expanded=True):
        st.table(pd.DataFrame(summary_rows))
        st.download_button(
            "导出当前角色目标",
            data=character_target_yaml(character),
            file_name=(
                f"{_safe_filename(game.id)}_"
                f"{_safe_filename(character.id)}_target.yaml"
            ),
            mime="application/x-yaml",
            key=f"download_character_target_sidebar_{game.id}_{character.id}",
        )


def _character_target_import_state_key(game, character) -> str:
    return f"character_target_import::{game.id}::{character.id}"


def _character_target_import_digest_key(game, character) -> str:
    return f"character_target_digest::{game.id}::{character.id}"


def _character_target_version(game, character) -> str:
    digest = str(st.session_state.get(_character_target_import_digest_key(game, character)) or "")
    return digest[:12] if digest else "base"


def _character_control_key(game, character, suffix: str) -> str:
    return f"{suffix}_{game.id}_{character.id}_{_character_target_version(game, character)}"


def _merge_imported_character_target(base_character, imported_character):
    return base_character.model_copy(
        update={
            "target_set": imported_character.target_set,
            "effective_substats": imported_character.effective_substats,
            "substat_priority": imported_character.substat_priority,
            "preferred_main_stats": imported_character.preferred_main_stats,
            "set_plans": imported_character.set_plans,
            "default_set_plan": imported_character.default_set_plan,
            "target_effective_rolls": imported_character.target_effective_rolls,
            "target_weighted_score": imported_character.target_weighted_score,
            "rating_thresholds": imported_character.rating_thresholds,
            "notes": imported_character.notes,
        }
    )


def _render_character_target_import_controls(game, character):
    state_key = _character_target_import_state_key(game, character)
    digest_key = _character_target_import_digest_key(game, character)
    active_character = st.session_state.get(state_key, character)

    with st.sidebar.expander("角色目标 YAML", expanded=False):
        uploaded = st.file_uploader(
            "导入角色目标 YAML",
            type=["yaml", "yml"],
            key=f"upload_character_target_{game.id}_{character.id}",
        )
        if uploaded is not None:
            content = uploaded.getvalue()
            digest = hashlib.sha256(content).hexdigest()
            if st.session_state.get(digest_key) != digest:
                try:
                    _metadata, imported_character = load_character_target_yaml_text(
                        content.decode("utf-8")
                    )
                    if imported_character.game != game.id:
                        st.error(
                            f"导入目标属于 {imported_character.game}，当前选择的是 {game.id}。"
                        )
                    else:
                        merged_character = _merge_imported_character_target(
                            character,
                            imported_character,
                        )
                        validate_character_against_game(merged_character, game)
                        st.session_state[state_key] = merged_character
                        st.session_state[digest_key] = digest
                        st.success("已导入角色目标配置。")
                        st.rerun()
                except Exception as exc:
                    st.error(f"导入失败：{exc}")
            else:
                st.caption("当前上传的角色目标 YAML 已导入。")

        if state_key in st.session_state:
            st.caption("当前正在使用导入的目标配置覆盖本角色模板。")
            if st.button(
                "清除导入目标",
                key=f"clear_character_target_{game.id}_{character.id}",
            ):
                del st.session_state[state_key]
                st.session_state.pop(digest_key, None)
                st.rerun()

    return active_character


def _probability_model_import_state_key(game, model) -> str:
    return f"probability_model_import::{game.id}::{model.id}"


def _probability_model_import_digest_key(game, model) -> str:
    return f"probability_model_digest::{game.id}::{model.id}"


def _probability_model_version(game, model) -> str:
    digest = str(st.session_state.get(_probability_model_import_digest_key(game, model)) or "")
    return digest[:12] if digest else "base"


def _render_probability_model_import_controls(game, model):
    state_key = _probability_model_import_state_key(game, model)
    digest_key = _probability_model_import_digest_key(game, model)
    active_model = st.session_state.get(state_key, model)

    with st.sidebar.expander("概率模型 YAML", expanded=False):
        uploaded = st.file_uploader(
            "导入概率模型 YAML",
            type=["yaml", "yml"],
            key=f"upload_probability_model_{game.id}_{model.id}",
        )
        if uploaded is not None:
            content = uploaded.getvalue()
            digest = hashlib.sha256(content).hexdigest()
            if st.session_state.get(digest_key) != digest:
                try:
                    _metadata, imported_model = load_probability_model_yaml_text(
                        content.decode("utf-8")
                    )
                    if imported_model.game != game.id:
                        st.error(
                            f"导入概率模型属于 {imported_model.game}，当前选择的是 {game.id}。"
                        )
                    else:
                        st.session_state[state_key] = imported_model
                        st.session_state[digest_key] = digest
                        st.success("已导入概率模型。")
                        st.rerun()
                except Exception as exc:
                    st.error(f"导入失败：{exc}")
            else:
                st.caption("当前上传的概率模型 YAML 已导入。")

        if state_key in st.session_state:
            st.caption("当前正在使用导入的概率模型覆盖本配置。")
            if st.button(
                "清除导入概率模型",
                key=f"clear_probability_model_{game.id}_{model.id}",
            ):
                del st.session_state[state_key]
                st.session_state.pop(digest_key, None)
                st.rerun()

    return active_model


def _render_probability_model_parameter_controls(game, model):
    version = _probability_model_version(game, model)
    with st.sidebar.expander("概率模型参数", expanded=False):
        st.info(
            "这些是假设参数，会直接影响调律策略的候选概率和资源期望。"
            "绝区零指定套装调律时，目标套装概率按 100% 处理。"
        )
        st.table(
            pd.DataFrame(
                [
                    {
                        "参数": "目标套装概率",
                        "怎么理解": "指定套装调律为 100%；只有随机掉落或跨套装估算才低于 100%。",
                    },
                    {
                        "参数": "母盘/随机位置尝试",
                        "怎么理解": "不锁位置，靠 1/6 位置随机命中目标位，消耗较低。",
                    },
                    {
                        "参数": "母盘/固定位置尝试",
                        "怎么理解": "锁定位置，母盘消耗更高，用来跳过位置随机。",
                    },
                    {
                        "参数": "校音器/固定主属性尝试",
                        "怎么理解": "只锁主属性，不锁副属性；短期和长期冲突时优先留给长期目标。",
                    },
                    {
                        "参数": "共鸣核/固定副属性尝试",
                        "怎么理解": "锁 1-2 个副属性，默认最稀有，不作为常规补弱路径。",
                    },
                ]
            )
        )
        target_set_probability = st.slider(
            "目标套装概率",
            min_value=0.0,
            max_value=1.0,
            value=float(model.target_set_probability),
            step=0.01,
            format="%.2f",
            key=f"prob_target_set_{game.id}_{model.id}_{version}",
        )
        three_line_probability = st.slider(
            "初始 3 词条概率",
            min_value=0.0,
            max_value=1.0,
            value=float(model.initial_substat_count_probabilities.get("3", 0.8)),
            step=0.01,
            format="%.2f",
            key=f"prob_initial_3_{game.id}_{model.id}_{version}",
        )
        st.caption(f"初始 4 词条概率：{1.0 - three_line_probability:.0%}")

        resource_labels = {
            "mother_disk_random_position_attempt": "母盘/随机位置尝试",
            "mother_disk_fixed_position_attempt": "母盘/固定位置尝试",
            "tuner_per_fixed_main_attempt": "校音器/固定主属性尝试",
            "core_per_fixed_substat_attempt": "共鸣核/固定副属性尝试",
        }
        resource_defaults = {
            "mother_disk_random_position_attempt": 3.0,
            "mother_disk_fixed_position_attempt": 6.0,
            "tuner_per_fixed_main_attempt": 1.0,
            "core_per_fixed_substat_attempt": 1.0,
        }
        resource_costs: dict[str, float] = {}
        for key, label in resource_labels.items():
            resource_costs[key] = float(
                st.number_input(
                    label,
                    min_value=0.0,
                    max_value=999.0,
                    value=float(model.resource_cost(key, resource_defaults[key])),
                    step=0.1,
                    format="%.1f",
                    key=f"prob_resource_{key}_{game.id}_{model.id}_{version}",
                )
            )

    updated_model = model.model_copy(
        update={
            "target_set_probability": float(target_set_probability),
            "initial_substat_count_probabilities": {
                "3": float(three_line_probability),
                "4": float(1.0 - three_line_probability),
            },
            "resource_costs": resource_costs,
        }
    )
    with st.sidebar.expander("概率模型导出", expanded=False):
        st.download_button(
            "导出当前概率模型",
            data=probability_model_yaml(updated_model),
            file_name=(
                f"{_safe_filename(game.id)}_"
                f"{_safe_filename(updated_model.id)}_probability.yaml"
            ),
            mime="application/x-yaml",
            key=f"download_probability_model_{game.id}_{model.id}",
        )
    return updated_model


def _character_with_plan(character, plan: SetPlan, target_set: str | None = None):
    return character.model_copy(
        update={
            "target_set": target_set or character.target_set,
            "set_plans": [plan],
            "default_set_plan": plan.id,
        }
    )


def _target_set_from_plan(plan: SetPlan, fallback: str) -> str:
    if plan.requirements:
        return plan.requirements[0].primary_set
    return fallback


def _first_valid_set(game, candidates: list[str], excluded: set[str] | None = None) -> str:
    excluded = excluded or set()
    for set_name in candidates:
        if set_name in game.sets and set_name not in excluded:
            return set_name
    for set_name in game.sets:
        if set_name not in excluded:
            return set_name
    return game.sets[0]


def _active_plan_structure(character) -> str:
    active_plan = character.active_set_plan()
    if active_plan is None or active_plan.is_unrestricted:
        return "不限套装"
    pieces = sorted([requirement.pieces for requirement in active_plan.requirements], reverse=True)
    if pieces == [4, 2]:
        return "4+2"
    if pieces == [2, 2, 2]:
        return "2+2+2"
    return "4+2"


def _four_two_defaults(game, character) -> tuple[str, str]:
    active_plan = character.active_set_plan()
    core_set = _first_valid_set(game, [character.target_set])
    pair_set = _first_valid_set(game, [], {core_set})
    if active_plan and not active_plan.is_unrestricted:
        for requirement in active_plan.requirements:
            if requirement.pieces == 4:
                core_set = _first_valid_set(game, requirement.set_names)
                break
        for requirement in active_plan.requirements:
            if requirement.pieces == 2:
                pair_set = _first_valid_set(game, requirement.set_names, {core_set})
                break
    return core_set, pair_set


def _two_two_two_defaults(game, character) -> list[str]:
    active_plan = character.active_set_plan()
    defaults: list[str] = []
    if active_plan and not active_plan.is_unrestricted:
        for requirement in active_plan.requirements:
            if requirement.pieces == 2:
                defaults.append(_first_valid_set(game, requirement.set_names, set(defaults)))
    if not defaults:
        defaults.append(_first_valid_set(game, [character.target_set]))
    while len(defaults) < 3:
        defaults.append(_first_valid_set(game, [], set(defaults)))
    return defaults[:3]


def _render_set_plan_target_controls(game, character):
    structure_options = ["4+2", "2+2+2", "不限套装"]
    default_structure = _active_plan_structure(character)
    with st.sidebar.expander("目标套装方案", expanded=True):
        structure = _selectbox(
            st,
            "目标结构",
            structure_options,
            default_structure,
            key=_character_control_key(game, character, "target_plan_structure"),
        )
        st.caption("这里只选择目标组合；先补哪一段、哪一号位由当前盘面自动排序。")

        if structure == "不限套装":
            plan = SetPlan(id="ui_unrestricted", name="不限套装", requirements=[])
            _render_set_plan_effect_preview(game, plan)
            return _character_with_plan(character, plan, character.target_set)

        if structure == "2+2+2":
            defaults = _two_two_two_defaults(game, character)
            first_set = _selectbox(
                st,
                "二件套 A",
                game.sets,
                defaults[0],
                key=_character_control_key(game, character, "target_2p_a"),
            )
            second_options = [set_name for set_name in game.sets if set_name != first_set] or game.sets
            second_set = _selectbox(
                st,
                "二件套 B",
                second_options,
                defaults[1] if defaults[1] in second_options else second_options[0],
                key=_character_control_key(game, character, "target_2p_b"),
            )
            third_options = [
                set_name for set_name in game.sets if set_name not in {first_set, second_set}
            ] or game.sets
            third_set = _selectbox(
                st,
                "二件套 C",
                third_options,
                defaults[2] if defaults[2] in third_options else third_options[0],
                key=_character_control_key(game, character, "target_2p_c"),
            )
            pair_sets = [first_set, second_set, third_set]
            plan = SetPlan(
                id="ui_target_2_2_2",
                name=" + ".join(f"{set_name} 2" for set_name in pair_sets),
                requirements=[
                    SetRequirement(role=f"pair{index}", set_name=set_name, pieces=2)
                    for index, set_name in enumerate(pair_sets, start=1)
                ],
            )
            _render_set_plan_effect_preview(game, plan)
            return _character_with_plan(character, plan, first_set)

        core_default, pair_default = _four_two_defaults(game, character)
        core_set = _selectbox(
            st,
            "4 件套",
            game.sets,
            core_default,
            key=_character_control_key(game, character, "target_4p_set"),
        )
        pair_options = [set_name for set_name in game.sets if set_name != core_set] or game.sets
        pair_set = _selectbox(
            st,
            "2 件套",
            pair_options,
            pair_default if pair_default in pair_options else pair_options[0],
            key=_character_control_key(game, character, "target_2p_set"),
        )
        plan = SetPlan(
            id="ui_target_4_2",
            name=f"{core_set} 4 + {pair_set} 2",
            requirements=[
                SetRequirement(role="core4", set_name=core_set, pieces=4),
                SetRequirement(role="pair2", set_name=pair_set, pieces=2),
            ],
        )
        _render_set_plan_effect_preview(game, plan)
        return _character_with_plan(character, plan, core_set)


def _render_main_stat_target_controls(game, character):
    preferred_main_stats: dict[str, list[str]] = {}
    with st.sidebar.expander("主属性倾向", expanded=False):
        for rule in game.positions:
            options = list(rule.main_stats)
            current = [
                stat
                for stat in character.preferred_mains_for(rule.id)
                if stat in options
            ]
            if len(options) <= 1 and not current:
                st.caption(f"{rule.name}：{options[0] if options else '-'}")
                continue
            values = st.multiselect(
                rule.name,
                options,
                default=current,
                key=_character_control_key(
                    game,
                    character,
                    f"preferred_main_{position_key(rule.id)}",
                ),
            )
            if values:
                preferred_main_stats[position_key(rule.id)] = values
    return character.model_copy(update={"preferred_main_stats": preferred_main_stats})


def _render_target_score_controls(game, character):
    thresholds = character.rating_thresholds
    usable_default = float(thresholds.get("usable", 2.0))
    good_default = max(float(thresholds.get("good", 4.0)), usable_default)
    excellent_default = max(float(thresholds.get("excellent", 6.0)), good_default)
    with st.sidebar.expander("评分目标", expanded=False):
        st.info(
            "高级可选项：普通使用不必改；优先配置套装方案、主属性倾向和副词条优先级。"
            "这里不是伤害模拟，只是工具内部的观察线。"
        )
        st.table(
            pd.DataFrame(
                [
                    {
                        "参数": "有效词条目标线",
                        "是否必须": "否，默认即可",
                        "影响": "候选胚子是否达到有效词条观察线。",
                    },
                    {
                        "参数": "质量分目标线",
                        "是否必须": "否，默认即可",
                        "影响": "按副词条优先级顺序观察质量，用于补弱和让位排序。",
                    },
                    {
                        "参数": "评级线",
                        "是否必须": "否，默认即可",
                        "影响": "只改变 weak / usable / good / excellent 的显示分界。",
                    },
                ]
            )
        )
        st.caption("想更激进或更保守时再改；看不懂就直接保持角色模板默认。")
        effective_key = _character_control_key(game, character, "target_effective_rolls")
        weighted_key = _character_control_key(game, character, "target_weighted_score")
        usable_key = _character_control_key(game, character, "rating_usable")
        good_key = _character_control_key(game, character, "rating_good")
        excellent_key = _character_control_key(game, character, "rating_excellent")
        if st.button(
            "恢复角色模板评分目标",
            key=_character_control_key(game, character, "reset_target_score"),
        ):
            st.session_state[effective_key] = float(character.target_effective_rolls)
            st.session_state[weighted_key] = float(character.weighted_target_score)
            st.session_state[usable_key] = usable_default
            st.session_state[good_key] = good_default
            st.session_state[excellent_key] = excellent_default
            st.rerun()
        effective_target = _float_number_input(
            st,
            "有效词条目标线",
            key=effective_key,
            value=float(character.target_effective_rolls),
            step=0.1,
            format="%.1f",
        )
        weighted_target = _float_number_input(
            st,
            "质量分目标线",
            key=weighted_key,
            value=float(character.weighted_target_score),
            step=0.1,
            format="%.1f",
        )
        st.caption(
            "评级线只决定 weak / usable / good / excellent 的显示分界，"
            "并自动保持 usable <= good <= excellent。"
        )
        usable_threshold = _float_number_input(
            st,
            "usable 评级线",
            key=usable_key,
            value=usable_default,
            step=0.1,
            format="%.1f",
        )
        good_threshold = _float_number_input(
            st,
            "good 评级线",
            key=good_key,
            value=good_default,
            minimum=usable_threshold,
            step=0.1,
            format="%.1f",
        )
        excellent_threshold = _float_number_input(
            st,
            "excellent 评级线",
            key=excellent_key,
            value=excellent_default,
            minimum=good_threshold,
            step=0.1,
            format="%.1f",
        )
    return character.model_copy(
        update={
            "target_effective_rolls": float(effective_target),
            "target_weighted_score": float(weighted_target),
            "rating_thresholds": {
                "usable": float(usable_threshold),
                "good": float(good_threshold),
                "excellent": float(excellent_threshold),
            },
        }
    )


def _render_substat_weight_controls(game, character):
    core_default, usable_default = _priority_groups_from_effective_substats(character)
    with st.sidebar.expander("副词条优先级", expanded=False):
        st.info("只需要按顺序选择副词条，不需要填写小数。")
        st.caption("内部直接按核心/可用顺位排序，不再填写或显示副词条小数系数。")
        core_key = _character_control_key(game, character, "substat_priority_core")
        usable_key = _character_control_key(game, character, "substat_priority_usable")
        if core_key in st.session_state:
            st.session_state[core_key] = [
                stat for stat in st.session_state[core_key] if stat in game.sub_stats
            ]
        core_stats = st.multiselect(
            "核心副词条（从左到右优先）",
            game.sub_stats,
            default=[stat for stat in core_default if stat in game.sub_stats],
            key=core_key,
        )
        usable_options = [stat for stat in game.sub_stats if stat not in set(core_stats)]
        if usable_key in st.session_state:
            st.session_state[usable_key] = [
                stat for stat in st.session_state[usable_key] if stat in usable_options
            ]
        usable_stats = st.multiselect(
            "可用/过渡副词条（从左到右优先）",
            usable_options,
            default=[stat for stat in usable_default if stat in usable_options],
            key=usable_key,
        )
        effective_substats = _markers_from_priority_groups(core_stats, usable_stats)
        if not effective_substats:
            st.warning("至少保留一个有效副词条。")
            effective_substats = dict(character.effective_substats)
        st.write("当前优先级预览")
        st.table(_substat_priority_preview_frame(core_stats, usable_stats))
    return character.model_copy(
        update={
            "effective_substats": effective_substats,
            "substat_priority": SubstatPriority(core=core_stats, usable=usable_stats),
        }
    )


def _render_editor_validation_warnings(warnings: list[str]) -> None:
    if not warnings:
        return
    unique_warnings = list(dict.fromkeys(warnings))
    st.warning(f"当前盘面有 {len(unique_warnings)} 条输入已自动校验，请展开查看详情。")
    with st.expander("查看校验详情", expanded=False):
        for warning in unique_warnings:
            st.caption(warning)


def _current_state_key(game, character) -> str:
    return f"current_piece_state::{game.id}::{character.id}"


def _current_import_digest_key(game, character) -> str:
    return f"current_import_digest::{game.id}::{character.id}"


def _current_editor_revision_key(game, character) -> str:
    return f"current_editor_revision::{game.id}::{character.id}"


def _current_editor_version(game, character) -> str:
    digest = str(st.session_state.get(_current_import_digest_key(game, character)) or "")
    revision = int(st.session_state.get(_current_editor_revision_key(game, character), 0))
    base = digest[:12] if digest else "base"
    return f"{base}_{revision}" if revision else base


def _bump_current_editor_revision(game, character) -> None:
    key = _current_editor_revision_key(game, character)
    st.session_state[key] = int(st.session_state.get(key, 0)) + 1


def _current_piece_key_prefix(game, character, piece_key: str) -> str:
    return f"current_{piece_key}_{_current_editor_version(game, character)}"


def _ensure_current_state(game, character) -> dict[str, dict]:
    state_key = _current_state_key(game, character)
    position_keys = [position_key(rule.id) for rule in game.positions]
    if state_key not in st.session_state:
        st.session_state[state_key] = {
            position_key(piece.position): _piece_state(piece)
            for piece in _default_current_pieces(game, character)
        }
    state = st.session_state[state_key]
    for rule in game.positions:
        key = position_key(rule.id)
        if key not in state:
            state[key] = _piece_state(
                GearPiece(
                    position=rule.id,
                    set_name=character.target_set,
                    main_stat=rule.main_stats[0],
                    level=0,
                    substats=[],
                )
            )
    for key in list(state):
        if key not in position_keys:
            del state[key]
    return state


def _apply_current_pieces_to_state(game, character, pieces: list[GearPiece]) -> None:
    state = _ensure_current_state(game, character)
    valid_positions = {position_key(rule.id): rule for rule in game.positions}
    for piece in pieces:
        key = position_key(piece.position)
        if key not in valid_positions:
            continue
        if "initial_substat_count" in piece.model_fields_set:
            initial_count = piece.initial_substat_count
        else:
            initial_count = 4 if len(piece.substats) >= 4 else 3
        state[key] = _piece_state(piece, initial_count=initial_count)


def _replace_current_pieces_state(game, character, pieces: list[GearPiece]) -> None:
    st.session_state[_current_state_key(game, character)] = {}
    _apply_current_pieces_to_state(game, character, pieces)
    _bump_current_editor_revision(game, character)


def _current_gear_save_check_rows(game, character, pieces: list[GearPiece]) -> tuple[list[dict[str, str]], bool]:
    expected_keys = [position_key(rule.id) for rule in game.positions]
    actual_keys = [position_key(piece.position) for piece in pieces]
    missing_keys = [key for key in expected_keys if key not in actual_keys]
    duplicate_keys = sorted({key for key in actual_keys if actual_keys.count(key) > 1})

    rows: list[dict[str, str]] = []
    if missing_keys:
        missing_names = "、".join(
            game.position_name(rule.id)
            for rule in game.positions
            if position_key(rule.id) in missing_keys
        )
        rows.append(
            {
                "检查项": "盘面完整度",
                "状态": "需补齐",
                "说明": f"保存模板需要每个位置都有一件盘；缺少 {missing_names}。",
            }
        )
    elif duplicate_keys:
        duplicate_names = "、".join(
            game.position_name(rule.id)
            for rule in game.positions
            if position_key(rule.id) in duplicate_keys
        )
        rows.append(
            {
                "检查项": "盘面完整度",
                "状态": "需修正",
                "说明": f"存在重复位置：{duplicate_names}。",
            }
        )
    else:
        rows.append(
            {
                "检查项": "盘面完整度",
                "状态": "通过",
                "说明": f"已识别 {len(pieces)} 件装备。",
            }
        )

    try:
        validate_current_gear_against_game(pieces, game, require_complete=True)
    except Exception as exc:
        rows.append(
            {
                "检查项": "等级 / roll / 词条",
                "状态": "需修正",
                "说明": str(exc),
            }
        )
        can_save = False
    else:
        rows.append(
            {
                "检查项": "等级 / roll / 词条",
                "状态": "通过",
                "说明": "等级、可见副词条、roll 总数和主副属性互斥均通过。",
            }
        )
        can_save = not missing_keys and not duplicate_keys

    rows.append(
        {
            "检查项": "保存位置",
            "状态": "本机用户数据",
            "说明": str(current_gear_store_path(game.id, character.id)),
        }
    )
    return rows, can_save


def _current_gear_status_frame(
    game,
    character,
    pieces: list[GearPiece],
    warnings: list[str],
) -> pd.DataFrame:
    save_check_rows, can_save = _current_gear_save_check_rows(game, character, pieces)
    expected_count = len(game.positions)
    actual_keys = [position_key(piece.position) for piece in pieces]
    unique_count = len(set(actual_keys))
    unique_warnings = list(dict.fromkeys(warnings))
    check_notes = {
        row["检查项"]: row
        for row in save_check_rows
    }
    roll_check = check_notes.get("等级 / roll / 词条")

    save_note = "可在盘面模板中保存为当前角色盘面。"
    if unique_warnings:
        save_note = "可保存；建议先展开校验详情确认自动修正是否符合预期。"
    if not can_save:
        save_note = "展开盘面模板查看保存前检查，并按提示修正。"

    rows = [
        {
            "项目": "保存就绪",
            "状态": "可保存" if can_save else "暂不可保存",
            "说明": save_note,
        },
        {
            "项目": "盘面完整度",
            "状态": f"{unique_count}/{expected_count}",
            "说明": "六个位置已齐全。" if unique_count == expected_count else "有位置缺失或重复。",
        },
        {
            "项目": "自动校验",
            "状态": f"{len(unique_warnings)} 条自动修正" if unique_warnings else "无自动修正",
            "说明": "页面下方可展开查看详情。" if unique_warnings else "当前输入没有被系统改写。",
        },
        {
            "项目": "等级 / roll 约束",
            "状态": roll_check["状态"] if roll_check else "-",
            "说明": roll_check["说明"] if roll_check else "按游戏规则限制等级、可见词条和强化次数。",
        },
        {
            "项目": "保存路径",
            "状态": "本机用户数据",
            "说明": str(current_gear_store_path(game.id, character.id)),
        },
    ]
    return pd.DataFrame(rows)


def _render_current_save_controls(game, character, pieces: list[GearPiece]) -> None:
    save_check_rows, can_save_template = _current_gear_save_check_rows(
        game,
        character,
        pieces,
    )
    st.write("保存当前盘面")
    st.caption("盘位编辑会实时写入当前会话；确认保存就绪后，在这里保存为当前角色的本机盘面模板。")
    save_cols = st.columns([1.8, 0.9])
    save_label = save_cols[0].text_input(
        "盘面模板名称",
        value=f"{character.name} 当前盘面",
        key=f"save_current_template_name_{game.id}_{character.id}",
    )
    if save_cols[1].button(
        "保存当前盘面",
        key=f"save_current_template_{game.id}_{character.id}",
        disabled=not can_save_template,
        use_container_width=True,
    ):
        try:
            validate_current_gear_against_game(pieces, game, require_complete=True)
            saved = save_user_current_gear(
                game.id,
                character.id,
                pieces,
                save_label,
            )
            st.success(f"校验通过，已保存：{saved['label']}")
            st.rerun()
        except Exception as exc:
            st.error(f"保存失败：{exc}")
    if not can_save_template:
        st.warning("当前盘面暂不能保存，请展开盘面模板查看保存前检查。")
    with st.expander("保存前检查", expanded=False):
        st.table(pd.DataFrame(save_check_rows))


def _render_current_source_controls(game, character, pieces: list[GearPiece]) -> None:
    examples = list_current_examples(game.id, character.id)
    saved_templates = load_user_current_gears(game.id, character.id)
    with st.expander("盘面模板", expanded=False):
        template_options: dict[str, tuple[str, object]] = {
            f"内置：{item['label']}": ("example", item["path"])
            for item in examples
        }
        template_options.update(
            {
                f"已保存：{item['label']}": ("saved", item)
                for item in saved_templates
            }
        )
        if template_options:
            selected_label = st.selectbox(
                "当前装备示例",
                list(template_options),
                key=f"current_example_{game.id}_{character.id}",
            )
            cols = st.columns(3)
            if cols[0].button(
                "载入示例盘面",
                key=f"load_current_example_{game.id}_{character.id}",
            ):
                source_type, source = template_options[selected_label]
                if source_type == "example":
                    loaded_pieces = load_current_example(str(source))
                else:
                    loaded_pieces = list(source["pieces"])  # type: ignore[index]
                validate_current_gear_against_game(loaded_pieces, game)
                _replace_current_pieces_state(game, character, loaded_pieces)
                st.success(f"校验通过，已载入 {len(loaded_pieces)} 件：{selected_label}")
                st.rerun()
            if cols[1].button(
                "清空为手动输入",
                key=f"blank_current_{game.id}_{character.id}",
            ):
                _replace_current_pieces_state(
                    game,
                    character,
                    _blank_current_pieces(game, character),
                )
                st.success("已清空当前盘面。")
                st.rerun()
            selected_type, selected_source = template_options[selected_label]
            if selected_type == "saved":
                if cols[2].button(
                    "删除已保存盘面",
                    key=f"delete_current_template_{game.id}_{character.id}",
                ):
                    deleted = delete_user_current_gear(
                        game.id,
                        character.id,
                        selected_source["id"],  # type: ignore[index]
                    )
                    if deleted:
                        st.success(f"已删除：{selected_source['label']}")  # type: ignore[index]
                        st.rerun()
                    st.warning("没有找到可删除的本地盘面。")
            else:
                cols[2].caption("内置盘面不可删除")
        else:
            st.caption("当前游戏暂无内置或已保存盘面模板。")
            if st.button(
                "清空为手动输入",
                key=f"blank_current_{game.id}_{character.id}",
            ):
                _replace_current_pieces_state(
                    game,
                    character,
                    _blank_current_pieces(game, character),
                )
                st.success("已清空当前盘面。")
                st.rerun()

        st.divider()
        st.caption("保存会写入本机 user_data，不会改内置 examples；保存入口在盘面状态摘要下方。")
        save_check_rows, can_save_template = _current_gear_save_check_rows(
            game,
            character,
            pieces,
        )
        st.write("保存前检查")
        st.table(pd.DataFrame(save_check_rows))
        if not can_save_template:
            st.warning("当前盘面暂不能保存模板，请先按检查项修正。")


def _state_to_piece(item: dict, game) -> GearPiece:
    visible_slots = _visible_substat_slots(game, item["level"], item["initial_count"])
    rows = [
        (line.get("stat", ""), int(line.get("rolls", 0)))
        for line in item.get("substats", [])[:visible_slots]
    ]
    substats, _warnings = _safe_substats(
        rows,
        game.position_name(item["position"]),
        item["main_stat"],
    )
    return GearPiece(
        position=item["position"],
        set_name=item["set_name"],
        main_stat=item["main_stat"],
        level=item["level"],
        locked=bool(item.get("locked", False)),
        initial_substat_count=item.get("initial_count", 4),
        substats=substats,
    )


def _inventory_state_key(game, character) -> str:
    return f"inventory_state::{game.id}::{character.id}"


def _inventory_counter_key(game, character) -> str:
    return f"inventory_counter::{game.id}::{character.id}"


def _inventory_import_digest_key(game, character) -> str:
    return f"inventory_import_digest::{game.id}::{character.id}"


def _inventory_item_key_prefix(game, character, item_id: str) -> str:
    return f"inventory_{game.id}_{character.id}_{item_id}"


def _next_inventory_item_id(game, character) -> str:
    key = _inventory_counter_key(game, character)
    st.session_state[key] = int(st.session_state.get(key, 0)) + 1
    return f"item_{st.session_state[key]}"


def _inventory_piece_state(piece: GearPiece, item_id: str) -> dict:
    state = _piece_state(piece)
    state["id"] = item_id
    return state


def _default_inventory_piece(game, character) -> GearPiece:
    preferred_positions = list(character.preferred_main_stats)
    target_position = preferred_positions[0] if preferred_positions else position_key(game.positions[0].id)
    if target_position not in {position_key(rule.id) for rule in game.positions}:
        target_position = position_key(game.positions[0].id)
    rule = game.position(target_position)
    preferred_mains = character.preferred_mains_for(target_position)
    main_stat = (
        preferred_mains[0]
        if preferred_mains and preferred_mains[0] in rule.main_stats
        else rule.main_stats[0]
    )
    available = game.available_substats(main_stat)
    substats = [
        SubstatLine(stat=stat, rolls=0)
        for stat in _effective_substats_by_priority(character, exclude=main_stat)
        if stat in available
    ][:3]
    return GearPiece(
        position=rule.id,
        set_name=character.target_set,
        main_stat=main_stat,
        level=0,
        initial_substat_count=3,
        substats=substats,
    )


def _ensure_inventory_state(game, character) -> list[dict]:
    key = _inventory_state_key(game, character)
    if key not in st.session_state:
        pieces = load_user_inventory(game.id, character.id)
        st.session_state[key] = [
            _inventory_piece_state(piece, f"saved_{index}")
            for index, piece in enumerate(pieces, start=1)
        ]
        st.session_state[_inventory_counter_key(game, character)] = len(pieces)
    return st.session_state[key]


def _replace_inventory_state(game, character, pieces: list[GearPiece]) -> None:
    st.session_state[_inventory_state_key(game, character)] = [
        _inventory_piece_state(piece, f"imported_{index}_{hashlib.sha1(piece.model_dump_json().encode('utf-8')).hexdigest()[:8]}")
        for index, piece in enumerate(pieces, start=1)
    ]
    st.session_state[_inventory_counter_key(game, character)] = len(pieces)


def _inventory_piece_summary_frame(
    game,
    character,
    pieces: list[GearPiece],
) -> pd.DataFrame:
    rows = []
    for index, piece in enumerate(pieces, start=1):
        effective_lines, effective_rolls, quality_score = _piece_preview_values(
            piece.substats,
            character,
        )
        rows.append(
            {
                "#": index,
                "位置": game.position_name(piece.position),
                "套装": piece.set_name,
                "主属性": piece.main_stat,
                "等级": f"+{piece.level}",
                "初始词条": piece.initial_substat_count,
                "副属性": _substat_effective_label(piece.substats),
                "有效词条": effective_rolls,
                "质量分": quality_score,
                "状态": "成品" if piece.level >= game.enhancement.max_level else "胚子",
            }
        )
    return pd.DataFrame(rows)


def _render_inventory_piece_controls(game, character, item: dict, index: int) -> tuple[GearPiece | None, list[str]]:
    item_id = str(item.get("id") or f"item_{index}")
    key_prefix = _inventory_item_key_prefix(game, character, item_id)
    warnings: list[str] = []

    position_options = [rule.id for rule in game.positions]
    position_labels = {rule.id: rule.name for rule in game.positions}
    selected_position = _selectbox(
        st,
        "位置",
        position_options,
        item.get("position") if item.get("position") in position_options else position_options[0],
        key=f"{key_prefix}_position",
        format_func=lambda value: position_labels[value],
    )
    rule = game.position(selected_position)

    cols = st.columns(4)
    set_name = _selectbox(
        cols[0],
        "套装",
        _set_options_for_character(game, character, item.get("set_name")),
        item.get("set_name"),
        key=f"{key_prefix}_set",
    )
    main_stat = _selectbox(
        cols[1],
        "主属性",
        list(dict.fromkeys(rule.main_stats + [item.get("main_stat", rule.main_stats[0])])),
        item.get("main_stat", rule.main_stats[0]),
        key=f"{key_prefix}_main",
    )
    level = _selectbox(
        cols[2],
        "等级",
        [0, 3, 6, 9, 12, 15],
        item.get("level", 0),
        key=f"{key_prefix}_level",
    )
    initial_count = _selectbox(
        cols[3],
        "初始词条数",
        [3, 4],
        item.get("initial_count", 3),
        key=f"{key_prefix}_initial",
    )

    substat_rows, used_rolls, max_rolls, input_warnings = _render_substat_inputs(
        game,
        main_stat,
        item.get("substats", [{"stat": "", "rolls": 0} for _ in range(4)]),
        level,
        initial_count,
        key_prefix,
        f"库存 {index}",
    )
    substats, row_warnings = _safe_substats(substat_rows, f"库存 {index}", main_stat)
    warnings.extend(input_warnings)
    warnings.extend(row_warnings)

    item.update(
        {
            "id": item_id,
            "position": selected_position,
            "set_name": set_name,
            "main_stat": main_stat,
            "level": level,
            "locked": False,
            "initial_count": initial_count,
            "substats": [{"stat": line.stat, "rolls": line.rolls} for line in substats]
            + [{"stat": "", "rolls": 0} for _ in range(4 - len(substats))],
        }
    )

    try:
        piece = _state_to_piece(item, game)
        validate_gear_piece_against_game(piece, game)
    except Exception as exc:
        warnings.append(f"库存 {index} 暂不能纳入计算：{exc}")
        piece = None

    visible_slots = _visible_substat_slots(game, level, initial_count)
    st.table(
        _piece_edit_status_frame(
            visible_slots,
            used_rolls,
            max_rolls,
            substats,
            warnings,
        )
    )
    return piece, warnings


def _render_inventory_manager(game, character) -> tuple[list[GearPiece], list[str]]:
    state = _ensure_inventory_state(game, character)
    warnings: list[str] = []
    valid_pieces: list[GearPiece] = []

    st.info(
        "库存维护不用手写 YAML：当前装备页只管角色身上的 6 件；这里添加背包里没穿的成品或胚子，"
        "保存后调律策略会自动把它们纳入理论期望。"
    )
    with st.expander("背包库存（点这里添加未装备盘）", expanded=not state):
        st.table(
            pd.DataFrame(
                [
                    {"步骤": "1", "你要做什么": "点“添加库存件”"},
                    {"步骤": "2", "你要做什么": "选择位置、套装、主属性、等级和副属性"},
                    {"步骤": "3", "你要做什么": "点“保存库存到本机”"},
                    {"步骤": "4", "你要做什么": "回到攻略结论，库存会自动参与 EV"},
                ]
            )
        )
        st.caption("YAML 只是备份和迁移入口；正常使用不需要打开文本手动编辑。")
        st.caption(f"本机保存路径：{user_inventory_store_path(game.id, character.id)}")

        control_cols = st.columns([1, 1, 1, 1])
        if control_cols[0].button(
            "添加库存件",
            key=f"add_inventory_piece_{game.id}_{character.id}",
            use_container_width=True,
        ):
            state.append(
                _inventory_piece_state(
                    _default_inventory_piece(game, character),
                    _next_inventory_item_id(game, character),
                )
            )
        if control_cols[1].button(
            "清空库存",
            key=f"clear_inventory_{game.id}_{character.id}",
            disabled=not state,
            use_container_width=True,
        ):
            state.clear()
            st.rerun()

        uploaded = st.file_uploader(
            "导入库存备份 YAML（可选）",
            type=["yaml", "yml"],
            key=f"visual_inventory_upload_{game.id}_{character.id}",
            help="导入后会变成上面的可视化库存项，之后仍然可以点开逐件编辑。",
        )
        if uploaded is not None:
            try:
                text = uploaded.read().decode("utf-8")
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if st.session_state.get(_inventory_import_digest_key(game, character)) != digest:
                    _metadata, imported_pieces = load_current_yaml_text(text)
                    for piece in imported_pieces:
                        validate_gear_piece_against_game(piece, game)
                    _replace_inventory_state(game, character, imported_pieces)
                    st.session_state[_inventory_import_digest_key(game, character)] = digest
                    st.success(f"已导入库存 {len(imported_pieces)} 件。")
                    st.rerun()
            except Exception as exc:
                st.error(f"库存 YAML 导入失败：{exc}")

        if not state:
            st.info("库存为空。只有当前 6 件装备会参与 EV；有未装备好盘或胚子时，点“添加库存件”。")
        for index, item in enumerate(list(state), start=1):
            title = (
                f"库存 {index}：{game.position_name(item.get('position'))} "
                f"{item.get('set_name', '-') } {item.get('main_stat', '-') } +{item.get('level', 0)}"
            )
            with st.expander(title, expanded=index == len(state)):
                piece, item_warnings = _render_inventory_piece_controls(game, character, item, index)
                warnings.extend(item_warnings)
                if piece is not None:
                    valid_pieces.append(piece)
                if st.button(
                    "删除这件",
                    key=f"delete_inventory_{game.id}_{character.id}_{item.get('id', index)}",
                ):
                    state.remove(item)
                    st.rerun()

        if valid_pieces:
            st.write("当前库存摘要")
            st.dataframe(
                _inventory_piece_summary_frame(game, character, valid_pieces),
                use_container_width=True,
                hide_index=True,
            )

        save_cols = st.columns([1, 1])
        if save_cols[0].button(
            "保存库存到本机",
            key=f"save_inventory_{game.id}_{character.id}",
            use_container_width=True,
        ):
            path = save_user_inventory(game.id, character.id, valid_pieces)
            st.success(f"已保存 {len(valid_pieces)} 件库存：{path}")
        save_cols[1].download_button(
            "导出库存 YAML",
            current_gear_yaml(
                game.id,
                character.id,
                valid_pieces,
                label=f"{character.name} 库存",
            ),
            file_name=f"{_safe_filename(character.id)}_inventory.yaml",
            mime="text/yaml",
            use_container_width=True,
        )

    return valid_pieces, warnings


def _local_asset_path(relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    path = Path(relative_path)
    if not path.is_absolute():
        path = ROOT / path
    return path if path.exists() else None


def _set_icon_path(game, set_name: str) -> Path | None:
    icon_path = None
    resolver = getattr(game, "set_icon_path", None)
    if callable(resolver):
        icon_path = resolver(set_name)
    else:
        icon_path = getattr(game, "set_icons", {}).get(set_name)
    return _local_asset_path(icon_path)


def _set_effect_for(game, set_name: str):
    resolver = getattr(game, "set_effect", None)
    if callable(resolver):
        return resolver(set_name)
    return getattr(game, "set_effects", {}).get(set_name)


@st.cache_data(show_spinner=False)
def _asset_data_uri(path_text: str) -> str:
    path = Path(path_text)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _tile_tone(rating: str) -> tuple[str, str]:
    tones = {
        "weak": ("rgba(127, 29, 29, 0.62)", "rgba(15, 23, 42, 0.88)"),
        "usable": ("rgba(113, 63, 18, 0.58)", "rgba(15, 23, 42, 0.88)"),
        "good": ("rgba(20, 83, 45, 0.55)", "rgba(15, 23, 42, 0.88)"),
        "excellent": ("rgba(30, 64, 175, 0.58)", "rgba(15, 23, 42, 0.88)"),
    }
    return tones.get(rating, ("rgba(30, 41, 59, 0.68)", "rgba(2, 6, 23, 0.88)"))


def _render_piece_tile_background(tile_key: str, icon_path: Path | None, rating: str) -> None:
    if not icon_path:
        return
    top, bottom = _tile_tone(rating)
    data_uri = _asset_data_uri(str(icon_path))
    st.markdown(
        f"""
        <style>
        [class*="st-key-{tile_key}"] button {{
          background-image:
            linear-gradient(180deg, rgba(2, 6, 23, 0.16), rgba(2, 6, 23, 0.58) 46%, {bottom}),
            linear-gradient(145deg, {top}, {bottom}),
            url("{data_uri}") !important;
          background-size: cover, cover, var(--gear-tile-icon-size) !important;
          background-position: center, center, center 0.45rem !important;
          background-repeat: no-repeat !important;
          padding-top: var(--gear-tile-image-padding) !important;
          text-shadow: 0 1px 2px rgba(0, 0, 0, 0.72);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_set_effect_card(container, game, set_name: str) -> None:
    effect = _set_effect_for(game, set_name)
    icon_path = _set_icon_path(game, set_name)
    with container.container(key=f"set_effect_card_{game.id}_{_safe_filename(set_name)}"):
        cols = st.columns([0.28, 1.0])
        with cols[0]:
            if icon_path:
                st.image(str(icon_path), use_container_width=True)
            else:
                st.markdown(
                    f"<div class='fallback-set-icon small'>{set_name[:2]}</div>",
                    unsafe_allow_html=True,
                )
        with cols[1]:
            st.markdown(f"**{set_name}**")
            if effect:
                st.caption(f"2件：{effect.two_piece or '暂无配置'}")
                st.caption(f"4件：{effect.four_piece or '暂无配置'}")
            else:
                st.caption("暂无 2/4 件套效果配置。")


def _render_set_plan_effect_preview(game, plan: SetPlan | None) -> None:
    with st.sidebar.expander("套装效果预览", expanded=True):
        if plan is None or plan.is_unrestricted:
            st.caption("当前方案不限制套装，调律策略会按位置、主属性和副词条质量判断。")
            return

        shown: set[str] = set()
        for requirement in plan.requirements:
            st.caption(f"目标：{_set_requirement_config_label(requirement)}")
            for set_name in requirement.set_names:
                if set_name in shown:
                    continue
                _render_set_effect_card(st, game, set_name)
                shown.add(set_name)


def _position_target_row(set_plan, key: str) -> dict | None:
    if not set_plan:
        return None
    for row in set_plan.get("position_targets", []):
        if position_key(row["position"]) == key:
            return row
    return None


def _slot_plan_badge(row: dict | None) -> str:
    if not row:
        return "保留"
    status = row.get("status", "")
    stage = row.get("stage", "")
    if status == "建议让位":
        return "让位2件" if "2" in stage else "让位4件"
    if status == "候补让位":
        return "候补让位"
    if status == "规划保留":
        return "保留4件" if "4" in stage else "保留2件"
    if status == "锁定保留":
        return "锁定保留"
    if status == "锁定冲突":
        return "锁定冲突"
    if status == "质量优化":
        return "质量优化"
    return status or "保留"


def _slot_plan_token(row: dict | None) -> str:
    if not row:
        return "plan_keep"
    status = row.get("status")
    if status == "建议让位":
        return "plan_yield"
    if status == "候补让位":
        return "plan_candidate"
    if status == "锁定冲突":
        return "plan_conflict"
    if status == "质量优化":
        return "plan_quality"
    return "plan_keep"


def _piece_card_label(rule, score, set_plan, is_weakest: bool = False) -> str:
    rating = score.rating if score else "weak"
    rating_label = {
        "weak": "弱",
        "usable": "可用",
        "good": "良好",
        "excellent": "优秀",
    }.get(rating, rating)
    rolls = f"{score.effective_rolls:g}" if score else "0"
    main_stat = score.main_stat if score else "-"
    level = score.level if score else 0
    main_badge = "主准" if not score or score.main_stat_preferred else "主偏"
    weakness = " 最弱" if is_weakest else ""
    main_label = _short_stat_label(main_stat)
    return (
        f"{rule.name}{weakness}\n"
        f"{rating_label} · {rolls}有效\n"
        f"{main_badge} {main_label}+{level}"
    )


def _is_weakest_position(analysis, key: str) -> bool:
    return (
        analysis.weakest_position is not None
        and position_key(analysis.weakest_position) == key
    )


def _set_replacement_token(set_plan, key: str) -> str:
    if not set_plan:
        return "set_keep"
    badge = set_plan["position_pressures"].get(key, {}).get("replacement_badge", "保留")
    if badge == "优先替换":
        return "set_priority"
    if badge == "可替换":
        return "set_replaceable"
    return "set_keep"


def _piece_tile_key(game, key: str, score, analysis) -> str:
    rating = score.rating if score else "weak"
    priority = "priority_weakest" if _is_weakest_position(analysis, key) else "priority_normal"
    main = "main_ok" if not score or score.main_stat_preferred else "main_miss"
    set_token = _set_replacement_token(analysis.set_plan, key)
    plan_token = _slot_plan_token(_position_target_row(analysis.set_plan, key))
    return f"gear_tile_{game.id}_{key}_rating_{rating}_{priority}_{main}_{set_token}_{plan_token}"


def _piece_overview_frame(score, set_plan, key: str) -> pd.DataFrame:
    if score is None:
        return pd.DataFrame()
    pressure = set_plan["position_pressures"].get(key, {}) if set_plan else {}
    target_row = _position_target_row(set_plan, key)
    rows = [
        {
            "项目": "套装",
            "当前值": score.set_name,
        },
        {
            "项目": "规划目标",
            "当前值": target_row["target_group"] if target_row else "未配置",
        },
        {
            "项目": "规划动作",
            "当前值": target_row["action"] if target_row else "按词条补弱",
        },
        {
            "项目": "规划状态",
            "当前值": target_row["status"] if target_row else "未配置",
        },
        {
            "项目": "评级",
            "当前值": score.rating,
        },
        {
            "项目": "有效/质量",
            "当前值": f"{score.effective_rolls:g} / {score.weighted_score:g}",
        },
        {
            "项目": "替换标签",
            "当前值": pressure.get("replacement_badge", "保留"),
        },
        {
            "项目": "保留锁定",
            "当前值": "是" if score.locked else "否",
        },
    ]
    if target_row:
        rows.append({"项目": "规划依据", "当前值": target_row["reason"]})
    return pd.DataFrame(rows)


def _board_set_stage_label(analysis) -> str:
    if not analysis.set_plan:
        return "按词条补弱"
    if analysis.set_plan["is_unrestricted"]:
        return "不限套装"
    if not analysis.set_plan.get("feasible_with_locks", True):
        return "锁定冲突"
    if analysis.set_plan["satisfied"]:
        return "套装达标"
    missing = analysis.set_plan.get("missing", [])
    if not missing:
        return "接近达标"
    target = missing[0]
    pieces = target.get("required", 0)
    role = target.get("role", "")
    prefix = "先补4件" if pieces >= 4 or str(role).startswith("core") else "先补2件"
    target_label = target.get("label") or target.get("set_name") or "-"
    return f"{prefix} · {target_label}"


def _render_board_center_panel(column, analysis) -> None:
    locked_count = sum(1 for score in analysis.scores if score.locked)
    weakest = analysis.weakest_position_name or "-"
    set_stage = _board_set_stage_label(analysis)
    column.markdown(
        f"""
        <div class="gear-board-center">
          <div class="gear-board-center-title">盘面状态</div>
          <div class="gear-board-center-main">{weakest}</div>
          <div class="gear-board-center-line">{set_stage}</div>
          <div class="gear-board-center-line">锁定 {locked_count} 件</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_piece_controls(game, character, state: dict[str, dict], rule) -> list[str]:
    key = position_key(rule.id)
    item = state[key]
    control_prefix = _current_piece_key_prefix(game, character, key)
    warnings: list[str] = []

    st.markdown(f"**{rule.name}**")
    cols = st.columns([1.2, 1.2, 0.8, 0.8])
    set_options = _set_options_for_character(game, character, item["set_name"])
    set_name = _selectbox(
        cols[0],
        "套装",
        set_options,
        item["set_name"],
        key=f"{control_prefix}_set",
    )
    main_options = list(dict.fromkeys(rule.main_stats + [item["main_stat"]]))
    main_stat = _selectbox(
        cols[1],
        "主属性",
        main_options,
        item["main_stat"],
        key=f"{control_prefix}_main",
    )
    level = _selectbox(
        cols[2],
        "等级",
        [0, 3, 6, 9, 12, 15],
        item["level"],
        key=f"{control_prefix}_level",
    )
    initial_count = _selectbox(
        cols[3],
        "初始词条数",
        [3, 4],
        item.get("initial_count", 4),
        key=f"{control_prefix}_initial",
    )
    locked = st.checkbox(
        "保留此盘，不参与套装让位和当前调律优先级",
        value=bool(item.get("locked", False)),
        key=f"{control_prefix}_locked",
    )

    substat_rows, used_rolls, max_rolls, input_warnings = _render_substat_inputs(
        game,
        main_stat,
        item.get("substats", [{"stat": "", "rolls": 0} for _ in range(4)]),
        level,
        initial_count,
        control_prefix,
        rule.name,
    )
    visible_slots = _visible_substat_slots(game, level, initial_count)
    st.caption(
        f"+{level} / 初始 {initial_count} 词条：可见 {visible_slots} 条副属性，"
        f"最多 {max_rolls} 次强化命中，已分配 {used_rolls} 次。"
    )

    substats, row_warnings = _safe_substats(substat_rows, rule.name, main_stat)
    warnings.extend(input_warnings)
    warnings.extend(row_warnings)
    local_warnings = input_warnings + row_warnings
    remaining_rolls = max(max_rolls - used_rolls, 0)
    effective_line_count, effective_roll_count, quality_score = _piece_preview_values(
        substats,
        character,
    )
    feedback_cols = st.columns(3)
    feedback_cols[0].metric("有效词条", f"{effective_roll_count:g}", f"{effective_line_count} 条")
    feedback_cols[1].metric("质量分", f"{quality_score:g}")
    feedback_cols[2].metric(
        "roll 预算",
        f"{used_rolls}/{max_rolls}",
        "已用满" if remaining_rolls == 0 else f"剩 {remaining_rolls}",
    )
    st.caption(
        f"当前编辑预览：{effective_line_count} 条有效副属性，"
        f"{effective_roll_count:g} 次有效词条，{quality_score:g} 质量分。"
    )
    st.caption(
        "roll 预算按等级和初始词条数自动限制；修改后会实时写入当前会话并重新校验，"
        "长期复用请保存当前盘面。"
    )
    st.write("编辑状态")
    st.table(
        _piece_edit_status_frame(
            visible_slots,
            used_rolls,
            max_rolls,
            substats,
            local_warnings,
        )
    )
    if local_warnings:
        st.warning(f"本盘有 {len(local_warnings)} 条输入已自动校验，页面下方可展开查看详情。")
    state[key] = {
        "position": rule.id,
        "set_name": set_name,
        "main_stat": main_stat,
        "level": level,
        "locked": locked,
        "initial_count": initial_count,
        "substats": [{"stat": line.stat, "rolls": line.rolls} for line in substats]
        + [{"stat": "", "rolls": 0} for _ in range(4 - len(substats))],
    }
    return warnings


def _render_piece_board(game, character, state: dict[str, dict], analysis) -> list[str]:
    warnings: list[str] = []
    score_by_position = {position_key(score.position): score for score in analysis.scores}
    rule_by_key = {position_key(rule.id): rule for rule in game.positions}
    layout = board_layout_for_game(game)
    center_slot = board_center_slot(layout)

    with st.container(key=f"gear_board_shell_{game.id}"):
        for row_index, row in enumerate(layout):
            cols = st.columns(len(row), gap="small")
            for column_index, (column, key) in enumerate(zip(cols, row)):
                if key is None:
                    if center_slot == (row_index, column_index):
                        _render_board_center_panel(column, analysis)
                    else:
                        column.markdown("<div class='gear-board-spacer'></div>", unsafe_allow_html=True)
                    continue
                rule = rule_by_key[key]
                score = score_by_position.get(key)
                is_weakest = _is_weakest_position(analysis, key)
                tile_key = _piece_tile_key(game, key, score, analysis)
                with column.container(key=tile_key):
                    set_name = score.set_name if score else state[key]["set_name"]
                    icon_path = _set_icon_path(game, set_name)
                    _render_piece_tile_background(
                        tile_key,
                        icon_path,
                        score.rating if score else "weak",
                    )
                    with st.popover(
                        _piece_card_label(rule, score, analysis.set_plan, is_weakest),
                        use_container_width=True,
                    ):
                        overview = _piece_overview_frame(score, analysis.set_plan, key)
                        if not overview.empty:
                            st.table(overview)
                        warnings.extend(_render_piece_controls(game, character, state, rule))
    return warnings


def _render_substat_inputs(
    game,
    main_stat: str,
    rows: list[dict],
    level: int,
    initial_count: int,
    key_prefix: str,
    context_label: str | None = None,
) -> tuple[list[tuple[str, int]], int, int, list[str]]:
    visible_slots = _visible_substat_slots(game, level, initial_count)
    max_rolls = _max_rolls_at_level(game, level, initial_count)
    substat_rows: list[tuple[str, int]] = []
    chosen_stats: list[str] = []
    used_rolls = 0
    warnings: list[str] = []
    label_prefix = context_label or key_prefix

    for index in range(4):
        line = rows[index] if index < len(rows) else {"stat": "", "rolls": 0}
        disabled = index >= visible_slots
        original_stat = str(line.get("stat", "") or "")
        original_rolls = int(line.get("rolls", 0) or 0)
        cols = st.columns([1.8, 0.8])
        options = _substat_options(
            game,
            main_stat,
            original_stat,
            chosen_stats,
        )
        stat = _selectbox(
            cols[0],
            f"副属性 {index + 1}",
            options,
            original_stat if not disabled else "",
            key=f"{key_prefix}_sub_{index}",
            disabled=disabled,
        )
        if disabled:
            if original_stat or original_rolls:
                warnings.append(
                    f"{label_prefix} 副属性 {index + 1} 当前等级不可见，已暂不计入分析。"
                )
            rolls = 0
        else:
            max_for_line = max_rolls - used_rolls
            roll_key = f"{key_prefix}_roll_{index}"
            raw_rolls = int(st.session_state.get(roll_key, original_rolls) or 0)
            if raw_rolls > max_for_line:
                warnings.append(
                    f"{label_prefix} 副属性 {index + 1} roll 次数超出剩余预算，"
                    f"已限制为 {max_for_line}。"
                )
            if not stat and raw_rolls > 0:
                warnings.append(
                    f"{label_prefix} 副属性 {index + 1} 未选择词条，roll 次数已清零。"
                )
            rolls = _number_input(
                cols[1],
                "roll 次数",
                roll_key,
                original_rolls,
                max_for_line if stat else 0,
                disabled=not stat,
            )
            used_rolls += rolls
            if stat:
                chosen_stats.append(stat)
                substat_rows.append((stat, rolls))

    return substat_rows, used_rolls, max_rolls, warnings


def _render_current_editor(game, character) -> tuple[list[GearPiece], list[str]]:
    state = _ensure_current_state(game, character)
    pieces_before_edit = [
        _state_to_piece(state[position_key(rule.id)], game)
        for rule in game.positions
    ]
    analysis_before_edit = analyse_current_gear(pieces_before_edit, game, character)
    warnings = _render_piece_board(game, character, state, analysis_before_edit)

    pieces = [
        _state_to_piece(state[position_key(rule.id)], game)
        for rule in game.positions
    ]

    return pieces, warnings


def _candidate_import_state_key(game, character) -> str:
    return f"candidate_import::{game.id}::{character.id}"


def _candidate_import_digest_key(game, character) -> str:
    return f"candidate_import_digest::{game.id}::{character.id}"


def _candidate_editor_key_prefix(game, character, case: str, imported: bool) -> str:
    base = f"candidate_{game.id}_{case}"
    if not imported:
        return base
    digest = str(st.session_state.get(_candidate_import_digest_key(game, character)) or "")
    version = digest[:12] if digest else "imported"
    return f"{base}_{version}"


def _default_candidate_for_game(game, character) -> CandidatePiece:
    preferred_positions = list(character.preferred_main_stats)
    target_position = preferred_positions[0] if preferred_positions else position_key(game.positions[0].id)
    if target_position not in {position_key(rule.id) for rule in game.positions}:
        target_position = position_key(game.positions[0].id)
    position_rule = game.position(target_position)
    preferred_mains = character.preferred_mains_for(target_position)
    main_stat = (
        preferred_mains[0]
        if preferred_mains and preferred_mains[0] in position_rule.main_stats
        else position_rule.main_stats[0]
    )
    available = game.available_substats(main_stat)
    substats = [
        SubstatLine(stat=stat, rolls=0)
        for stat in _effective_substats_by_priority(character, exclude=main_stat)
        if stat in available
    ][:3]
    if len(substats) < 3:
        selected = {line.stat for line in substats}
        for stat in available:
            if stat not in selected:
                substats.append(SubstatLine(stat=stat, rolls=0))
                selected.add(stat)
            if len(substats) == 3:
                break
    return CandidatePiece(
        position=position_rule.id,
        set_name=character.target_set,
        main_stat=main_stat,
        initial_substat_count=3,
        level=0,
        substats=substats,
    )


def _render_candidate_editor(game, character) -> tuple[CandidatePiece, list[str]]:
    imported_default = st.session_state.get(_candidate_import_state_key(game, character))
    examples = list_candidate_examples(game.id)
    example_options = {"手动输入": None} | {
        item["label"]: item["path"]
        for item in examples
    }
    case = st.selectbox(
        "候选示例",
        list(example_options),
        key=f"candidate_case_{game.id}",
    )
    example_path = example_options[case]
    uses_imported_default = imported_default is not None and not example_path
    if uses_imported_default:
        default = imported_default
    elif example_path:
        default = load_candidate_example(example_path)
        validate_candidate_against_game(default, game)
    else:
        default = _default_candidate_for_game(game, character)
    if position_key(default.position) not in {position_key(rule.id) for rule in game.positions}:
        default = _default_candidate_for_game(game, character)

    position_options = [rule.id for rule in game.positions]
    position_labels = {rule.id: rule.name for rule in game.positions}
    key_prefix = _candidate_editor_key_prefix(
        game,
        character,
        case,
        uses_imported_default,
    )
    selected_position = _selectbox(
        st,
        "位置",
        position_options,
        default.position if default.position in position_options else position_options[0],
        key=f"{key_prefix}_position",
        format_func=lambda item: position_labels[item],
    )
    position_rule = game.position(selected_position)

    cols = st.columns(4)
    set_options = _set_options_for_character(game, character, default.set_name)
    set_name = _selectbox(
        cols[0],
        "套装",
        set_options,
        default.set_name,
        key=f"{key_prefix}_set",
    )
    main_options = list(dict.fromkeys(position_rule.main_stats + [default.main_stat]))
    main_stat = _selectbox(
        cols[1],
        "主属性",
        main_options,
        default.main_stat,
        key=f"{key_prefix}_main",
    )
    initial_count = _selectbox(
        cols[2],
        "初始词条数",
        [3, 4],
        default.initial_substat_count,
        key=f"{key_prefix}_initial",
    )
    level = _selectbox(
        cols[3],
        "当前等级",
        [0, 3, 6, 9, 12, 15],
        default.level,
        key=f"{key_prefix}_level",
    )

    rows = [
        {"stat": line.stat, "rolls": line.rolls}
        for line in default.substats[:4]
    ]
    rows += [{"stat": "", "rolls": 0} for _ in range(4 - len(rows))]
    substat_rows, used_rolls, max_rolls, input_warnings = _render_substat_inputs(
        game,
        main_stat,
        rows,
        level,
        initial_count,
        key_prefix,
        "候选胚子",
    )
    visible_slots = _visible_substat_slots(game, level, initial_count)
    st.caption(
        f"当前 +{level} / 初始 {initial_count} 词条：可见 {visible_slots} 条副属性，"
        f"最多 {max_rolls} 次强化命中，已分配 {used_rolls} 次。"
    )

    substats, warnings = _safe_substats(substat_rows, "候选胚子", main_stat)
    warnings = input_warnings + warnings
    st.write("编辑状态")
    st.table(
        _piece_edit_status_frame(
            visible_slots,
            used_rolls,
            max_rolls,
            substats,
            warnings,
        )
    )
    return (
        CandidatePiece(
            position=selected_position,
            set_name=set_name,
            main_stat=main_stat,
            level=level,
            initial_substat_count=initial_count,
            substats=substats,
        ),
        warnings,
    )


def _set_plan_status_text(analysis) -> str:
    return shared_set_plan_status_text(analysis)


def _set_requirement_label(item: dict) -> str:
    label = item.get("label", item["set_name"])
    if item.get("set_names"):
        return f"{label}（当前按 {item['set_name']}）"
    return label


def _recommended_strategy_set(analysis, character, target_position) -> str:
    if analysis.set_plan and not analysis.set_plan["is_unrestricted"]:
        if analysis.set_plan["missing"]:
            missing = analysis.set_plan["missing"][0]
            return _set_group_label(missing.get("set_names") or [missing["set_name"]])
        target_sets = set(analysis.set_plan["target_sets"])
        for score in analysis.scores:
            if position_key(score.position) == position_key(target_position):
                if score.set_name in target_sets:
                    return score.set_name
        if analysis.set_plan["target_sets"]:
            return analysis.set_plan["target_sets"][0]
    return character.target_set


def _scores_frame(analysis) -> pd.DataFrame:
    def detail_label(score) -> str:
        values = []
        for detail in score.substat_details:
            total_rolls = detail["total_rolls"]
            if detail["priority"] == "无效":
                values.append(f"{detail['stat']}({detail['priority']})")
            else:
                rank = detail.get("priority_rank")
                rank_text = f"#{rank}" if rank else ""
                values.append(
                    f"{detail['stat']} {total_rolls:g}次·{detail['priority']}{rank_text}"
                )
        return "；".join(values)

    return pd.DataFrame(
        [
            {
                "位置": score.position_name,
                "套装": score.set_name,
                "主属性": score.main_stat,
                "等级": score.level,
                "保留锁定": "是" if score.locked else "否",
                "有效副词条数": score.effective_lines,
                "有效词条次数": score.effective_rolls,
                "质量分": score.weighted_score,
                "副词条明细": detail_label(score),
                "套装替换压力": (
                    analysis.set_plan["position_pressures"][position_key(score.position)][
                        "replacement_pressure"
                    ]
                    if analysis.set_plan
                    else 0.0
                ),
                "替换标签": (
                    analysis.set_plan["position_pressures"][position_key(score.position)][
                        "replacement_badge"
                    ]
                    if analysis.set_plan
                    else "保留"
                ),
                "评级": score.rating,
                "主属性匹配": "是" if score.main_stat_preferred else "否",
                "套装方案匹配": "是" if score.set_plan_preferred else "否",
            }
            for score in analysis.scores
        ]
    )


def _set_action_label(score, pressure: dict, set_plan: dict) -> str:
    if set_plan.get("is_unrestricted"):
        return "不限套装"
    if pressure.get("locked") or score.locked:
        return "已锁定"
    if pressure["replacement_badge"] == "优先替换":
        return "优先让位"
    if pressure["replaceable_for_set_plan"]:
        if score.rating in {"good", "excellent"}:
            return "可让位但谨慎"
        return "可让位"
    return "保留"


def _set_plan_action_frame(analysis) -> pd.DataFrame:
    if not analysis.set_plan:
        return pd.DataFrame()
    pressure_by_position = analysis.set_plan["position_pressures"]
    rows = []
    for score in analysis.scores:
        pressure = pressure_by_position[position_key(score.position)]
        rows.append(
            {
                "位置": score.position_name,
                "当前套装": pressure["current_set"],
                "目标套装": pressure["target_set"] or "已满足",
                "盘面质量": score.rating,
                "质量分": score.weighted_score,
                "判断": _set_action_label(score, pressure, analysis.set_plan),
                "让位压力": pressure["replacement_pressure"],
                "原因": pressure["reason"],
            }
        )
    return pd.DataFrame(rows)


def _set_plan_stage_frame(game, analysis) -> pd.DataFrame:
    rows = set_plan_stage_rows(game, analysis)
    return pd.DataFrame(
        [
            {
                "顺序": row["order"],
                "阶段": row["stage"],
                "目标": row["target"],
                "进度": row["progress"],
                "缺口": row["missing"],
                "排序分": row["priority_score"],
                "算法依据": row["algorithm_basis"],
                "当前动作": row["action"],
                "推荐让位": row["replacement"],
                "依据": row["basis"],
            }
            for row in rows
        ]
    )


def _action_rows_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "顺序": row["order"],
                "行动": row["action"],
                "入口": row.get("entry", "调律策略比较 -> 全局调律推荐"),
                "目标": row["target"],
                "调律范围": row["tuning_scope"],
                "资源提示": row["resource_hint"],
                "原因": row["reason"],
            }
            for row in rows
        ]
    )


def _today_action_summary_frame(
    game,
    character,
    candidate,
    result,
    analysis,
    current_best,
    long_term_best,
    tuner_best,
    core_best,
) -> pd.DataFrame:
    return pd.DataFrame(
        today_action_summary_rows(
            game,
            character,
            candidate,
            result,
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
        )
    )


def _resource_guardrail_frame(current_best, long_term_best, tuner_best, core_best) -> pd.DataFrame:
    return pd.DataFrame(
        resource_guardrail_rows(current_best, long_term_best, tuner_best, core_best)
    )


def _probability_breakdown_label(row) -> str:
    breakdown = row.probability_breakdown or {}
    options = getattr(row, "target_set_options", None) or [row.target_set]
    set_note = (
        f"套装 {breakdown.get('set', 0.0):.1%}"
        if len(options) <= 1
        else f"套装 {breakdown.get('set', 0.0):.1%}（{len(options)} 个可接受套装合并）"
    )
    return (
        f"{set_note} × "
        f"位置 {breakdown.get('position', 0.0):.1%} × "
        f"主属性 {breakdown.get('main_stat', 0.0):.1%} × "
        f"副属性 {breakdown.get('substats', 0.0):.1%}"
    )


def _target_set_options_label(row) -> str:
    options = getattr(row, "target_set_options", None) or [row.target_set]
    return " / ".join(options)


def _set_probability_source_label(row) -> str:
    options = getattr(row, "target_set_options", None) or [row.target_set]
    set_probability = row.probability_breakdown.get("set", 0.0)
    if len(options) <= 1:
        return f"单套装 {set_probability:.1%}"
    return f"{len(options)} 个可接受套装合并，套装概率 {set_probability:.1%}"


def _strategy_resource_scope_label(row) -> str:
    if row.expected_cores > 0:
        return "固定副属性才消耗共鸣核；不属于普通固定主属性路径"
    if row.expected_tuners > 0:
        return "固定主属性只消耗校音器；不消耗共鸣核"
    return "只消耗母盘；不使用校音器或共鸣核"


def _strategy_decision_role_label(label: str, row) -> str:
    if row.expected_cores > 0:
        return "极限毕业观察，默认保留共鸣核"
    if label == "当前相对提升最优":
        return "当前补弱路径"
    if label == "长期绝对最优":
        return "长期目标路径"
    if label.startswith("校音器"):
        return "只评估固定主属性是否值得"
    return "观察项"


def _strategy_frame(rows) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "策略名称": row.strategy_name,
                "目标套装": row.target_set,
                "可接受套装": _target_set_options_label(row),
                "目标位置": row.target_position_name,
                "目标主属性": row.target_main_stat,
                "是否固定位置": "是" if row.fixed_position else "否",
                "是否固定主属性": "是" if row.fixed_main_stat else "否",
                "固定副属性": "、".join(row.fixed_substats) if row.fixed_substats else "不固定",
                "副属性优先级": fixed_substat_note(row),
                "套装概率": row.probability_breakdown.get("set", 0.0),
                "套装概率来源": _set_probability_source_label(row),
                "位置概率": row.probability_breakdown.get("position", 0.0),
                "主属性概率": row.probability_breakdown.get("main_stat", 0.0),
                "副属性概率": row.probability_breakdown.get("substats", 0.0),
                "候选概率": row.candidate_probability,
                "期望母盘消耗": row.expected_mother_disks,
                "期望校音器消耗": row.expected_tuners,
                "期望共鸣核消耗": row.expected_cores,
                "长期价值评分": row.long_term_value_score,
                "当前相对提升评分": row.current_relative_gain_score,
                "推荐倾向": row.recommendation,
            }
            for row in rows
        ]
    )


def _ratio_label(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}x"


def _strategy_cost_ladder_frame(rows) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "阶梯": item["stage"],
                "策略名称": item["strategy_name"],
                "锁定范围": item["locked_scope"],
                "可接受套装": item["target_set_scope"],
                "套装概率来源": item["set_probability_source"],
                "候选概率": item["candidate_probability"],
                "期望母盘": item["expected_mother_disks"],
                "期望校音器": item["expected_tuners"],
                "期望共鸣核": item["expected_cores"],
                "固定副词条依据": item["fixed_substat_note"],
                "母盘相对上一档": _ratio_label(
                    item["mother_disk_multiplier_vs_previous"]
                ),
                "概率相对上一档": _ratio_label(
                    item["probability_multiplier_vs_previous"]
                ),
                "增量解释": item["incremental_note"],
            }
            for item in strategy_cost_ladder(rows)
        ]
    )


def _probability_model_assumption_frame(probability_model) -> pd.DataFrame:
    return pd.DataFrame(probability_model_assumption_rows(probability_model))


def _position_strategy_efficiency_frame(
    game,
    character,
    probability_model,
    analysis,
    inventory_pieces: list[GearPiece] | None = None,
) -> pd.DataFrame:
    return pd.DataFrame(
        _visible_action_ev_rows(
            position_strategy_efficiency_rows(
                game,
                character,
                probability_model,
                analysis,
                inventory_pieces=inventory_pieces,
            )
        )
    ).astype(str)


def _visible_action_ev_rows(rows: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in row.items() if not str(key).startswith("_")}
        for row in rows
    ]


def _model_payload(item):
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return item
    return str(item)


def _strategy_exact_input_digest(
    game,
    character,
    probability_model,
    inventory_pieces: list[GearPiece],
    horizon: int,
) -> str:
    payload = {
        "game": _model_payload(game),
        "character": _model_payload(character),
        "probability_model": _model_payload(probability_model),
        "horizon": horizon,
        "inventory": [_model_payload(piece) for piece in inventory_pieces],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _strategy_loadout_result_key(game, character) -> str:
    return f"strategy_best_loadout::{game.id}::{character.id}"


def _strategy_action_ev_result_key(game, character) -> str:
    return f"strategy_action_ev::{game.id}::{character.id}"


def _source_label(source: str | None) -> str:
    return {
        "current": "当前装备",
        "inventory": "背包库存",
        "outcome": "新结果",
    }.get(str(source or "inventory"), "背包库存")


def _best_loadout_display_frame(game, character, rows: list[dict]) -> pd.DataFrame:
    display_rows = []
    for index, row in enumerate(rows, start=1):
        piece = row.get("_piece")
        level = piece.level if isinstance(piece, GearPiece) else row.get("level", "-")
        main_stat = piece.main_stat if isinstance(piece, GearPiece) else row.get("main_stat", "-")
        substats = piece.substats if isinstance(piece, GearPiece) else []
        display_rows.append(
            {
                "#": index,
                "位置": game.position_name(row["position"]),
                "来源": _source_label(row.get("source")),
                "套装": row["set_name"],
                "主属性": main_stat,
                "等级": f"+{level}" if isinstance(level, int) else level,
                "状态": "成品"
                if isinstance(level, int) and level >= game.enhancement.max_level
                else "胚子",
                "副属性": _substat_effective_label(substats) if substats else "-",
                "有效词条": round(float(row.get("effective_rolls", 0.0)), 3),
                "质量分": round(float(row.get("quality_score", 0.0)), 3),
                "排序向量": " / ".join(f"{float(value):g}" for value in row.get("quality_vector", ()))
                or "-",
            }
        )
    return pd.DataFrame(display_rows)


def _exact_progress_callback(title: str):
    progress = st.progress(0.0, text=f"{title}：准备中")
    detail = st.empty()
    state = {"last_update": 0.0}

    def callback(event: dict[str, object]) -> None:
        event_name = str(event.get("event", ""))
        now = time.monotonic()
        if (
            now - float(state["last_update"]) < 0.12
            and event_name not in {"start", "unit_start", "unit_done", "complete", "cache_hit"}
        ):
            return
        state["last_update"] = now

        total = float(event.get("total") or 0)
        completed = float(event.get("completed") or 0)
        fraction = 1.0 if event_name in {"complete", "cache_hit"} else 0.0
        if total > 0:
            fraction = min(max(completed / total, 0.0), 1.0)

        label = str(event.get("label") or "")
        unit_label = str(event.get("unit_label") or "")
        spec_index = event.get("spec_index")
        spec_total = event.get("spec_total")
        prefix = f"{title}：{fraction:.0%}"
        if spec_index and spec_total:
            prefix += f"｜action {spec_index}/{spec_total}"
        if unit_label:
            prefix += f"｜{unit_label}"
        if label:
            prefix += f"｜{label}"

        progress.progress(fraction, text=prefix)
        dp_states = int(event.get("dp_states") or 0)
        memo_hits = int(event.get("memo_hits") or 0)
        detail.caption(f"已完成 DP 状态：{dp_states}；缓存命中：{memo_hits}。")

    return callback


def _fixed_main_gain_ladder_frame(game, character, probability_model, analysis) -> pd.DataFrame:
    return pd.DataFrame(
        fixed_main_gain_ladder_rows(game, character, probability_model, analysis)
    ).astype(str)


def _fixed_substat_gain_ladder_frame(game, character, probability_model, analysis) -> pd.DataFrame:
    return pd.DataFrame(
        fixed_substat_gain_ladder_rows(game, character, probability_model, analysis)
    ).astype(str)


def _resource_marginal_ev_frame(
    game,
    character,
    probability_model,
    analysis,
    inventory_pieces: list[GearPiece] | None = None,
    horizon: int = 1,
    progress_callback=None,
) -> pd.DataFrame:
    return pd.DataFrame(
        resource_marginal_ev_rows(
            game,
            character,
            probability_model,
            analysis,
            inventory_pieces=inventory_pieces,
            horizon=horizon,
            progress_callback=progress_callback,
        )
    ).astype(str)


def _initial_substat_tier_frame(game, character, probability_model, analysis) -> pd.DataFrame:
    return pd.DataFrame(
        initial_substat_tier_rows(game, character, probability_model, analysis)
    ).astype(str)


def _strategy_context_frame(game, character, probability_model, analysis) -> pd.DataFrame:
    return pd.DataFrame(
        strategy_context_rows(game, character, probability_model, analysis)
    )


def _strategy_brief(row) -> str:
    return shared_strategy_brief(row, include_resources=True)


def _first_sentence(text: str) -> str:
    if not text:
        return "-"
    sentence = str(text).split("。", 1)[0].strip()
    return f"{sentence}。" if sentence else str(text)


def _compact_resource_action(tuner_text: str, core_text: str) -> str:
    tuner_hold = any(word in tuner_text for word in ["先别急", "先攒", "暂无"])
    core_hold = any(word in core_text for word in ["先留", "保留", "暂无"])
    tuner_action = "校音器先留" if tuner_hold else "校音器可观察"
    core_action = "共鸣核先留" if core_hold else "共鸣核只看极限毕业"
    return f"{tuner_action}；{core_action}"


def _action_ev_guide_text(action_ev_rows: list[dict]) -> tuple[str, str]:
    row = recommended_action_ev_row(action_ev_rows)
    if row is None:
        return "暂无母盘 action", "缺少概率模型或当前盘面。"
    target = f"{row['目标套装']} {row['位置']}"
    action = "固定位置" if row.get("策略") == "固定位置" else "随机位置"
    reason = (
        f"排序向量/母盘 {row.get('排序向量/母盘', '-')}，有效/母盘 {row['有效/母盘']}；"
        f"{row['相对随机']}。"
    )
    return f"{action}：{target}", reason


def _strategy_guide_frame(
    action_ev_rows: list[dict],
    analysis,
    current_best,
    long_term_best,
    tuner_best,
    core_best,
) -> pd.DataFrame:
    ev_action, ev_reason = _action_ev_guide_text(action_ev_rows)
    tuner_text, core_text = resource_decision_text(tuner_best, core_best, long_term_best)
    return pd.DataFrame(
        [
            {
                "优先级": "1",
                "主题": "母盘",
                "行动": ev_action,
                "理由": ev_reason,
            },
            {
                "优先级": "2",
                "主题": "当前补弱",
                "行动": f"{analysis.weakest_position_name or '-'} 最弱",
                "理由": f"最弱：{analysis.weakest_position_name or '-'}；只看当前盘面最容易补强的位置。",
            },
            {
                "优先级": "3",
                "主题": "特殊资源",
                "行动": _compact_resource_action(tuner_text, core_text),
                "理由": f"{_first_sentence(tuner_text)} {_first_sentence(core_text)}",
            },
            {
                "优先级": "4",
                "主题": "长期目标",
                "行动": _strategy_brief(long_term_best),
                "理由": _first_sentence(strategy_alignment_text(current_best, long_term_best)),
            },
        ]
    )


def _current_conclusion_frame(
    analysis,
    current_best,
    long_term_best,
    tuner_best,
    core_best,
) -> pd.DataFrame:
    return pd.DataFrame(
        current_gear_conclusion_rows(
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
            include_strategy_resources=True,
        )
    )


def _conclusion_by_question(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["问题"]: row for row in rows}


def _current_acceptance_frame(
    analysis,
    current_best,
    long_term_best,
    tuner_best,
    core_best,
    action_ev_rows: list[dict] | None = None,
) -> pd.DataFrame:
    rows = current_gear_conclusion_rows(
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
        include_strategy_resources=True,
    )
    by_question = _conclusion_by_question(rows)
    items = [
        ("我当前 6 件盘哪件最差？", "当前哪件最弱", "看当前装备评分和柱状图。"),
        ("这个新胚子还值不值得强化？", None, "切到候选胚子评估页，看候选验收速览。"),
        ("现在应该固定几号位？", "现在优先固定/刷哪里", "看调律策略比较的全局推荐和随机 vs 固定位置表。"),
        ("校音器该不该用？", "校音器该不该用", "只对应固定主属性，先看是否和长期目标一致。"),
        ("共鸣核该不该留？", "共鸣核该不该留", "只对应固定副属性，默认作为极限毕业资源。"),
        ("长期最优和当前提升是否冲突？", "长期和当前是否冲突", "看长期绝对最优与当前补弱是否同目标。"),
    ]
    frame = pd.DataFrame(
        [
            {
                "验收问题": question,
                "当前答案": by_question.get(source, {}).get("结论", "见候选页")
                if source
                else "见候选页",
                "怎么继续看": next_step,
            }
            for question, source, next_step in items
        ]
    )
    if action_ev_rows:
        fixed_mask = frame["验收问题"] == "现在应该固定几号位？"
        frame.loc[fixed_mask, "当前答案"] = action_ev_brief(action_ev_rows)
        frame.loc[fixed_mask, "怎么继续看"] = "看攻略结论和随机 vs 固定位置收益效率。"
    return frame


def _candidate_conclusion_frame(game, character, candidate: CandidatePiece, result, analysis) -> pd.DataFrame:
    return pd.DataFrame(
        candidate_conclusion_rows(game, character, candidate, result, analysis)
    )


def _candidate_next_step_frame(result) -> pd.DataFrame:
    return pd.DataFrame(candidate_next_step_rows(result))


def _candidate_acceptance_frame(game, character, candidate: CandidatePiece, result, analysis) -> pd.DataFrame:
    rows = candidate_conclusion_rows(game, character, candidate, result, analysis)
    by_question = _conclusion_by_question(rows)
    items = [
        ("这个新胚子还值不值得强化？", "这个胚子值不值得继续", "看建议和强化观察点。"),
        ("替换当前同位置有没有提升？", "替换当前同位置提升", "看候选补位价值和结果概率。"),
        ("主属性/套装有没有偏？", "主属性是否符合目标", "再结合套装是否符合方案判断。"),
        ("下一跳该看什么？", "强化观察点", "按 +3/+6 等节点止损。"),
    ]
    return pd.DataFrame(
        [
            {
                "验收问题": question,
                "当前答案": by_question.get(source, {}).get("结论", "-"),
                "怎么继续看": next_step,
            }
            for question, source, next_step in items
        ]
    )


def _first_version_acceptance_frame(
    game,
    character,
    candidate: CandidatePiece,
    result,
    analysis,
    current_best,
    long_term_best,
    tuner_best,
    core_best,
    action_ev_rows: list[dict] | None = None,
) -> pd.DataFrame:
    frame = pd.DataFrame(
        first_version_acceptance_rows(
            game,
            character,
            candidate,
            result,
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
            include_strategy_resources=True,
        )
    )
    if action_ev_rows:
        fixed_mask = frame["验收问题"] == "现在应该固定几号位？"
        frame.loc[fixed_mask, "当前答案"] = action_ev_brief(action_ev_rows)
        frame.loc[fixed_mask, "依据"] = "Action EV 按完整概率分布枚举；固定位置只有单位母盘收益高于随机位置时才推荐。"
        frame.loc[fixed_mask, "入口"] = "调律策略比较 -> 攻略结论 / 随机 vs 固定位置收益效率"
    return frame


def _high_priority_closure_frame() -> pd.DataFrame:
    return pd.DataFrame(high_priority_closure_rows())


def _candidate_outcome_frame(game, character, candidate: CandidatePiece, result, analysis) -> pd.DataFrame:
    return pd.DataFrame(
        candidate_outcome_rows(game, character, candidate, result, analysis)
    )


def _strategy_conclusion_frame(
    analysis,
    current_best,
    long_term_best,
    tuner_best,
    core_best,
) -> pd.DataFrame:
    return pd.DataFrame(
        strategy_conclusion_rows(
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
            include_strategy_resources=True,
        )
    )


def _render_import_export_controls(
    game,
    character,
    pieces: list[GearPiece],
    probability_model,
    analysis,
    current_best,
    long_term_best,
    tuner_best,
    core_best,
    strategy_rows,
) -> None:
    current_file = (
        f"{_safe_filename(game.id)}_{_safe_filename(character.id)}_current.yaml"
    )
    target_file = (
        f"{_safe_filename(game.id)}_{_safe_filename(character.id)}_target.yaml"
    )
    report_file = (
        f"{_safe_filename(game.id)}_{_safe_filename(character.id)}_report.md"
    )
    with st.expander("导入/导出", expanded=False):
        uploaded = st.file_uploader(
            "导入当前装备 YAML",
            type=["yaml", "yml"],
            key=f"upload_current_{game.id}_{character.id}",
        )
        if uploaded is not None:
            content = uploaded.getvalue()
            digest = hashlib.sha256(content).hexdigest()
            digest_key = _current_import_digest_key(game, character)
            if st.session_state.get(digest_key) != digest:
                try:
                    metadata, imported_pieces = load_current_yaml_text(
                        content.decode("utf-8")
                    )
                    imported_game = str(metadata.get("game") or "")
                    imported_character = str(metadata.get("character") or "")
                    if imported_game and imported_game != game.id:
                        st.error(
                            f"导入文件属于 {imported_game}，当前选择的是 {game.id}。"
                        )
                    else:
                        if imported_character and imported_character != character.id:
                            st.warning(
                                f"导入文件角色是 {imported_character}，"
                                f"当前模板是 {character.id}，将只导入盘面。"
                            )
                        validate_current_gear_against_game(imported_pieces, game)
                        _apply_current_pieces_to_state(game, character, imported_pieces)
                        st.session_state[digest_key] = digest
                        st.success(f"已导入 {len(imported_pieces)} 件装备。")
                        st.rerun()
                except Exception as exc:
                    st.error(f"导入失败：{exc}")
            else:
                st.caption("当前上传的装备 YAML 已导入。")

        cols = st.columns(3)
        cols[0].download_button(
            "导出当前装备",
            data=current_gear_yaml(
                game.id,
                character.id,
                pieces,
                f"{game.name} {character.name} 当前装备",
            ),
            file_name=current_file,
            mime="application/x-yaml",
            key=f"download_current_{game.id}_{character.id}",
        )
        cols[1].download_button(
            "导出角色目标",
            data=character_target_yaml(character),
            file_name=target_file,
            mime="application/x-yaml",
            key=f"download_target_{game.id}_{character.id}",
        )
        cols[2].download_button(
            "导出分析报告",
            data=current_analysis_report_markdown(
                game,
                character,
                analysis,
                current_best,
                long_term_best,
                tuner_best,
                core_best,
                strategy_rows,
                probability_model=probability_model,
                pieces=pieces,
            ),
            file_name=report_file,
            mime="text/markdown",
            key=f"download_report_{game.id}_{character.id}",
        )


def _render_candidate_import_export_controls(
    game,
    character,
    candidate: CandidatePiece,
    result,
    analysis,
) -> None:
    candidate_file = (
        f"{_safe_filename(game.id)}_{_safe_filename(character.id)}_candidate.yaml"
    )
    report_file = (
        f"{_safe_filename(game.id)}_{_safe_filename(character.id)}_candidate_report.md"
    )
    with st.expander("候选 YAML", expanded=False):
        uploaded = st.file_uploader(
            "导入候选胚子 YAML",
            type=["yaml", "yml"],
            key=f"upload_candidate_{game.id}_{character.id}",
        )
        if uploaded is not None:
            content = uploaded.getvalue()
            digest = hashlib.sha256(content).hexdigest()
            digest_key = _candidate_import_digest_key(game, character)
            if st.session_state.get(digest_key) != digest:
                try:
                    metadata, imported_candidate = load_candidate_yaml_text(
                        content.decode("utf-8")
                    )
                    imported_game = str(metadata.get("game") or "")
                    if imported_game and imported_game != game.id:
                        st.error(
                            f"导入文件属于 {imported_game}，当前选择的是 {game.id}。"
                        )
                    else:
                        validate_candidate_against_game(imported_candidate, game)
                        st.session_state[_candidate_import_state_key(game, character)] = (
                            imported_candidate
                        )
                        st.session_state[digest_key] = digest
                        st.session_state[f"candidate_case_{game.id}"] = "手动输入"
                        st.success("已导入候选胚子。")
                        st.rerun()
                except Exception as exc:
                    st.error(f"导入失败：{exc}")
            else:
                st.caption("当前上传的候选 YAML 已导入。")

        cols = st.columns(2)
        cols[0].download_button(
            "导出候选胚子 YAML",
            data=candidate_yaml(
                game.id,
                candidate,
                f"{game.name} {character.name} 候选胚子",
            ),
            file_name=candidate_file,
            mime="application/x-yaml",
            key=f"download_candidate_{game.id}_{character.id}",
        )
        cols[1].download_button(
            "导出候选报告",
            data=candidate_analysis_report_markdown(
                game,
                character,
                candidate,
                result,
                analysis,
            ),
            file_name=report_file,
            mime="text/markdown",
            key=f"download_candidate_report_{game.id}_{character.id}",
        )


def _strategy_position_context(row, analysis) -> str:
    if row is None or not analysis.set_plan:
        return ""
    pressure = analysis.set_plan["position_pressures"].get(position_key(row.target_position))
    if not pressure:
        return ""
    action = "优先让位" if pressure["replacement_badge"] == "优先替换" else pressure["replacement_badge"]
    return (
        f"{row.target_position_name} 当前套装判断：{action}，"
        f"让位压力 {pressure['replacement_pressure']:g}，{pressure['reason']}。"
    )


def _top_global_strategy_frame(current_best, long_term_best, tuner_best, core_best) -> pd.DataFrame:
    rows = [
        ("当前相对提升最优", current_best, "current_relative_gain_score"),
        ("长期绝对最优", long_term_best, "long_term_value_score"),
        ("校音器观察（只锁主属性）", tuner_best, "current_relative_gain_score"),
        ("共鸣核观察（固定副属性/极限毕业）", core_best, "current_relative_gain_score"),
    ]
    values = []
    for label, row, score_field in rows:
        if row is None:
            continue
        values.append(
            {
                "推荐类型": label,
                "策略": row.strategy_name,
                "目标套装": row.target_set,
                "可接受套装": _target_set_options_label(row),
                "目标位置": row.target_position_name,
                "目标主属性": row.target_main_stat,
                "固定副属性": "、".join(row.fixed_substats) if row.fixed_substats else "不固定",
                "副属性优先级": fixed_substat_note(row),
                "资源口径": _strategy_resource_scope_label(row),
                "决策性质": _strategy_decision_role_label(label, row),
                "概率拆解": _probability_breakdown_label(row),
                "候选概率": row.candidate_probability,
                "期望校音器": row.expected_tuners,
                "期望共鸣核": row.expected_cores,
                "评分": getattr(row, score_field),
            }
        )
    return pd.DataFrame(values)


def _position_rules_frame(game) -> pd.DataFrame:
    def main_stat_label(rule, stat: str) -> str:
        probability = game.main_stat_probability(rule.id, stat)
        return f"{stat}（{probability:.1%}）"

    return pd.DataFrame(
        [
            {
                "位置": rule.name,
                "ID": position_key(rule.id),
                "主属性池": "、".join(main_stat_label(rule, stat) for stat in rule.main_stats),
            }
            for rule in game.positions
        ]
    )


def _substat_rules_frame(game) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "副属性": stat,
                "抽取相对概率": game.sub_stat_probabilities.get(stat, 1.0),
            }
            for stat in game.sub_stats
        ]
    )


def _enhancement_rules_frame(game, probability_model) -> pd.DataFrame:
    rows = [
        {"规则": "最高等级", "值": str(game.enhancement.max_level)},
        {"规则": "强化间隔", "值": str(game.enhancement.step)},
        {"规则": "补第 4 词条等级", "值": str(game.enhancement.initial_add_level)},
        {
            "规则": "强化事件等级",
            "值": "、".join(f"+{level}" for level in game.enhancement.event_levels),
        },
        {"规则": "目标套装概率", "值": f"{probability_model.target_set_probability:.1%}"},
    ]
    for count, probability in probability_model.initial_substat_count_probabilities.items():
        rows.append({"规则": f"初始 {count} 词条概率", "值": f"{probability:.1%}"})
    for key, value in probability_model.resource_costs.items():
        rows.append({"规则": key, "值": str(value)})
    return pd.DataFrame(rows)


def _render_rules_overview(game, probability_model) -> None:
    with st.sidebar.expander("规则概览", expanded=False):
        st.write("位置与主属性池")
        st.dataframe(_position_rules_frame(game), use_container_width=True, hide_index=True)
        st.write("副属性池")
        st.dataframe(_substat_rules_frame(game), use_container_width=True, hide_index=True)
        st.write("强化与概率模型")
        st.dataframe(
            _enhancement_rules_frame(game, probability_model),
            use_container_width=True,
            hide_index=True,
        )
        if probability_model.notes:
            st.caption(probability_model.notes)


BOARD_DENSITY_PRESETS = {
    "紧凑": {
        "tile_size": "6.2rem",
        "tile_padding": "0.32rem",
        "tile_font_size": "0.68rem",
        "tile_icon_size": "42% auto",
        "tile_image_padding": "1.65rem",
        "center_main_size": "0.96rem",
        "center_line_size": "0.66rem",
    },
    "标准": {
        "tile_size": "7.4rem",
        "tile_padding": "0.42rem",
        "tile_font_size": "0.74rem",
        "tile_icon_size": "46% auto",
        "tile_image_padding": "1.95rem",
        "center_main_size": "1.1rem",
        "center_line_size": "0.72rem",
    },
    "宽松": {
        "tile_size": "8.3rem",
        "tile_padding": "0.52rem",
        "tile_font_size": "0.8rem",
        "tile_icon_size": "50% auto",
        "tile_image_padding": "2.2rem",
        "center_main_size": "1.18rem",
        "center_line_size": "0.76rem",
    },
}


def _render_board_density_controls() -> dict[str, str]:
    labels = list(BOARD_DENSITY_PRESETS)
    selected = st.sidebar.selectbox(
        "盘面显示密度",
        labels,
        index=0,
        help="只影响当前装备页六个盘位方块大小，不改变评分和推荐。",
    )
    preset = BOARD_DENSITY_PRESETS[selected]
    st.sidebar.caption(f"盘面方块尺寸：{preset['tile_size']}。2K 全屏推荐紧凑。")
    return preset


games, all_characters, all_probabilities = _load_catalog(CATALOG_CACHE_VERSION)

st.title("gacha-gear-optimizer")

board_density = _render_board_density_controls()

st.markdown(
    f"""
    <style>
    :root {{
      --gear-tile-size: {board_density["tile_size"]};
      --gear-tile-padding: {board_density["tile_padding"]};
      --gear-tile-font-size: {board_density["tile_font_size"]};
      --gear-tile-icon-size: {board_density["tile_icon_size"]};
      --gear-tile-image-padding: {board_density["tile_image_padding"]};
      --gear-center-main-size: {board_density["center_main_size"]};
      --gear-center-line-size: {board_density["center_line_size"]};
      --gear-board-width: calc((var(--gear-tile-size) * 3) + 2.2rem);
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <style>
    [class*="st-key-gear_board_shell_"] {
      width: min(100%, var(--gear-board-width));
      max-width: var(--gear-board-width);
      margin: 0 auto 1.1rem auto;
    }
    [class*="st-key-gear_board_shell_"] [data-testid="stHorizontalBlock"] {
      gap: 0.55rem;
    }
    [class*="st-key-gear_board_shell_"] [data-testid="column"] {
      display: flex;
      justify-content: center;
    }
    .gear-board-spacer {
      width: min(100%, var(--gear-tile-size));
      max-width: var(--gear-tile-size);
      min-height: var(--gear-tile-size);
      aspect-ratio: 1 / 1;
      margin: 0.12rem auto;
    }
    [class*="st-key-gear_tile_"] button,
    [class*="st-key-gear_tile_selected_"] button {
      width: min(100%, var(--gear-tile-size)) !important;
      max-width: var(--gear-tile-size);
      min-height: var(--gear-tile-size);
      aspect-ratio: 1 / 1;
      margin: 0.12rem auto;
      border-radius: 8px;
      border: 1px solid rgba(148, 163, 184, 0.28);
      background:
        linear-gradient(145deg, rgba(30, 41, 59, 0.82), rgba(2, 6, 23, 0.62));
      color: #f8fafc;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
      white-space: pre-line;
      text-align: center;
      align-items: center;
      justify-content: center;
      padding: var(--gear-tile-padding);
      line-height: 1.08;
      font-weight: 720;
      font-size: var(--gear-tile-font-size);
      overflow: hidden;
      overflow-wrap: normal;
      word-break: keep-all;
    }
    [class*="st-key-gear_tile_"],
    [class*="st-key-gear_tile_selected_"] {
      display: flex;
      justify-content: center;
    }
    [class*="st-key-gear_tile_"] button p,
    [class*="st-key-gear_tile_selected_"] button p {
      margin: 0;
      font-size: inherit;
      line-height: inherit;
      white-space: pre-line;
      max-width: calc(var(--gear-tile-size) - 1rem);
      overflow: hidden;
    }
    [class*="st-key-gear_tile_"] button svg,
    [class*="st-key-gear_tile_selected_"] button svg {
      display: none;
    }
    .fallback-set-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      aspect-ratio: 1 / 1;
      border-radius: 8px;
      border: 1px solid rgba(148, 163, 184, 0.25);
      background: rgba(15, 23, 42, 0.78);
      color: #cbd5e1;
      font-size: 0.74rem;
      font-weight: 760;
      text-align: center;
    }
    .gear-board-center {
      width: min(100%, var(--gear-tile-size));
      max-width: var(--gear-tile-size);
      min-height: var(--gear-tile-size);
      aspect-ratio: 1 / 1;
      margin: 0.12rem auto;
      border-radius: 8px;
      border: 1px solid rgba(56, 189, 248, 0.34);
      background:
        linear-gradient(145deg, rgba(15, 23, 42, 0.88), rgba(2, 6, 23, 0.78));
      color: #e2e8f0;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      text-align: center;
      padding: var(--gear-tile-padding);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.07);
    }
    .gear-board-center-title {
      font-size: 0.72rem;
      color: #93c5fd;
      font-weight: 760;
    }
    .gear-board-center-main {
      margin-top: 0.25rem;
      font-size: var(--gear-center-main-size);
      color: #f8fafc;
      font-weight: 820;
    }
    .gear-board-center-line {
      margin-top: 0.25rem;
      font-size: var(--gear-center-line-size);
      color: #cbd5e1;
      font-weight: 680;
      max-width: 100%;
      overflow-wrap: anywhere;
    }
    [class*="st-key-gear_tile_"][class*="_rating_weak"] button {
      border-color: rgba(248, 113, 113, 0.72);
      background:
        linear-gradient(145deg, rgba(127, 29, 29, 0.72), rgba(15, 23, 42, 0.82));
    }
    [class*="st-key-gear_tile_"][class*="_rating_usable"] button {
      border-color: rgba(251, 191, 36, 0.62);
      background:
        linear-gradient(145deg, rgba(113, 63, 18, 0.64), rgba(15, 23, 42, 0.82));
    }
    [class*="st-key-gear_tile_"][class*="_rating_good"] button {
      border-color: rgba(74, 222, 128, 0.58);
      background:
        linear-gradient(145deg, rgba(20, 83, 45, 0.58), rgba(15, 23, 42, 0.82));
    }
    [class*="st-key-gear_tile_"][class*="_rating_excellent"] button {
      border-color: rgba(96, 165, 250, 0.7);
      background:
        linear-gradient(145deg, rgba(30, 64, 175, 0.64), rgba(15, 23, 42, 0.82));
    }
    [class*="st-key-gear_tile_"][class*="_priority_weakest"] button {
      box-shadow:
        0 0 0 1px rgba(251, 113, 133, 0.9),
        0 0 22px rgba(251, 113, 133, 0.26),
        inset 0 1px 0 rgba(255, 255, 255, 0.08);
    }
    [class*="st-key-gear_tile_"][class*="_main_miss"] button {
      border-style: dashed;
    }
    [class*="st-key-gear_tile_"][class*="_set_priority"] button {
      box-shadow:
        inset 0 -4px 0 rgba(251, 146, 60, 0.9),
        0 0 0 1px rgba(251, 146, 60, 0.3);
    }
    [class*="st-key-gear_tile_"][class*="_set_replaceable"] button {
      box-shadow:
        inset 0 -4px 0 rgba(250, 204, 21, 0.72),
        0 0 0 1px rgba(250, 204, 21, 0.22);
    }
    [class*="st-key-gear_tile_"][class*="_plan_yield"] button {
      border-color: rgba(251, 146, 60, 0.78);
      box-shadow:
        inset 0 -5px 0 rgba(251, 146, 60, 0.92),
        0 0 0 1px rgba(251, 146, 60, 0.3);
    }
    [class*="st-key-gear_tile_"][class*="_plan_candidate"] button {
      border-color: rgba(250, 204, 21, 0.58);
      box-shadow:
        inset 0 -4px 0 rgba(250, 204, 21, 0.58),
        0 0 0 1px rgba(250, 204, 21, 0.18);
    }
    [class*="st-key-gear_tile_"][class*="_plan_conflict"] button {
      border-color: rgba(248, 113, 113, 0.86);
      border-style: dashed;
      box-shadow:
        inset 0 -5px 0 rgba(248, 113, 113, 0.88),
        0 0 0 1px rgba(248, 113, 113, 0.34);
    }
    [class*="st-key-gear_tile_"][class*="_priority_weakest"][class*="_set_priority"] button {
      box-shadow:
        inset 0 -4px 0 rgba(251, 146, 60, 0.9),
        0 0 0 1px rgba(251, 113, 133, 0.9),
        0 0 22px rgba(251, 113, 133, 0.26),
        inset 0 1px 0 rgba(255, 255, 255, 0.08);
    }
    [class*="st-key-gear_tile_"][class*="_priority_weakest"][class*="_set_replaceable"] button {
      box-shadow:
        inset 0 -4px 0 rgba(250, 204, 21, 0.72),
        0 0 0 1px rgba(251, 113, 133, 0.9),
        0 0 22px rgba(251, 113, 133, 0.26),
        inset 0 1px 0 rgba(255, 255, 255, 0.08);
    }
    [class*="st-key-gear_tile_"] button:hover,
    [class*="st-key-gear_tile_selected_"] button:hover {
      border-color: #38bdf8;
      color: #f8fafc;
    }
    [class*="st-key-gear_tile_selected_"] button {
      border-color: #38bdf8;
      box-shadow: 0 0 0 1px #38bdf8, 0 12px 30px rgba(0, 0, 0, 0.22);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

game_options = {f"{game.name} ({game.id})": game for game in games}
game_labels = list(game_options)
default_game_index = next(
    (index for index, label in enumerate(game_labels) if game_options[label].id == "zzz"),
    0,
)
selected_game_label = st.sidebar.selectbox("游戏", game_labels, index=default_game_index)
game = game_options[selected_game_label]

characters = [character for character in all_characters if character.game == game.id]
if not characters:
    st.error("当前游戏没有可用角色模板。")
    st.stop()
character_options = {f"{character.name} ({character.id})": character for character in characters}
character_labels = list(character_options)
selected_character_label = st.sidebar.selectbox(
    "角色模板",
    character_labels,
    index=0,
)
character = character_options[selected_character_label]
character = _render_character_target_import_controls(game, character)
character = _render_set_plan_target_controls(game, character)
character = _render_main_stat_target_controls(game, character)
character = _render_target_score_controls(game, character)
character = _render_substat_weight_controls(game, character)
_render_character_target_summary(game, character)

probabilities = [model for model in all_probabilities if model.game == game.id]
if not probabilities:
    st.error("当前游戏没有可用概率模型。")
    st.stop()
probability_options = {f"{model.name} ({model.id})": model for model in probabilities}
probability_labels = list(probability_options)
default_probability_index = next(
    (
        index
        for index, label in enumerate(probability_labels)
        if probability_options[label].id == "zzz_default"
    ),
    0,
)
selected_probability_label = st.sidebar.selectbox(
    "概率模型",
    probability_labels,
    index=default_probability_index,
)
probability_model = probability_options[selected_probability_label]
probability_model = _render_probability_model_import_controls(game, probability_model)
probability_model = _render_probability_model_parameter_controls(game, probability_model)

st.sidebar.caption(f"规则：{game.gear_name} / {len(game.positions)} 个位置")
_render_rules_overview(game, probability_model)

tab_current, tab_candidate, tab_strategy, tab_acceptance = st.tabs(
    ["当前装备评分", "候选胚子评估", "调律策略比较", "验收总览"]
)

with tab_current:
    pieces, editor_warnings = _render_current_editor(game, character)
    st.write("盘面状态摘要")
    st.table(_current_gear_status_frame(game, character, pieces, editor_warnings))
    _render_current_save_controls(game, character, pieces)
    _render_current_source_controls(game, character, pieces)
    analysis = analyse_current_gear(pieces, game, character)
    _render_editor_validation_warnings(editor_warnings)

    current_global_rows = build_strategy_sweep(game, character, probability_model, analysis)
    current_global_best = top_strategy(
        current_global_rows,
        "current_relative_gain_score",
    )
    current_long_term_best = top_strategy(
        current_global_rows,
        "long_term_value_score",
    )
    current_tuner_best = top_strategy(
        [
            row
            for row in current_global_rows
            if row.fixed_main_stat and row.expected_tuners > 0
        ],
        "current_relative_gain_score",
    )
    current_core_best = top_strategy(
        [row for row in current_global_rows if row.expected_cores > 0],
        "current_relative_gain_score",
    )

    scores_df = _scores_frame(analysis)
    summary_cols = st.columns(3)
    summary_cols[0].caption("当前最弱位置")
    summary_cols[0].markdown(f"### {analysis.weakest_position_name or '-'}")
    summary_cols[1].caption("套装方案")
    summary_cols[1].markdown(
        f"**{analysis.set_plan['name'] if analysis.set_plan else character.target_set}**"
    )
    summary_cols[2].caption("有效副词条")
    summary_cols[2].markdown(f"**{_effective_substat_summary(character)}**")

    st.write("当前结论")
    st.dataframe(
        _current_conclusion_frame(
            analysis,
            current_global_best,
            current_long_term_best,
            current_tuner_best,
            current_core_best,
        ),
        use_container_width=True,
        hide_index=True,
    )
    _render_import_export_controls(
        game,
        character,
        pieces,
        probability_model,
        analysis,
        current_global_best,
        current_long_term_best,
        current_tuner_best,
        current_core_best,
        current_global_rows,
    )

    st.info(current_priority_text(analysis))
    st.dataframe(scores_df, use_container_width=True, hide_index=True)

    fig = px.bar(
        scores_df,
        x="位置",
        y="有效词条次数",
        color="评级",
        text="有效词条次数",
        color_discrete_map={
            "weak": "#d95f59",
            "usable": "#d8a31f",
            "good": "#3f8f6b",
            "excellent": "#2d6cdf",
        },
    )
    fig.update_layout(height=360, yaxis_title="有效词条次数", xaxis_title="")
    st.plotly_chart(fig, use_container_width=True)

    priority_df = pd.DataFrame(analysis.relative_priority)
    priority_df = priority_df.rename(
        columns={
            "position_name": "位置",
            "current_effective_rolls": "有效词条",
            "current_weighted_score": "质量分",
            "rating": "评级",
            "main_stat": "主属性",
            "main_stat_target": "目标主属性",
            "main_stat_issue": "主属性状态",
            "main_stat_preferred": "主属性匹配",
            "set_plan_preferred": "套装方案匹配",
            "set_replacement_pressure": "套装替换压力",
            "set_replacement_badge": "替换标签",
            "priority_score": "相对提升优先级",
        }
    )
    if not priority_df.empty:
        priority_df = priority_df.drop(columns=["current_score"], errors="ignore")
        priority_df["主属性匹配"] = priority_df["主属性匹配"].map({True: "是", False: "否"})
        priority_df["套装方案匹配"] = priority_df["套装方案匹配"].map({True: "是", False: "否"})
        priority_df = priority_df.drop(columns=["position"])
        st.dataframe(priority_df, use_container_width=True, hide_index=True)

with tab_candidate:
    candidate, candidate_warnings = _render_candidate_editor(game, character)
    result = evaluate_candidate(candidate, game, character)
    candidate_analysis = analyse_current_gear(pieces, game, character)
    for warning in candidate_warnings + result.warnings:
        st.warning(warning)

    cols = st.columns(6)
    cols[0].metric("当前有效词条数", f"{result.current_effective_rolls:g}")
    cols[1].metric("当前质量分", f"{result.current_weighted_score:g}")
    cols[2].metric("剩余随机命中", result.remaining_roll_events)
    cols[3].metric("最终期望", f"{result.final_expected_effective_rolls:g}")
    cols[4].metric("质量期望", f"{result.final_expected_weighted_score:g}")
    contextual_recommendation, contextual_reason = candidate_contextual_recommendation(
        candidate,
        result,
        candidate_analysis,
    )
    cols[5].metric("建议", contextual_recommendation)

    _render_candidate_import_export_controls(
        game,
        character,
        candidate,
        result,
        candidate_analysis,
    )

    st.write("候选结论")
    st.table(
        _candidate_conclusion_frame(
            game,
            character,
            candidate,
            result,
            candidate_analysis,
        ),
    )
    st.write("下一跳止损卡")
    st.dataframe(
        _candidate_next_step_frame(result),
        use_container_width=True,
        hide_index=True,
    )
    st.write("候选结果概率")
    st.table(
        _candidate_outcome_frame(
            game,
            character,
            candidate,
            result,
            candidate_analysis,
        ),
    )

    if contextual_recommendation == "继续":
        st.success(contextual_reason)
    elif contextual_recommendation == "暂停":
        st.warning(contextual_reason)
    elif contextual_recommendation == "仅过渡":
        st.info(contextual_reason)
    else:
        st.error(contextual_reason)

    st.write("候选验收速览")
    st.dataframe(
        _candidate_acceptance_frame(
            game,
            character,
            candidate,
            result,
            candidate_analysis,
        ),
        use_container_width=True,
        hide_index=True,
    )

    if result.event_rows:
        event_df = pd.DataFrame(
            [
                {
                    "等级": f"+{row['level']}",
                    "事件": row["event"],
                    "命中有效概率": row["hit_probability"],
                    "质量期望增量": row["expected_weighted_gain"],
                    "说明": row["description"],
                }
                for row in result.event_rows
            ]
        )
        event_display_df = event_df.copy()
        event_display_df["命中有效概率"] = event_display_df["命中有效概率"].map(
            lambda value: f"{value:.1%}"
        )
        event_display_df["质量期望增量"] = event_display_df["质量期望增量"].map(
            lambda value: f"{value:.2f}"
        )
        st.write("强化路径明细")
        st.caption("路径会区分 +3 补第 4 副属性，以及后续随机命中已有副属性的概率。")
        st.dataframe(event_display_df, use_container_width=True, hide_index=True)

    distribution_df = pd.DataFrame(
        [
            {
                "最终有效词条次数": point.effective_rolls,
                "概率": point.probability,
            }
            for point in result.distribution
        ]
    )
    weighted_distribution_df = pd.DataFrame(
        [
            {
                "最终质量分": point.weighted_score,
                "概率": point.probability,
            }
            for point in result.weighted_distribution
        ]
    )
    distribution_tabs = st.tabs(["有效次数分布", "质量分布"])
    with distribution_tabs[0]:
        if not distribution_df.empty:
            fig = px.bar(
                distribution_df,
                x="最终有效词条次数",
                y="概率",
                text=distribution_df["概率"].map(lambda value: f"{value:.1%}"),
            )
            fig.update_layout(height=360, yaxis_tickformat=".0%", xaxis_title="最终有效词条次数")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(distribution_df, use_container_width=True, hide_index=True)
    with distribution_tabs[1]:
        if not weighted_distribution_df.empty:
            weighted_display = weighted_distribution_df.copy()
            weighted_display["最终质量分"] = weighted_display["最终质量分"].map(
                lambda value: round(value, 3)
            )
            fig = px.bar(
                weighted_display,
                x="最终质量分",
                y="概率",
                text=weighted_display["概率"].map(lambda value: f"{value:.1%}"),
            )
            fig.update_layout(height=360, yaxis_tickformat=".0%", xaxis_title="最终质量分")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(weighted_display, use_container_width=True, hide_index=True)

with tab_strategy:
    analysis = analyse_current_gear(pieces, game, character)
    st.subheader("库存工作台")
    st.caption("先维护库存；计算当前最优搭配和调律建议都需要你明确点击按钮。")
    extra_inventory_pieces, inventory_warnings = _render_inventory_manager(game, character)
    if inventory_warnings:
        with st.expander("库存输入校验详情", expanded=False):
            for warning in dict.fromkeys(inventory_warnings):
                st.warning(warning)

    with st.expander("计算设置", expanded=True):
        include_candidate_inventory = st.checkbox(
            "把当前候选胚子纳入库存 EV",
            value=False,
            help="勾选后，策略页会把候选胚子视为库存的一部分；未满级胚子会额外出现“强化库存胚子”action。",
            key=f"include_candidate_inventory_{game.id}_{character.id}",
        )
        action_ev_horizon = st.selectbox(
            "Action EV 展望步数",
            [1, 2],
            index=0,
            help="horizon=2 会把本次 action 后的下一次最优调律也纳入期权价值；完整 action 空间计算较重。",
            key=f"action_ev_horizon_{game.id}_{character.id}",
        )
        compute_resource_marginal_ev = st.checkbox(
            "计算特殊资源全局边际 EV 详情",
            value=False,
            help="这张明细表较重；攻略结论不依赖它，只有想审计校音器/共鸣核边际差值时再打开。",
            key=f"compute_resource_marginal_ev_{game.id}_{character.id}",
        )

    strategy_inventory = [
        *pieces,
        *extra_inventory_pieces,
        *([candidate] if include_candidate_inventory else []),
    ]
    requested_action_ev_horizon = int(action_ev_horizon)
    loadout_digest = _strategy_exact_input_digest(
        game,
        character,
        probability_model,
        strategy_inventory,
        0,
    )
    exact_digest = _strategy_exact_input_digest(
        game,
        character,
        probability_model,
        strategy_inventory,
        requested_action_ev_horizon,
    )

    st.caption("下面两个按钮只在你明确点击时计算，不会因为添加或编辑库存自动重算。")
    action_digest = f"{exact_digest}::resource={int(compute_resource_marginal_ev)}"
    loadout_result_key = _strategy_loadout_result_key(game, character)
    action_result_key = _strategy_action_ev_result_key(game, character)

    action_cols = st.columns([1, 1, 2])
    run_loadout = action_cols[0].button(
        "计算当前最优搭配",
        key=f"run_best_loadout_{game.id}_{character.id}",
        use_container_width=True,
    )
    run_action_ev = action_cols[1].button(
        "计算调律建议",
        type="primary",
        key=f"run_action_ev_{game.id}_{character.id}",
        use_container_width=True,
    )
    action_cols[2].caption(
        f"库存池：当前装备 {len(pieces)} 件 + 背包 {len(extra_inventory_pieces)} 件"
        + (" + 当前候选 1 件" if include_candidate_inventory else "")
    )

    if run_loadout:
        st.session_state[loadout_result_key] = {
            "digest": loadout_digest,
            "rows": best_loadout_rows(
                strategy_inventory,
                game,
                character,
                current_count=len(pieces),
            ),
        }

    loadout_result = st.session_state.get(loadout_result_key)
    if isinstance(loadout_result, dict) and loadout_result.get("digest") == loadout_digest:
        st.write("当前最优搭配")
        st.dataframe(
            _best_loadout_display_frame(
                game,
                character,
                list(loadout_result.get("rows") or []),
            ),
            use_container_width=True,
            hide_index=True,
        )
    elif isinstance(loadout_result, dict):
        st.info("库存或方案已变化；上次最优搭配结果已过期，需要重新点击“计算当前最优搭配”。")

    if requested_action_ev_horizon > 1:
        st.warning(
            "horizon=2 是精确枚举，不是抽样；只有点击“计算调律建议”才会开始跑。"
        )
    global_rows = build_strategy_sweep(game, character, probability_model, analysis)
    global_current_best = top_strategy(global_rows, "current_relative_gain_score")
    global_long_term_best = top_strategy(global_rows, "long_term_value_score")
    tuner_best = top_strategy(
        [row for row in global_rows if row.fixed_main_stat and row.expected_tuners > 0],
        "current_relative_gain_score",
    )
    core_best = top_strategy(
        [row for row in global_rows if row.expected_cores > 0],
        "current_relative_gain_score",
    )

    action_result = st.session_state.get(action_result_key)
    action_result_current = (
        action_result
        if isinstance(action_result, dict) and action_result.get("digest") == action_digest
        else None
    )
    if run_action_ev:
        progress_callback = (
            _exact_progress_callback("Action EV 精确计算")
            if requested_action_ev_horizon > 1
            else None
        )
        spinner_text = (
            "正在精确计算 horizon=2 的 action EV；进度条会显示当前 action 和 DP 状态。"
            if requested_action_ev_horizon > 1
            else "正在计算 action EV。"
        )
        with st.spinner(spinner_text):
            action_ev_rows = position_strategy_efficiency_rows(
                game,
                character,
                probability_model,
                analysis,
                inventory_pieces=strategy_inventory,
                horizon=requested_action_ev_horizon,
                progress_callback=progress_callback,
            )
            if compute_resource_marginal_ev:
                resource_progress_callback = (
                    _exact_progress_callback("特殊资源 EV 精确计算")
                    if requested_action_ev_horizon > 1
                    else None
                )
                resource_marginal_ev = _resource_marginal_ev_frame(
                    game,
                    character,
                    probability_model,
                    analysis,
                    inventory_pieces=strategy_inventory,
                    horizon=requested_action_ev_horizon,
                    progress_callback=resource_progress_callback,
                )
            else:
                resource_marginal_ev = pd.DataFrame()
        action_result_current = {
            "digest": action_digest,
            "horizon": requested_action_ev_horizon,
            "action_ev_rows": action_ev_rows,
            "resource_marginal_ev": resource_marginal_ev.to_dict("records"),
        }
        st.session_state[action_result_key] = action_result_current
        st.success(f"horizon={requested_action_ev_horizon} 调律建议已计算完成。")
    elif action_result_current:
        action_ev_rows = list(action_result_current.get("action_ev_rows") or [])
        resource_marginal_ev = pd.DataFrame(
            action_result_current.get("resource_marginal_ev") or []
        )
    else:
        action_ev_rows = []
        resource_marginal_ev = pd.DataFrame()
        if isinstance(action_result, dict):
            st.info("库存、候选、方案或 horizon 已变化；上次调律建议已过期，需要重新点击“计算调律建议”。")
        else:
            st.info("库存可以继续编辑；需要调律建议时再点击“计算调律建议”。")
    st.subheader("攻略结论")
    st.table(
        _strategy_guide_frame(
            action_ev_rows,
            analysis,
            global_current_best,
            global_long_term_best,
            tuner_best,
            core_best,
        )
    )
    st.caption("只看上表就能操作；概率、阶梯和手动核算都收在下方。")
    with st.expander("核算细节：策略上下文", expanded=False):
        st.table(_strategy_context_frame(game, character, probability_model, analysis))
        st.info(set_plan_step_text(analysis))
    with st.expander("核算细节：随机 vs 固定位置收益效率", expanded=False):
        st.caption(
            "按完整概率分布做理论期望，不做抽样模拟；随机/固定都会把新盘加入库存后重求当前套装约束下的最优组合；同时展示质量提升/母盘和有效词条提升/母盘，校音器/共鸣核单独计数。"
        )
        if action_ev_rows:
            st.dataframe(
                pd.DataFrame(_visible_action_ev_rows(action_ev_rows)).astype(str),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("尚未计算调律建议；点击“计算调律建议”后这里会显示完整 Action EV 明细。")
    fixed_main_ladder = _fixed_main_gain_ladder_frame(game, character, probability_model, analysis)
    if not fixed_main_ladder.empty:
        with st.expander("核算细节：固定主属性省母盘阶梯", expanded=False):
            st.caption(
                "先固定位置后再看是否锁主属性：这里按当前补弱顺位列出达到 +1/+2/+3 质量分时，锁主属性相对不锁主属性能少刷多少母盘；校音器只单独计数，不折算。"
            )
            st.dataframe(fixed_main_ladder, use_container_width=True, hide_index=True)
    fixed_substat_ladder = _fixed_substat_gain_ladder_frame(game, character, probability_model, analysis)
    if not fixed_substat_ladder.empty:
        with st.expander("核算细节：固定副属性省母盘阶梯", expanded=False):
            st.caption(
                "已经固定位置和主属性后再看是否锁副属性：这里比较锁 1/2 个目标副词条能少刷多少母盘；共鸣核只单独计数，不折算。"
            )
            st.dataframe(fixed_substat_ladder, use_container_width=True, hide_index=True)
    with st.expander("核算细节：特殊资源全局边际 EV", expanded=False):
        st.caption(
            "固定主属性按 EV(固定位置+固定主属性) - EV(固定位置不固定主属性)；固定副属性按 EV(锁副属性) - EV(只锁主属性)。EV 都通过完整库存 best_loadout 计算，校音器/共鸣核只单独计数。"
        )
        if resource_marginal_ev.empty:
            st.info("这张审计明细默认不自动计算；需要复核时，勾选上面的“计算特殊资源全局边际 EV 详情”。")
        else:
            st.dataframe(resource_marginal_ev, use_container_width=True, hide_index=True)
    with st.expander("核算细节：胚子挡位概率解释", expanded=False):
        st.caption(
            "初始 3 词条按概率模型作为主流；4中3 只有在主属性没有挤占有效副词条时才可能出现，例如 5号物伤可以 4中3，6号生命百分比会挤掉生命百分比副词条。"
        )
        st.dataframe(
            _initial_substat_tier_frame(game, character, probability_model, analysis),
            use_container_width=True,
            hide_index=True,
        )
    tuner_decision, core_decision = resource_decision_text(
        tuner_best,
        core_best,
        global_long_term_best,
    )
    with st.expander("核算细节：资源判断和调律结论", expanded=False):
        resource_cols = st.columns(2)
        resource_cols[0].info(tuner_decision)
        resource_cols[1].warning(core_decision)
        st.table(
            _strategy_conclusion_frame(
                analysis,
                global_current_best,
                global_long_term_best,
                tuner_best,
                core_best,
            )
        )
    with st.expander("核算细节：概率与套装阶段", expanded=False):
        st.write("概率与资源假设")
        st.table(_probability_model_assumption_frame(probability_model))
        st.write("套装阶段拆解")
        st.table(_set_plan_stage_frame(game, analysis))

    set_action_df = _set_plan_action_frame(analysis)
    if not set_action_df.empty:
        with st.expander("套装保留/让位判断", expanded=False):
            st.dataframe(set_action_df, use_container_width=True, hide_index=True)

    global_top_df = _top_global_strategy_frame(
        global_current_best,
        global_long_term_best,
        tuner_best,
        core_best,
    )
    if not global_top_df.empty:
        display_global_df = global_top_df.copy()
        display_global_df["候选概率"] = display_global_df["候选概率"].map(lambda value: f"{value:.3%}")
        for column in ["期望校音器", "期望共鸣核"]:
            display_global_df[column] = display_global_df[column].map(
                lambda value: "∞" if value == float("inf") else f"{value:.1f}"
            )
        with st.expander("核算细节：全局推荐目标", expanded=False):
            st.caption("概率拆解 = 套装概率 × 位置概率 × 主属性概率 × 副属性概率。")
            st.dataframe(display_global_df, use_container_width=True, hide_index=True)

    with st.expander("核算细节：手动目标策略比较", expanded=False):
        default_position = analysis.weakest_position or game.positions[-1].id
        position_options = [rule.id for rule in game.positions]
        cols = st.columns([1, 1, 1])
        selected_position = cols[0].selectbox(
            "目标位置",
            position_options,
            format_func=lambda item: game.position_name(item),
            index=position_options.index(default_position)
            if default_position in position_options
            else 0,
            key="strategy_position",
        )
        preferred_mains = character.preferred_mains_for(selected_position)
        main_options = game.main_stats_for(selected_position)
        default_main = preferred_mains[0] if preferred_mains and preferred_mains[0] in main_options else main_options[0]
        target_main = cols[1].selectbox(
            "目标主属性",
            main_options,
            index=_choice_index(main_options, default_main),
            key="strategy_main",
        )
        strategy_set_groups = _set_option_groups_for_character(game, character)
        strategy_set_options = list(strategy_set_groups)
        default_strategy_set = _recommended_strategy_set(analysis, character, selected_position)
        target_set = cols[2].selectbox(
            "目标套装",
            strategy_set_options,
            index=_choice_index(strategy_set_options, default_strategy_set),
            key="strategy_set",
        )
        target_set_options = strategy_set_groups.get(target_set, [target_set])
        substat_options = _effective_substats_by_priority(character, exclude=target_main)
        with st.expander("固定副属性 / 共鸣核观察", expanded=False):
            st.caption(
                "普通调律决策默认不锁副属性；只有极限毕业或明确要花共鸣核时再选择。"
            )
            fixed_substats = st.multiselect(
                "目标副属性（极限毕业）",
                substat_options,
                default=[],
                key="strategy_substats",
            )

        rows = build_strategy_rows(
            game,
            character,
            probability_model,
            analysis,
            selected_position,
            target_main,
            fixed_substats,
            target_set,
            target_set_options,
            include_fixed_substat_strategies=bool(fixed_substats),
        )
        cost_ladder_df = _strategy_cost_ladder_frame(rows)
        display_cost_ladder_df = cost_ladder_df.copy()
        display_cost_ladder_df["候选概率"] = display_cost_ladder_df["候选概率"].map(
            lambda value: f"{value:.3%}"
        )
        for column in ["期望母盘", "期望校音器", "期望共鸣核"]:
            display_cost_ladder_df[column] = display_cost_ladder_df[column].map(
                lambda value: "∞" if value == float("inf") else f"{value:.1f}"
            )
        st.write("调律成本阶梯")
        st.dataframe(display_cost_ladder_df, use_container_width=True, hide_index=True)

        strategy_df = _strategy_frame(rows)
        display_df = strategy_df.copy()
        for column in ["套装概率", "位置概率", "主属性概率", "副属性概率", "候选概率"]:
            display_df[column] = display_df[column].map(lambda value: f"{value:.3%}")
        for column in ["期望母盘消耗", "期望校音器消耗", "期望共鸣核消耗"]:
            display_df[column] = display_df[column].map(lambda value: "∞" if value == float("inf") else f"{value:.1f}")
        st.caption("候选概率由套装、位置、主属性、副属性四段相乘得到。")
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        current_best = top_strategy(rows, "current_relative_gain_score")
        long_term_best = top_strategy(rows, "long_term_value_score")
        current_text, long_text = strategy_text(current_best, long_term_best, game, character)
        st.success(current_text)
        st.info(long_text)

with tab_acceptance:
    st.subheader("第一版验收总览")
    st.caption(
        "汇总当前装备、候选胚子、调律策略三块结果；这里的答案会随当前页面输入即时变化。"
    )
    acceptance_df = _first_version_acceptance_frame(
        game,
        character,
        candidate,
        result,
        analysis,
        global_current_best,
        global_long_term_best,
        tuner_best,
        core_best,
        action_ev_rows,
    )
    st.write("六个核心问题")
    for row in acceptance_df.to_dict("records"):
        st.markdown(f"**{row['验收问题']}**  \n{row['当前答案']}")
    st.dataframe(acceptance_df, use_container_width=True, hide_index=True)

    st.write("攻略结论")
    st.table(
        _strategy_guide_frame(
            action_ev_rows,
            analysis,
            global_current_best,
            global_long_term_best,
            tuner_best,
            core_best,
        )
    )
    with st.expander("核算细节：今日行动摘要", expanded=False):
        st.table(
            _today_action_summary_frame(
                game,
                character,
                candidate,
                result,
                analysis,
                global_current_best,
                global_long_term_best,
                tuner_best,
                core_best,
            )
        )

    with st.expander("核算细节：高优先级问题闭环", expanded=False):
        st.dataframe(
            _high_priority_closure_frame(),
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("核算细节：下一步操作卡", expanded=False):
        st.table(
            _action_rows_frame(
                first_version_next_action_rows(
                    game,
                    character,
                    candidate,
                    result,
                    analysis,
                    global_current_best,
                    global_long_term_best,
                )
            )
        )

    acceptance_cols = st.columns(4)
    acceptance_cols[0].metric("最弱位置", analysis.weakest_position_name or "-")
    acceptance_cols[1].metric("候选建议", contextual_recommendation)
    acceptance_cols[2].metric(
        "当前补弱",
        global_current_best.target_position_name if global_current_best else "-",
    )
    acceptance_cols[3].metric(
        "长期目标",
        global_long_term_best.target_position_name if global_long_term_best else "-",
    )

    with st.expander("核算细节：当前调律期望管理", expanded=False):
        st.caption(
            "按完整概率分布做理论期望，不做抽样模拟；随机/固定都会把新盘加入库存后重求最优组合；同时展示有效词条提升/母盘和质量提升/母盘；固定主属性只展示省母盘和期望校音器，不做资源折算。"
        )
        st.write("随机 vs 固定位置收益效率")
        if action_ev_rows:
            st.dataframe(
                pd.DataFrame(_visible_action_ev_rows(action_ev_rows)).astype(str),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("尚未计算调律建议；请先在“调律策略比较”里点击“计算调律建议”。")
        st.write("固定主属性省母盘阶梯")
        st.dataframe(
            _fixed_main_gain_ladder_frame(game, character, probability_model, analysis),
            use_container_width=True,
            hide_index=True,
        )
        st.write("固定副属性省母盘阶梯")
        st.dataframe(
            _fixed_substat_gain_ladder_frame(game, character, probability_model, analysis),
            use_container_width=True,
            hide_index=True,
        )

    st.download_button(
        "下载验收总览 Markdown",
        data=first_version_acceptance_report_markdown(
            game,
            character,
            candidate,
            result,
            analysis,
            global_current_best,
            global_long_term_best,
            tuner_best,
            core_best,
            probability_model=probability_model,
        ),
        file_name=f"{_safe_filename(game.id)}_{_safe_filename(character.id)}_acceptance.md",
        mime="text/markdown",
        key=f"download_acceptance_{game.id}_{character.id}",
    )
