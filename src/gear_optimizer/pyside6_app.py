from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback
from typing import Any, Callable
import uuid

from PySide6.QtCore import QObject, QEvent, QProcess, QProcessEnvironment, QThread, QTimer, Qt, Signal, Slot, QSize, QMimeData
from PySide6.QtGui import QDrag, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from gear_optimizer.game_rules import (
    PROJECT_ROOT,
    load_characters,
    load_games,
    load_probability_models,
    validate_current_gear_against_game,
    validate_gear_piece_against_game,
)
from gear_optimizer.agents import (
    AgentMetadata,
    UNKNOWN_LABEL,
    agent_filter_values,
    agent_metadata_with_fallbacks,
    filter_agent_metadata,
)
from gear_optimizer.action_ev_worker import ACTION_EV_ENGINE_ENV, DEFAULT_ACTION_EV_ENGINE, normalize_action_ev_engine
from gear_optimizer.models import (
    CharacterPreset,
    GameRules,
    GearPiece,
    ProbabilityModel,
    SetPlan,
    SetRequirement,
    SubstatLine,
    SubstatPriority,
    position_key,
)
from gear_optimizer.position_ev import (
    action_ev_brief,
    best_loadout_rows,
    position_strategy_efficiency_rows,
    recommended_action_ev_row,
)
from gear_optimizer.portfolio_ev import portfolio_action_rows
from gear_optimizer.portfolio_models import PortfolioMode, PortfolioTarget
from gear_optimizer.presets import list_current_examples, load_current_example
from gear_optimizer.scoring import analyse_current_gear
from gear_optimizer.scoring import score_piece
from gear_optimizer.ui_assets import asset_pixmap, set_effect_tooltip, set_icon_pixmap
from gear_optimizer.user_current_gear import (
    current_gear_store_path,
    delete_user_current_gear,
    load_user_current_gears,
    save_user_current_gear,
)
from gear_optimizer.user_inventory import load_user_inventory, save_user_inventory, user_inventory_store_path
from gear_optimizer.user_target_templates import (
    delete_user_target_template,
    load_user_target_template_source_agents,
    load_user_target_template_sources,
    load_user_target_templates,
    save_user_target_template,
)


COL_POSITION = 0
COL_SET = 1
COL_MAIN = 2
COL_LEVEL = 3
COL_INITIAL = 4
COL_LOCKED = 5
COL_SUB_1 = 6
COL_ROLL_1 = 7
COL_SUB_2 = 8
COL_ROLL_2 = 9
COL_SUB_3 = 10
COL_ROLL_3 = 11
COL_SUB_4 = 12
COL_ROLL_4 = 13
COL_REVEALED_NEXT = 14
GEAR_COLUMNS = [
    "位置",
    "套装",
    "主属性",
    "等级",
    "初始词条",
    "锁定",
    "副词条1",
    "roll1",
    "副词条2",
    "roll2",
    "副词条3",
    "roll3",
    "副词条4",
    "roll4",
    "预告副词条",
]
GEAR_COLUMN_WIDTHS = [
    78,
    128,
    116,
    88,
    76,
    56,
    112,
    96,
    112,
    96,
    112,
    96,
    112,
    96,
    128,
]
LEVEL_COMBO_MIN_WIDTH = 82
ROLL_SPINBOX_MIN_WIDTH = 96
ACTION_DETAIL_DISPLAY_LIMIT = 20
ACTION_PROCESS_TEMP_PREFIX = "gear-action-ev-"
ACTION_SUCCESSFUL_RUNS_TO_KEEP = 3
SUBSTAT_CARD_MIME = "application/x-gear-substat-card"
SUMMARY_NUMERIC_COLUMNS = {"有效", "当前有效", "期望有效", "有效/母盘"}
_TRANSIENT_POPUP_GUARD: QObject | None = None
_TRANSIENT_POPUP_SUPPRESS_UNTIL = 0.0
_TRANSIENT_POPUP_CLASS_NAMES = {
    "QComboBoxPrivateContainer",
    "QRollEffect",
    "QTipLabel",
}
ACTION_VISIBLE_COLUMNS = [
    "动作类型",
    "调律策略/动作",
    "目标套装",
    "位置",
    "主属性",
    "固定副属性",
    "horizon",
    "套装约束",
    "比较口径",
    "有效期望",
    "有效/母盘",
    "高级素材/次",
    "增益判断",
    "方案类型",
    "第一步 action",
    "第二步策略摘要",
    "计算口径",
    "说明",
    "代表路径",
    "代表分支搭配",
    "互补位",
]
APP_QSS = """
QMainWindow, QWidget {
    background: #f4f6f8;
    color: #202124;
    font-size: 13px;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #d7dce2;
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QTabWidget::pane {
    border: 0;
}
QTabBar::tab {
    background: #e7ebf0;
    border: 1px solid #d2d8df;
    border-radius: 6px;
    padding: 8px 14px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #0b57d0;
    border-color: #9db7f5;
}
QPushButton {
    background: #1a73e8;
    color: white;
    border: 0;
    border-radius: 6px;
    padding: 7px 12px;
    font-weight: 700;
}
QPushButton:disabled {
    background: #c8d1dc;
    color: #657386;
}
QPushButton:hover:!disabled {
    background: #1558b0;
}
QComboBox, QLineEdit, QSpinBox {
    background: #ffffff;
    border: 1px solid #cbd3dc;
    border-radius: 6px;
    padding: 5px 8px;
}
QSpinBox {
    min-height: 42px;
    min-width: 96px;
    padding-right: 46px;
}
QSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 42px;
    height: 21px;
    border-left: 1px solid #cbd3dc;
    border-bottom: 1px solid #e5e9ef;
    border-top-right-radius: 6px;
}
QSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 42px;
    height: 21px;
    border-left: 1px solid #cbd3dc;
    border-bottom-right-radius: 6px;
}
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f8fafc;
    gridline-color: #e5e9ef;
    border: 1px solid #d7dce2;
    border-radius: 6px;
}
QHeaderView::section {
    background: #eef2f7;
    color: #3c4043;
    border: 0;
    border-right: 1px solid #d7dce2;
    padding: 6px;
    font-weight: 700;
}
QTextEdit {
    background: #ffffff;
    border: 1px solid #d7dce2;
    border-radius: 6px;
}
QLabel#Badge {
    border-radius: 10px;
    padding: 3px 9px;
    font-weight: 700;
    background: #e8f0fe;
    color: #0b57d0;
}
QLabel#MutedBadge {
    border-radius: 10px;
    padding: 3px 9px;
    font-weight: 700;
    background: #edf2f7;
    color: #56606b;
}
QLabel#WarningBadge {
    border-radius: 10px;
    padding: 3px 9px;
    font-weight: 800;
    background: #fce8e6;
    color: #b3261e;
}
QLabel#MutedText {
    color: #56606b;
}
QLabel#ProgressTitle {
    font-size: 15px;
    font-weight: 800;
    color: #174ea6;
}
QLabel#ProgressMeter {
    font-weight: 700;
    color: #202124;
    padding: 4px 0;
}
QLabel#ProgressDetail {
    color: #3c4043;
}
QScrollArea {
    background: transparent;
    border: 0;
}
QFrame#PieceCard, QFrame#PieceCardSelected, QFrame#OverviewCard, QFrame#RecommendCard {
    background: #ffffff;
    border: 1px solid #d7dce2;
    border-radius: 8px;
}
QFrame#PieceCard:hover {
    border-color: #1a73e8;
}
QFrame#PieceCardSelected {
    border: 2px solid #1a73e8;
}
QFrame#PieceCardHighlighted {
    background: #fff8e1;
    border: 2px solid #fbbc04;
}
QFrame#PieceCardHighlightedSelected {
    background: #fff8e1;
    border: 2px solid #1a73e8;
}
QProgressBar#ActionProgressBar {
    border: 2px solid #1a73e8;
    border-radius: 8px;
    background: #dfe9ff;
    color: #174ea6;
    text-align: center;
    font-weight: 700;
}
QProgressBar#ActionProgressBar::chunk {
    border-radius: 5px;
    margin: 3px;
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #34a853,
        stop: 0.55 #1a73e8,
        stop: 1 #174ea6
    );
}
"""


def _model_payload(item: Any) -> Any:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    return item


def _engine_label(engine: str) -> str:
    if engine == "state_dp":
        return "state_dp（显式状态 DP）"
    return "inventory_recursive（默认精确递归）"


def _execution_mode_label(mode: str) -> str:
    if mode == "worker_process":
        return "QProcess 子进程"
    if mode == "qthread":
        return "QThread 后台线程"
    return mode or "-"


def cleanup_successful_action_run_dirs(parent: Path, keep: int = ACTION_SUCCESSFUL_RUNS_TO_KEEP) -> list[Path]:
    successful_dirs: list[Path] = []
    for child in parent.glob(f"{ACTION_PROCESS_TEMP_PREFIX}*"):
        if not child.is_dir():
            continue
        summary_path = child / "summary.json"
        if not summary_path.exists():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if summary.get("status") == "ok":
            successful_dirs.append(child)

    successful_dirs.sort(
        key=lambda path: (path / "summary.json").stat().st_mtime,
        reverse=True,
    )
    removed: list[Path] = []
    for stale_dir in successful_dirs[max(keep, 0):]:
        shutil.rmtree(stale_dir, ignore_errors=True)
        removed.append(stale_dir)
    return removed


def _pieces_digest(pieces: list[GearPiece]) -> str:
    encoded = json.dumps(
        [_model_payload(piece) for piece in pieces],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _short_digest(value: str, length: int = 10) -> str:
    return value[:length] if value else "-"


def _default_piece(game: GameRules, character: CharacterPreset, position: str | int) -> GearPiece:
    rule = game.position(position)
    preferred = character.preferred_mains_for(rule.id)
    main_stat = preferred[0] if preferred and preferred[0] in rule.main_stats else rule.main_stats[0]
    set_name = _default_set_for_position(game, character, rule.id)
    substats = [
        SubstatLine(stat=stat, rolls=0)
        for stat in character.ordered_effective_substats(exclude=main_stat)
        if stat in game.available_substats(main_stat)
    ][:4]
    return GearPiece(
        position=rule.id,
        set_name=set_name,
        main_stat=main_stat,
        level=game.enhancement.max_level,
        initial_substat_count=4,
        substats=substats,
    )


def _default_set_for_position(
    game: GameRules,
    character: CharacterPreset,
    position: str | int,
) -> str:
    allowed = game.sets_for_position(position)
    set_plan = character.active_set_plan()
    if set_plan and set_plan.requirements:
        for requirement in set_plan.requirements:
            for set_name in requirement.set_names:
                if set_name in allowed:
                    return set_name
    if character.target_set in allowed:
        return character.target_set
    if allowed:
        return allowed[0]
    if game.sets:
        return game.sets[0]
    return character.target_set


def _default_inventory_piece(
    game: GameRules,
    character: CharacterPreset,
    position: str | int,
) -> GearPiece:
    piece = _default_piece(game, character, position)
    available = game.available_substats(piece.main_stat)
    preferred = [
        stat
        for stat in character.ordered_effective_substats(exclude=piece.main_stat)
        if stat in available
    ]
    fill_stats = [stat for stat in available if stat not in preferred]
    substats = [
        SubstatLine(stat=stat, rolls=0)
        for stat in [*preferred, *fill_stats][:3]
    ]
    return piece.model_copy(
        update={
            "level": 0,
            "initial_substat_count": 3,
            "substats": substats,
        }
    )


def _expected_visible_substat_count(game: GameRules, piece: GearPiece) -> int:
    if (
        piece.initial_substat_count == 4
        or piece.level >= game.enhancement.initial_add_level
    ):
        return 4
    return 3


def _expected_roll_total(game: GameRules, piece: GearPiece) -> int:
    total = sum(
        1
        for event_level in game.enhancement.event_levels
        if event_level <= piece.level
    )
    if (
        piece.initial_substat_count == 3
        and piece.level >= game.enhancement.initial_add_level
    ):
        total -= 1
    return max(total, 0)


def gear_piece_entry_consistency_issues(
    piece: GearPiece,
    game: GameRules,
) -> tuple[list[str], list[str]]:
    actual_substats = len(piece.substats)
    expected_substats = _expected_visible_substat_count(game, piece)
    actual_rolls = sum(line.rolls for line in piece.substats)
    expected_rolls = _expected_roll_total(game, piece)
    config_label = (
        f"初始 {piece.initial_substat_count} 条 / 等级 +{piece.level}"
    )
    errors: list[str] = []
    warnings: list[str] = []

    if actual_substats > expected_substats:
        errors.append(
            f"{config_label} 最多应显示 {expected_substats} 条副属性；当前填写了 {actual_substats} 条。"
        )
    elif actual_substats < expected_substats:
        warnings.append(
            f"{config_label} 通常应显示 {expected_substats} 条副属性；当前只填写了 {actual_substats} 条。"
        )

    if actual_rolls > expected_rolls:
        errors.append(
            f"{config_label} 最多应有 {expected_rolls} 次副属性强化；当前填写了 {actual_rolls} 次。"
        )
    elif actual_rolls < expected_rolls:
        warnings.append(
            f"{config_label} 通常应有 {expected_rolls} 次副属性强化；当前只填写了 {actual_rolls} 次。"
        )

    if piece.revealed_next_substat:
        if not game.enhancement.revealed_next_substat_supported:
            errors.append(f"{game.name} 当前不支持记录预告第 4 副属性。")
        elif piece.revealed_next_substat not in game.sub_stats:
            errors.append(f"预告第 4 副属性“{piece.revealed_next_substat}”不是 {game.name} 的合法副属性。")
        elif not (
            piece.initial_substat_count == 3
            and piece.level < game.enhancement.initial_add_level
            and actual_substats == 3
        ):
            errors.append(
                f"{config_label} 不能记录预告第 4 副属性；只有初始 3 条、+{game.enhancement.initial_add_level} 前、已填写 3 条副属性时才有效。"
            )

    return errors, warnings


def _complete_position_pieces(
    game: GameRules,
    character: CharacterPreset,
    pieces: list[GearPiece],
) -> list[GearPiece]:
    by_position = {position_key(piece.position): piece for piece in pieces}
    return [
        by_position.get(position_key(rule.id), _default_piece(game, character, rule.id))
        for rule in game.positions
    ]


def _unique_storage_ids(*values: str) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _gear_piece_duplicate_signature(piece: GearPiece, *, unordered_substats: bool = False) -> str:
    data = piece.model_dump(mode="json")
    if unordered_substats:
        substats = data.get("substats") or []
        data["substats"] = sorted(
            substats,
            key=lambda item: (str(item.get("stat") or ""), int(item.get("rolls") or 0)),
        )
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _inventory_duplicate_groups(
    pieces: list[GearPiece],
    *,
    unordered_substats: bool = False,
) -> list[list[int]]:
    rows_by_signature: dict[str, list[int]] = {}
    for index, piece in enumerate(pieces, start=1):
        signature = _gear_piece_duplicate_signature(piece, unordered_substats=unordered_substats)
        rows_by_signature.setdefault(signature, []).append(index)
    return [rows for rows in rows_by_signature.values() if len(rows) > 1]


def _duplicate_group_summary(groups: list[list[int]], limit: int = 4) -> str:
    shown = ["、".join(f"#{row}" for row in rows) for rows in groups[:limit]]
    text = "；".join(shown)
    if len(groups) > limit:
        text += f"；另有 {len(groups) - limit} 组"
    return text


def _inventory_highlight_summary(rows: set[int], label: str, limit: int = 4) -> str:
    if not rows:
        return ""
    ordered = sorted(rows)
    shown = "、".join(f"库存 #{row + 1}" for row in ordered[:limit])
    hidden = len(ordered) - limit
    suffix = f"、另 {hidden} 件" if hidden > 0 else ""
    return f"{label}：{shown}{suffix}；"


def _inventory_highlight_count_summary(rows: set[int], has_results: bool) -> str:
    if rows:
        return f"高亮 {len(rows)} 件；"
    return "当前结果未高亮库存；" if has_results else ""


def _inventory_hidden_highlight_summary(
    highlighted_rows: set[int],
    visible_rows: set[int],
) -> str:
    hidden_count = len(highlighted_rows - visible_rows)
    if hidden_count <= 0:
        return ""
    return f"其中 {hidden_count} 件高亮被当前筛选隐藏，点“清除筛选”可查看；"


def _inventory_duplicate_row_labels(pieces: list[GearPiece]) -> dict[int, str]:
    exact_groups = _inventory_duplicate_groups(pieces)
    unordered_groups = _inventory_duplicate_groups(pieces, unordered_substats=True)
    exact_row_sets = {tuple(rows) for rows in exact_groups}
    labels: dict[int, str] = {}
    for rows in exact_groups:
        group_text = "、".join(f"#{row}" for row in rows)
        for row in rows:
            labels[row - 1] = f"完全重复：{group_text}"
    for rows in unordered_groups:
        if tuple(rows) in exact_row_sets:
            continue
        group_text = "、".join(f"#{row}" for row in rows)
        for row in rows:
            labels.setdefault(row - 1, f"疑似重复：{group_text}")
    return labels


def _inventory_duplicate_export_summary(pieces: list[GearPiece]) -> dict[str, Any]:
    exact_groups = _inventory_duplicate_groups(pieces)
    unordered_groups = _inventory_duplicate_groups(pieces, unordered_substats=True)
    exact_row_sets = {tuple(rows) for rows in exact_groups}
    similar_groups = [
        rows for rows in unordered_groups if tuple(rows) not in exact_row_sets
    ]
    return {
        "exact_groups": exact_groups,
        "similar_groups": similar_groups,
        "exact_group_count": len(exact_groups),
        "similar_group_count": len(similar_groups),
        "flagged_piece_count": len(_inventory_duplicate_row_labels(pieces)),
    }


def _inventory_export_piece_payload(
    piece: GearPiece,
    index: int,
    duplicate_note: str,
) -> dict[str, Any]:
    payload = _model_payload(piece)
    payload["inventory_index"] = index
    if duplicate_note:
        payload["duplicate_note"] = duplicate_note
    return payload


def _initial_current_pieces(
    game: GameRules,
    storage_id: str,
    fallback_storage_ids: list[str] | None = None,
) -> list[GearPiece]:
    for candidate_id in _unique_storage_ids(storage_id, *(fallback_storage_ids or [])):
        try:
            saved = load_user_current_gears(game.id, candidate_id)
            if saved:
                return list(saved[-1]["pieces"])
            if current_gear_store_path(game.id, candidate_id).exists():
                return []
        except Exception:
            continue
    return []


def _initial_inventory_pieces(
    game: GameRules,
    storage_id: str,
    fallback_storage_ids: list[str] | None = None,
) -> list[GearPiece]:
    pieces, _source_id = _initial_inventory_with_source(game, storage_id, fallback_storage_ids)
    return pieces


def _initial_inventory_with_source(
    game: GameRules,
    storage_id: str,
    fallback_storage_ids: list[str] | None = None,
) -> tuple[list[GearPiece], str]:
    for candidate_id in _unique_storage_ids(storage_id, *(fallback_storage_ids or [])):
        try:
            pieces = load_user_inventory(game.id, candidate_id)
            if pieces or user_inventory_store_path(game.id, candidate_id).exists():
                return pieces, candidate_id
        except Exception:
            continue
    return [], storage_id


def _source_label(source: str | None) -> str:
    return {
        "current": "当前装备",
        "inventory": "背包库存",
        "outcome": "新结果",
    }.get(str(source or "inventory"), "背包库存")


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, tuple):
        return ", ".join(_format_value(item) for item in value)
    if isinstance(value, list):
        return " / ".join(_format_value(item) for item in value)
    return "" if value is None else str(value)


def _clean_sort_value(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if abs(number) <= 1e-9 else number


def _format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    total_seconds = int(seconds + 0.5)
    minutes, second = divmod(total_seconds, 60)
    hour, minute = divmod(minutes, 60)
    if hour:
        return f"{hour}:{minute:02d}:{second:02d}"
    return f"{minute:02d}:{second:02d}"


def _format_progress_count(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _progress_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _badge(text: str, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName("MutedBadge" if muted else "Badge")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _configure_step_spinbox(spin: QSpinBox, minimum_width: int = 92) -> QSpinBox:
    spin.setMinimumWidth(minimum_width)
    spin.setMinimumHeight(44)
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
    spin.setAccelerated(True)
    return spin


def _piece_metric_labels(
    piece: GearPiece,
    game: GameRules,
    character: CharacterPreset,
) -> tuple[str, str]:
    try:
        score = score_piece(piece, game, character)
    except Exception:
        return "-", "-"
    return str(score.effective_rolls), f"{score.weighted_score:.2f}"


def _piece_effective_label(
    piece: GearPiece,
    game: GameRules,
    character: CharacterPreset,
) -> str:
    effective, _quality = _piece_metric_labels(piece, game, character)
    return effective


def _shorten_card_text(value: str | None, limit: int = 34) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)] + "..."


def _set_card_label(game: GameRules, set_name: str) -> str:
    effect = game.set_effect(set_name)
    two_piece = _shorten_card_text(effect.two_piece if effect else "")
    four_piece = _shorten_card_text(effect.four_piece if effect else "")
    lines = [set_name]
    if two_piece:
        lines.append(f"2件 {two_piece}")
    if four_piece:
        lines.append(f"4件 {four_piece}")
    return "\n".join(lines)


def _set_button_style(selected: bool) -> str:
    if selected:
        return (
            "QPushButton { text-align: left; background: #e8f0fe; color: #0b57d0; "
            "border: 2px solid #1a73e8; border-radius: 8px; padding: 8px; font-weight: 800; }"
        )
    return (
        "QPushButton { text-align: left; background: #ffffff; color: #202124; "
        "border: 1px solid #d7dce2; border-radius: 8px; padding: 8px; font-weight: 700; }"
        "QPushButton:hover { border-color: #1a73e8; }"
    )


def _stat_button_style(selected: bool) -> str:
    if selected:
        return (
            "QPushButton { background: #e8f0fe; color: #0b57d0; border: 2px solid #1a73e8; "
            "border-radius: 8px; padding: 8px; font-weight: 800; }"
        )
    return (
        "QPushButton { background: #ffffff; color: #202124; border: 1px solid #d7dce2; "
        "border-radius: 8px; padding: 8px; font-weight: 700; }"
        "QPushButton:hover { border-color: #1a73e8; }"
    )


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _action_row_has_positive_gain(row: dict[str, Any]) -> bool:
    return _float_value(row.get("有效提升")) > 0.0005


def _action_gain_label(row: dict[str, Any]) -> str:
    return "有效提升为正" if _action_row_has_positive_gain(row) else "无有效提升"


def _effective_gain_summary(row: dict[str, Any]) -> str:
    value = row.get("有效提升")
    if value is None:
        return str(row.get("期望提升", "-") or "-")
    effective = _float_value(value)
    if abs(effective) <= 0.0005:
        return "无有效提升"
    sign = "+" if effective > 0 else ""
    return f"有效提升 {sign}{effective:g}"


def _loadout_level_label(piece: Any, row: dict[str, Any]) -> str:
    if not isinstance(piece, GearPiece):
        return "-"
    if row.get("_expected_upgrade"):
        return f"+{piece.level} -> +{row.get('_expected_level', '?')} 期望"
    return f"+{piece.level}"


def _inventory_index(row: dict[str, Any]) -> int | None:
    raw = str(row.get("_inventory_id") or "")
    if not raw.startswith("piece:"):
        return None
    try:
        return int(raw.removeprefix("piece:"))
    except ValueError:
        return None


def _inventory_source_row_from_id(raw_id: Any, current_count: int) -> int | None:
    raw = str(raw_id or "")
    if not raw.startswith("piece:"):
        return None
    try:
        global_index = int(raw.removeprefix("piece:"))
    except ValueError:
        return None
    source_row = global_index - current_count
    return source_row if source_row >= 0 else None


def _inventory_source_rows_from_loadout_rows(
    rows: list[dict[str, Any]],
    current_count: int,
) -> set[int]:
    values: set[int] = set()
    for row in rows:
        source_row = _inventory_source_row_from_id(row.get("_inventory_id"), current_count)
        if source_row is not None:
            values.add(source_row)
    return values


def _inventory_source_rows_from_action_row(
    row: dict[str, Any] | None,
    current_count: int,
) -> set[int]:
    if not row:
        return set()
    values: set[int] = set()
    source_row = _inventory_source_row_from_id(row.get("_upgrade_inventory_id"), current_count)
    if source_row is not None:
        values.add(source_row)
    raw_loadout_rows = row.get("_representative_loadout_rows")
    if isinstance(raw_loadout_rows, list):
        values.update(
            _inventory_source_rows_from_loadout_rows(
                [dict(item) for item in raw_loadout_rows if isinstance(item, dict)],
                current_count,
            )
        )
    return values


def _inventory_label_from_piece_id(raw_id: Any, current_count: int) -> str:
    source_row = _inventory_source_row_from_id(raw_id, current_count)
    return f"库存 #{source_row + 1}" if source_row is not None else "-"


def _loadout_source_ref(row: dict[str, Any], current_count: int) -> str:
    index = _inventory_index(row)
    if index is None:
        return _source_label(row.get("source"))
    if index < current_count:
        return f"当前 #{index + 1}"
    return f"库存 #{index - current_count + 1}"


def _piece_substat_label(piece: Any) -> str:
    if not isinstance(piece, GearPiece) or not piece.substats:
        return "-"
    return " / ".join(f"{line.stat}+{line.rolls}" for line in piece.substats)


def _piece_revealed_next_substat_label(piece: Any, game: GameRules | None = None) -> str:
    if not isinstance(piece, GearPiece) or not piece.revealed_next_substat:
        return ""
    label = f"预告第4副属性：{piece.revealed_next_substat}"
    if game is not None:
        if not game.enhancement.revealed_next_substat_supported:
            return f"{label}（当前游戏不支持，计算会忽略）"
        selected_stats = [line.stat for line in piece.substats]
        if piece.revealed_next_substat not in game.available_substats(piece.main_stat, selected_stats):
            return f"{label}（不适用于当前主属性或已有副属性，计算会忽略）"
        if not (
            piece.initial_substat_count == 3
            and piece.level < game.enhancement.initial_add_level
            and len(piece.substats) == 3
        ):
            return f"{label}（当前状态不适用，计算会忽略）"
    return label


def _loadout_main_stat_label(row: dict[str, Any]) -> str:
    piece = row.get("_piece")
    if isinstance(piece, GearPiece):
        return piece.main_stat
    return str(row.get("main_stat") or "-")


def _loadout_substat_label(row: dict[str, Any], game: GameRules) -> str:
    piece = row.get("_piece")
    if isinstance(piece, GearPiece):
        label = _piece_substat_label(piece)
        revealed_next = _piece_revealed_next_substat_label(piece, game)
        return f"{label} / {revealed_next}" if revealed_next else label
    return "代表期望结果"


def _loadout_level_from_row(row: dict[str, Any]) -> str:
    piece = row.get("_piece")
    if isinstance(piece, GearPiece):
        return _loadout_level_label(piece, row)
    level = row.get("level")
    return f"+{level}" if level is not None else "-"


def _position_order(game: GameRules) -> dict[str, int]:
    return {position_key(rule.id): index for index, rule in enumerate(game.positions)}


def _loadout_display_rows(
    rows: list[dict[str, Any]],
    game: GameRules,
    current_count: int,
) -> list[dict[str, Any]]:
    order = _position_order(game)
    display_rows = []
    sorted_rows = sorted(
        rows,
        key=lambda row: (order.get(position_key(row["position"]), 999), position_key(row["position"])),
    )
    for index, row in enumerate(sorted_rows, start=1):
        display_rows.append(
            {
                "#": index,
                "来源行": _loadout_source_ref(row, current_count),
                "位置": game.position_name(row["position"]),
                "来源": _source_label(row.get("source")),
                "套装": row["set_name"],
                "主属性": _loadout_main_stat_label(row),
                "等级": _loadout_level_from_row(row),
                "估值口径": "满级强化期望（不折算强化材料）" if row.get("_expected_upgrade") else "当前值/代表结果",
                "当前有效": row.get("_current_effective_rolls", row.get("effective_rolls", "-")),
                "期望有效": row.get("effective_rolls", "-"),
                "副词条": _loadout_substat_label(row, game),
            }
        )
    return display_rows


def _loadout_inventory_usage_summary(
    rows: list[dict[str, Any]],
    current_count: int,
    limit: int = 4,
) -> str:
    inventory_rows = _inventory_source_rows_from_loadout_rows(rows, current_count)
    if not inventory_rows:
        return "仅使用当前装备。"
    shown = "、".join(f"库存 #{row + 1}" for row in sorted(inventory_rows)[:limit])
    hidden = len(inventory_rows) - limit
    suffix = f"、另 {hidden} 件" if hidden > 0 else ""
    return f"使用库存：{shown}{suffix}。"


def _loadout_valuation_summary(rows: list[dict[str, Any]]) -> str:
    expected_count = sum(1 for row in rows if row.get("_expected_upgrade"))
    if expected_count <= 0:
        return "估值口径：均按当前值/代表结果。"
    return f"估值口径：含 {expected_count} 件未满级装备按满级强化期望估值，不折算强化材料消耗。"


def _loadout_vs_upgrade_opportunity_summary() -> str:
    return (
        "口径区别：当前最优是在当前装备+库存中选搭配；"
        "库存升级机会只评估某件未满级继续升级的未来分支，正期望不等于当前已入选最优。"
    )


def _loadout_result_summary(
    rows: list[dict[str, Any]],
    current_count: int,
    total_count: int,
) -> str:
    return "\n".join(
        [
            f"当前最优搭配 {len(rows)} 件；库存合计 {total_count} 件。",
            _loadout_inventory_usage_summary(rows, current_count),
            _loadout_valuation_summary(rows),
            _loadout_vs_upgrade_opportunity_summary(),
        ]
    )


def _priority_tiers_text(tiers: list[list[str]]) -> str:
    parts = [" = ".join(tier) for tier in tiers if tier]
    return " > ".join(parts)


def _action_row_explanation(row: dict[str, Any]) -> str:
    strategy = str(row.get("策略") or "")
    relative = str(row.get("相对随机") or "")
    comparison = str(row.get("比较口径") or relative)
    set_plan = str(row.get("套装约束") or "")
    horizon = int(row.get("horizon") or 1)
    horizon_note = ""
    if horizon > 1:
        horizon_note = "horizon>1 的 EV 已加权所有 outcome；H=2 方案页展示审计用代表路径或条件分支。"
    if set_plan.startswith("未满足"):
        return "未满足当前套装硬约束，不作为推荐结论。"
    if strategy == "随机位置":
        return (
            "随机位置这一行的数值由同目标套装各固定位置 action value 按位置概率加权平均得到；"
            f"不存在唯一典型搭配。{horizon_note}"
        )
    if strategy == "固定位置":
        return f"固定位置是基础 action；{comparison}。{horizon_note}"
    if strategy == "固定位置 + 固定主属性":
        return f"{comparison}；本行只和同位置不锁主属性的固定位置 action 比较。{horizon_note}"
    if strategy == "固定位置 + 固定主属性 + 固定副属性":
        return f"{comparison}；本行只和同位置锁主属性 action 比较。{horizon_note}"
    if strategy == "强化库存胚子":
        return (
            "这是库存升级机会，不是调律母盘策略；它回答的是这件未满级胚子继续升有没有期望价值。"
            "升级不消耗母盘，会消耗强化材料，本工具暂不把强化材料折算成母盘。"
            "有效提升为正表示升级后的所有 roll 分支按概率加权后有 option value；"
            "它不等于这件胚子当前已经比已装备件更好，也不保证代表/均值搭配一定选它。"
            "如果它出现在 H=2 第二步，第一步调律 action 会写在对应代表路径或条件分支里。"
            f"{horizon_note}"
        )
    return (relative or "完整概率分布精确计算。") + horizon_note


def _action_type_label(row: dict[str, Any]) -> str:
    raw = str(row.get("动作类型") or "")
    if raw:
        return raw
    return "库存升级机会" if row.get("策略") == "强化库存胚子" else "调律母盘"


def _action_display_strategy_label(row: dict[str, Any]) -> str:
    if row.get("策略") == "强化库存胚子":
        return "非调律：升级已有库存"
    return str(row.get("策略") or "-")


def _action_visible_summary(row: dict[str, Any], current_count: int = 0) -> str:
    parts = [_action_display_strategy_label(row)]
    if row.get("策略") == "强化库存胚子":
        inventory_label = _inventory_label_from_piece_id(row.get("_upgrade_inventory_id"), current_count)
        if inventory_label != "-":
            parts.append(inventory_label)
    for key in ["目标套装", "位置", "主属性"]:
        value = _format_value(row.get(key, "-"))
        if value and value != "-":
            parts.append(value)
    return " / ".join(parts) if parts else "-"


def _best_positive_upgrade_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if row.get("策略") == "强化库存胚子"
        and _action_row_has_positive_gain(row)
        and not str(row.get("套装约束") or "").startswith("未满足")
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (
            _float_value(row.get("有效提升")),
            _float_value(row.get("质量提升")),
            *_action_sort_vector(row),
        ),
    )


def _action_sort_vector(row: dict[str, Any]) -> tuple[float, ...]:
    raw = row.get("_sort_vector")
    if isinstance(raw, (list, tuple)):
        return tuple(_clean_sort_value(value) for value in raw)
    return (
        _clean_sort_value(row.get("质量/母盘")),
        _clean_sort_value(row.get("有效/母盘")),
    )


def _action_row_recommend_group(row: dict[str, Any]) -> int:
    strategy = str(row.get("策略") or "")
    relative = str(row.get("相对随机") or "")
    set_plan_status = str(row.get("套装约束") or "")
    if set_plan_status.startswith("未满足"):
        return 0
    if strategy == "随机位置":
        return 3
    if strategy == "固定位置" and relative in {"优于随机，才建议固定", "固定位置基准"}:
        return 3
    if (
        strategy == "固定位置 + 固定主属性"
        and relative
        in {
            "固定位置已优于随机；优于固定位置，才建议锁主属性",
            "优于固定位置，才建议锁主属性",
        }
    ):
        return 3
    if (
        strategy == "固定位置 + 固定主属性 + 固定副属性"
        and relative
        in {
            "锁主属性已优于固定位置；优于锁主属性，才建议锁副属性",
            "优于锁主属性，才建议锁副属性",
        }
    ):
        return 3
    if strategy == "强化库存胚子" and _action_row_has_positive_gain(row):
        return 2
    if _action_row_has_positive_gain(row):
        return 1
    return 0


def _action_display_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _action_row_recommend_group(row),
        _clean_sort_value(row.get("有效/母盘")),
        _float_value(row.get("有效提升")),
        _action_sort_vector(row),
    )


def _sorted_action_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=_action_display_sort_key, reverse=True)


def _desktop_recommended_action_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if row.get("策略") != "强化库存胚子"
        and _action_row_has_positive_gain(row)
        and _action_row_recommend_group(row) == 3
    ]
    if not candidates:
        return None
    return max(candidates, key=_action_display_sort_key)


def _action_display_row(row: dict[str, Any]) -> dict[str, Any]:
    display = {
        column: (
            _action_type_label(row)
            if column == "动作类型"
            else _action_display_strategy_label(row)
            if column == "调律策略/动作"
            else row.get("比较口径", row.get("相对随机", ""))
            if column == "比较口径"
            else row.get("代表分支搭配", row.get("预期搭配", ""))
            if column == "代表分支搭配"
            else _action_gain_label(row)
            if column == "增益判断"
            else _effective_gain_summary(row)
            if column == "有效期望"
            else row.get(column, "")
        )
        for column in ACTION_VISIBLE_COLUMNS
    }
    display["计算口径"] = "精确"
    display["说明"] = _action_row_explanation(row)
    return display


class GearTable(QTableWidget):
    changed = Signal()

    def __init__(
        self,
        editable_positions: bool,
        row_label_prefix: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.editable_positions = editable_positions
        self.row_label_prefix = row_label_prefix
        self.game: GameRules | None = None
        self.character: CharacterPreset | None = None
        self._loading = False
        self.setColumnCount(len(GEAR_COLUMNS))
        self.setHorizontalHeaderLabels(GEAR_COLUMNS)
        self.verticalHeader().setVisible(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setWordWrap(False)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().setStretchLastSection(False)
        self._apply_column_widths()

    def set_context(
        self,
        game: GameRules,
        character: CharacterPreset,
        pieces: list[GearPiece],
    ) -> None:
        self.game = game
        self.character = character
        self._loading = True
        try:
            self.setRowCount(0)
            self.setRowCount(len(pieces))
            for row, piece in enumerate(pieces):
                self._populate_row(row, piece)
            self._refresh_row_labels()
        finally:
            self._loading = False

    def add_piece(self, piece: GearPiece) -> None:
        self._require_context()
        self._loading = True
        try:
            row = self.rowCount()
            self.insertRow(row)
            self._populate_row(row, piece)
            self._refresh_row_labels()
        finally:
            self._loading = False
        self.changed.emit()

    def remove_selected(self) -> None:
        selected = self.selectionModel().selectedRows()
        if not selected:
            return
        self.removeRow(selected[0].row())
        self._refresh_row_labels()
        self.changed.emit()

    def collect_pieces(self) -> tuple[list[GearPiece], list[str]]:
        game, _character = self._require_context()
        pieces: list[GearPiece] = []
        warnings: list[str] = []
        for row in range(self.rowCount()):
            try:
                position = self._position_value(row)
                main_stat = str(self._combo_value(row, COL_MAIN))
                substats: list[SubstatLine] = []
                for sub_col, roll_col in [
                    (COL_SUB_1, COL_ROLL_1),
                    (COL_SUB_2, COL_ROLL_2),
                    (COL_SUB_3, COL_ROLL_3),
                    (COL_SUB_4, COL_ROLL_4),
                ]:
                    stat = str(self._combo_value(row, sub_col) or "")
                    if stat:
                        substats.append(
                            SubstatLine(
                                stat=stat,
                                rolls=int(self._spin_value(row, roll_col)),
                            )
                        )
                revealed_next_substat = str(self._combo_value(row, COL_REVEALED_NEXT) or "") or None
                if revealed_next_substat and not game.enhancement.revealed_next_substat_supported:
                    revealed_next_substat = None
                piece = GearPiece(
                    position=position,
                    set_name=str(self._combo_value(row, COL_SET)),
                    main_stat=main_stat,
                    level=int(self._combo_value(row, COL_LEVEL)),
                    initial_substat_count=int(self._combo_value(row, COL_INITIAL)),
                    locked=self._checkbox_value(row, COL_LOCKED),
                    substats=substats,
                    revealed_next_substat=revealed_next_substat,
                )
                validate_gear_piece_against_game(piece, game)
                pieces.append(piece)
            except Exception as exc:
                row_label = self._row_position_label(row)
                warnings.append(f"{row_label} 无法纳入计算：{exc}")
        return pieces, warnings

    def _require_context(self) -> tuple[GameRules, CharacterPreset]:
        if self.game is None or self.character is None:
            raise RuntimeError("gear table context has not been initialised")
        return self.game, self.character

    def _refresh_row_labels(self) -> None:
        self.setVerticalHeaderLabels(
            [f"{self.row_label_prefix} #{row + 1}" for row in range(self.rowCount())]
        )

    def _apply_column_widths(self) -> None:
        for column, width in enumerate(GEAR_COLUMN_WIDTHS):
            self.setColumnWidth(column, width)
        self.verticalHeader().setFixedWidth(68)

    def _populate_row(self, row: int, piece: GearPiece) -> None:
        game, _character = self._require_context()
        if self.editable_positions:
            position_combo = self._combo(
                [(game.position_name(rule.id), rule.id) for rule in game.positions],
                piece.position,
            )
            position_combo.currentIndexChanged.connect(lambda _index, r=row: self._position_changed(r))
            self.setCellWidget(row, COL_POSITION, position_combo)
        else:
            item = QTableWidgetItem(game.position_name(piece.position))
            item.setData(Qt.ItemDataRole.UserRole, piece.position)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, COL_POSITION, item)

        self.setCellWidget(
            row,
            COL_SET,
            self._combo(
                [(name, name) for name in game.sets_for_position(piece.position)],
                piece.set_name,
            ),
        )
        self.setCellWidget(
            row,
            COL_MAIN,
            self._combo(
                [(name, name) for name in game.main_stats_for(piece.position)],
                piece.main_stat,
            ),
        )
        main_combo = self.cellWidget(row, COL_MAIN)
        if isinstance(main_combo, QComboBox):
            main_combo.currentIndexChanged.connect(lambda _index, r=row: self._main_changed(r))
        level_values = list(range(0, game.enhancement.max_level + 1, game.enhancement.step))
        level_combo = self._combo([(f"+{value}", value) for value in level_values], piece.level)
        level_combo.setMinimumWidth(LEVEL_COMBO_MIN_WIDTH)
        self.setCellWidget(row, COL_LEVEL, level_combo)
        self.setCellWidget(row, COL_INITIAL, self._combo([("3", 3), ("4", 4)], piece.initial_substat_count))
        locked = QCheckBox()
        locked.setChecked(piece.locked)
        if self.editable_positions:
            locked.setEnabled(False)
        locked.stateChanged.connect(lambda _state: self._emit_changed())
        self.setCellWidget(row, COL_LOCKED, locked)

        rows = list(piece.substats[:4]) + [SubstatLine(stat="", rolls=0) for _ in range(4 - len(piece.substats[:4]))]
        for index, line in enumerate(rows):
            sub_col = COL_SUB_1 + index * 2
            roll_col = COL_ROLL_1 + index * 2
            self.setCellWidget(row, sub_col, self._substat_combo(piece.main_stat, line.stat))
            spin = _configure_step_spinbox(QSpinBox(), ROLL_SPINBOX_MIN_WIDTH)
            spin.setRange(0, 5)
            spin.setValue(int(line.rolls))
            spin.valueChanged.connect(lambda _value: self._emit_changed())
            self.setCellWidget(row, roll_col, spin)
        self.setCellWidget(
            row,
            COL_REVEALED_NEXT,
            self._substat_combo(piece.main_stat, piece.revealed_next_substat or ""),
        )

    def _combo(self, items: list[tuple[str, Any]], current: Any) -> QComboBox:
        combo = QComboBox()
        for label, value in items:
            combo.addItem(label, value)
        target = position_key(current)
        for index in range(combo.count()):
            if position_key(combo.itemData(index)) == target:
                combo.setCurrentIndex(index)
                break
        combo.currentIndexChanged.connect(lambda _index: self._emit_changed())
        return combo

    def _substat_combo(self, main_stat: str, current: str) -> QComboBox:
        game, _character = self._require_context()
        items = [("", "")] + [
            (stat, stat)
            for stat in game.sub_stats
            if stat != main_stat
        ]
        return self._combo(items, current)

    def _position_changed(self, row: int) -> None:
        game, _character = self._require_context()
        position = self._position_value(row)
        set_combo = self.cellWidget(row, COL_SET)
        current_set = str(set_combo.currentData() if isinstance(set_combo, QComboBox) else "")
        if isinstance(set_combo, QComboBox):
            self._loading = True
            try:
                set_combo.clear()
                allowed_sets = game.sets_for_position(position)
                for set_name in allowed_sets:
                    set_combo.addItem(set_name, set_name)
                index = set_combo.findData(current_set)
                set_combo.setCurrentIndex(index if index >= 0 else 0)
            finally:
                self._loading = False
        main_combo = self.cellWidget(row, COL_MAIN)
        current = str(main_combo.currentData() if isinstance(main_combo, QComboBox) else "")
        if isinstance(main_combo, QComboBox):
            self._loading = True
            try:
                main_combo.clear()
                for stat in game.main_stats_for(position):
                    main_combo.addItem(stat, stat)
                index = main_combo.findData(current)
                main_combo.setCurrentIndex(index if index >= 0 else 0)
            finally:
                self._loading = False
        self._main_changed(row)

    def _main_changed(self, row: int) -> None:
        main_stat = str(self._combo_value(row, COL_MAIN))
        self._loading = True
        try:
            for sub_col in [COL_SUB_1, COL_SUB_2, COL_SUB_3, COL_SUB_4]:
                widget = self.cellWidget(row, sub_col)
                current = str(widget.currentData() if isinstance(widget, QComboBox) else "")
                combo = self._substat_combo(main_stat, current)
                self.setCellWidget(row, sub_col, combo)
            revealed_widget = self.cellWidget(row, COL_REVEALED_NEXT)
            current_revealed = str(
                revealed_widget.currentData() if isinstance(revealed_widget, QComboBox) else ""
            )
            self.setCellWidget(row, COL_REVEALED_NEXT, self._substat_combo(main_stat, current_revealed))
        finally:
            self._loading = False
        self._emit_changed()

    def _emit_changed(self) -> None:
        if not self._loading:
            self.changed.emit()

    def _position_value(self, row: int) -> Any:
        if self.editable_positions:
            return self._combo_value(row, COL_POSITION)
        item = self.item(row, COL_POSITION)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _row_position_label(self, row: int) -> str:
        try:
            game, _character = self._require_context()
            return game.position_name(self._position_value(row))
        except Exception:
            return f"第 {row + 1} 行"

    def _combo_value(self, row: int, column: int) -> Any:
        widget = self.cellWidget(row, column)
        if isinstance(widget, QComboBox):
            value = widget.currentData()
            return widget.currentText() if value is None else value
        return ""

    def _spin_value(self, row: int, column: int) -> int:
        widget = self.cellWidget(row, column)
        return int(widget.value()) if isinstance(widget, QSpinBox) else 0

    def _checkbox_value(self, row: int, column: int) -> bool:
        widget = self.cellWidget(row, column)
        return bool(widget.isChecked()) if isinstance(widget, QCheckBox) else False


class PieceCard(QFrame):
    clicked = Signal(int)
    edit_requested = Signal(int)
    equip_requested = Signal(int)
    copy_requested = Signal(int)
    clear_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(
        self,
        row_index: int,
        show_actions: bool = False,
        show_equip: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.row_index = row_index
        self.show_actions = show_actions
        self._selected = False
        self._highlighted = False
        self.setObjectName("PieceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(250 if show_actions else 230, 300 if show_actions else 220)
        self.setMaximumHeight(340 if show_actions else 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        header = QHBoxLayout()
        self.icon_label = QLabel("")
        self.icon_label.setFixedSize(38, 38)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.index_badge = _badge(f"库存 #{row_index + 1}", muted=True)
        self.index_badge.setVisible(show_actions)
        self.position_label = QLabel("-")
        self.position_label.setStyleSheet("font-weight: 900; font-size: 15px;")
        self.position_label.setWordWrap(True)
        self.highlight_badge = _badge("入选")
        self.highlight_badge.setVisible(False)
        self.duplicate_badge = _badge("重复")
        self.duplicate_badge.setObjectName("WarningBadge")
        self.duplicate_badge.setVisible(False)
        header.addWidget(self.index_badge)
        self.locked_badge = _badge("未锁", muted=True)
        header.addWidget(self.icon_label)
        header.addWidget(self.position_label, 1)
        header.addWidget(self.highlight_badge)
        header.addWidget(self.duplicate_badge)
        header.addWidget(self.locked_badge)
        layout.addLayout(header)

        chips = QHBoxLayout()
        self.level_badge = _badge("等级 -/-", muted=True)
        self.metric_badge = _badge("有效 -", muted=True)
        chips.addWidget(self.level_badge)
        chips.addWidget(self.metric_badge)
        chips.addStretch(1)
        layout.addLayout(chips)

        self.set_label = QLabel("-")
        self.main_label = QLabel("-")
        self.substat_label = QLabel("-")
        self.substat_label.setWordWrap(True)
        layout.addWidget(self.set_label)
        layout.addWidget(self.main_label)
        layout.addWidget(self.substat_label, 1)

        if show_actions:
            primary_actions = QHBoxLayout()
            primary_actions.setSpacing(6)
            if show_equip:
                equip_button = QPushButton("装备")
                equip_button.clicked.connect(lambda _checked=False: self.equip_requested.emit(self.row_index))
                primary_actions.addWidget(equip_button)
            edit_button = QPushButton("编辑")
            edit_button.clicked.connect(lambda _checked=False: self.edit_requested.emit(self.row_index))
            primary_actions.addWidget(edit_button)
            layout.addLayout(primary_actions)

            secondary_actions = QHBoxLayout()
            secondary_actions.setSpacing(6)
            copy_button = QPushButton("复制")
            copy_button.clicked.connect(lambda _checked=False: self.copy_requested.emit(self.row_index))
            clear_button = QPushButton("清空")
            clear_button.clicked.connect(lambda _checked=False: self.clear_requested.emit(self.row_index))
            delete_button = QPushButton("删除")
            delete_button.clicked.connect(lambda _checked=False: self.delete_requested.emit(self.row_index))
            secondary_actions.addWidget(copy_button)
            secondary_actions.addWidget(clear_button)
            secondary_actions.addWidget(delete_button)
            layout.addLayout(secondary_actions)

    def update_piece(
        self,
        piece: GearPiece,
        game: GameRules,
        character: CharacterPreset,
    ) -> None:
        effective, _quality = _piece_metric_labels(piece, game, character)
        pixmap = set_icon_pixmap(game, piece.set_name, 32)
        if pixmap is not None:
            self.icon_label.setPixmap(pixmap)
            self.icon_label.setText("")
        else:
            self.icon_label.clear()
            self.icon_label.setText("盘")
        self.icon_label.setToolTip(set_effect_tooltip(game, piece.set_name))
        position_name = game.position_name(piece.position)
        self.position_label.setText(f"{piece.set_name}[{position_name}]")
        self.locked_badge.setText("锁定" if piece.locked else "未锁")
        self.locked_badge.setObjectName("Badge" if piece.locked else "MutedBadge")
        self.locked_badge.style().unpolish(self.locked_badge)
        self.locked_badge.style().polish(self.locked_badge)
        self.level_badge.setText(f"等级 {piece.level}/{game.enhancement.max_level}")
        self.metric_badge.setText(f"有效 {effective}")
        self.set_label.setText(f"槽位：{position_name}    套装：{piece.set_name}")
        self.main_label.setText(f"主属性：{piece.main_stat}")
        substats = _piece_substat_label(piece)
        revealed_next = _piece_revealed_next_substat_label(piece, game)
        substat_display = substats.replace(" / ", "\n")
        self.substat_label.setText(
            f"副属性：\n{substat_display}"
            + (f"\n{revealed_next}" if revealed_next else "")
        )
        self.setToolTip(
            f"{position_name} | {piece.set_name} | {piece.main_stat} +{piece.level}\n"
            f"有效 {effective}\n副属性：{substats}"
            + (f"\n{revealed_next}" if revealed_next else "")
        )
        try:
            score = score_piece(piece, game, character)
        except Exception:
            return
        self.main_label.setStyleSheet(
            "color: #0b57d0; font-weight: 700;"
            if score.main_stat_preferred
            else "color: #b3261e; font-weight: 700;"
        )
        metric_color = {
            "excellent": "#137333",
            "good": "#0b57d0",
            "usable": "#8a5a00",
            "weak": "#b3261e",
        }.get(score.rating, "#56606b")
        self.metric_badge.setStyleSheet(
            f"border-radius: 10px; padding: 3px 9px; font-weight: 700; "
            f"background: #f8fafc; color: {metric_color};"
        )

    def update_empty(self, game: GameRules, position: str | int) -> None:
        position_name = game.position_name(position)
        self.icon_label.clear()
        self.icon_label.setText("+")
        self.icon_label.setToolTip(f"{position_name} 空槽")
        self.position_label.setText(f"{position_name} 空槽")
        self.locked_badge.setText("未录入")
        self.locked_badge.setObjectName("MutedBadge")
        self.locked_badge.style().unpolish(self.locked_badge)
        self.locked_badge.style().polish(self.locked_badge)
        self.level_badge.setText("等级 -")
        self.metric_badge.setText("有效 -")
        self.metric_badge.setStyleSheet("")
        self.set_label.setText("当前没有装备")
        self.main_label.setText("点击录入或从库存装备到这里")
        self.main_label.setStyleSheet("color: #56606b; font-weight: 700;")
        self.substat_label.setText("副属性：-")
        self.setToolTip(f"{position_name} 还没有录入当前装备。")

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._refresh_visual_state()

    @property
    def is_selected(self) -> bool:
        return self._selected

    def set_highlighted(self, highlighted: bool, label: str = "入选") -> None:
        self._highlighted = highlighted
        self.highlight_badge.setText(label)
        self.highlight_badge.setVisible(highlighted)
        self._refresh_visual_state()

    def set_duplicate_warning(self, text: str = "") -> None:
        if text:
            self.duplicate_badge.setText("重复" if text.startswith("完全重复") else "疑似重复")
            self.duplicate_badge.setToolTip(text)
            self.duplicate_badge.setVisible(True)
        else:
            self.duplicate_badge.setToolTip("")
            self.duplicate_badge.setVisible(False)

    def _refresh_visual_state(self) -> None:
        if self._selected and self._highlighted:
            name = "PieceCardHighlightedSelected"
        elif self._selected:
            name = "PieceCardSelected"
        elif self._highlighted:
            name = "PieceCardHighlighted"
        else:
            name = "PieceCard"
        self.setObjectName(name)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.row_index)
        super().mousePressEvent(event)


class AgentCard(QFrame):
    clicked = Signal()

    def __init__(
        self,
        agent: AgentMetadata,
        *,
        selected: bool,
        summary: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.agent = agent
        self._selected = selected
        self.setObjectName("AgentCardSelected" if selected else "AgentCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(280, 158)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(summary)
        self.setStyleSheet(
            "QFrame#AgentCard { border: 1px solid #d7dce2; border-radius: 8px; "
            "background: #ffffff; }"
            "QFrame#AgentCard:hover { border-color: #1a73e8; }"
            "QFrame#AgentCardSelected { border: 2px solid #1a73e8; border-radius: 8px; "
            "background: #e8f0fe; }"
        )

        text_color = "#0b57d0" if selected else "#202124"
        muted_color = "#0b57d0" if selected else "#56606b"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self.image_label = QLabel("图")
        self.image_label.setObjectName("AgentCardImage")
        self.image_label.setFixedSize(96, 124)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = asset_pixmap(agent.card_path or agent.portrait_path, 96, 124)
        if pixmap is not None:
            self.image_label.setPixmap(pixmap)
            self.image_label.setText("")
        self.image_label.setStyleSheet("background: transparent; color: #56606b;")
        layout.addWidget(self.image_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)

        def add_line(text: str, *, style: str, object_name: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName(object_name)
            label.setWordWrap(True)
            label.setStyleSheet(style)
            text_layout.addWidget(label)
            return label

        self.name_label = add_line(
            agent.name,
            style=f"background: transparent; color: {text_color}; font-weight: 900; font-size: 15px;",
            object_name="AgentCardName",
        )
        self.meta_label = add_line(
            f"{agent.rarity} · {agent.attribute} · {agent.specialty}",
            style=f"background: transparent; color: {text_color}; font-weight: 800;",
            object_name="AgentCardMeta",
        )
        if agent.faction and agent.faction != UNKNOWN_LABEL:
            self.faction_label = add_line(
                f"阵营 {agent.faction}",
                style=f"background: transparent; color: {muted_color}; font-weight: 700;",
                object_name="AgentCardFaction",
            )
        if agent.release_version:
            self.version_label = add_line(
                f"实装 {agent.release_version}",
                style=f"background: transparent; color: {muted_color}; font-weight: 700;",
                object_name="AgentCardVersion",
            )
        self.template_label = add_line(
            f"目标模板 {agent.character_preset_id}",
            style=f"background: transparent; color: {muted_color}; font-weight: 700;",
            object_name="AgentCardTemplate",
        )
        text_layout.addStretch(1)
        layout.addLayout(text_layout, 1)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TargetSetOptionCard(QFrame):
    def __init__(
        self,
        game: GameRules,
        set_name: str,
        *,
        selected: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.set_name = set_name
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(280, 150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "QFrame#TargetSetOptionCard { border: 1px solid #d7dce2; border-radius: 8px; background: #ffffff; }"
            "QFrame#TargetSetOptionCard:hover { border-color: #1a73e8; }"
            "QFrame#TargetSetOptionCardSelected { border: 2px solid #1a73e8; border-radius: 8px; background: #e8f0fe; }"
            "QLabel { background: transparent; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        icon_label = QLabel("套")
        icon_label.setFixedSize(40, 40)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = set_icon_pixmap(game, set_name, 36)
        if pixmap is not None:
            icon_label.setPixmap(pixmap)
            icon_label.setText("")
        header.addWidget(icon_label)

        name_label = QLabel(set_name)
        name_label.setWordWrap(True)
        name_label.setStyleSheet("font-weight: 900; font-size: 14px; color: #202124;")
        header.addWidget(name_label, 1)

        self.check = QCheckBox("候选")
        self.check.setChecked(selected)
        self.check.stateChanged.connect(lambda _state: self._refresh_visual_state())
        header.addWidget(self.check)
        root.addLayout(header)

        effect = game.set_effect(set_name)
        two_piece = effect.two_piece if effect and effect.two_piece else "未配置 2 件套效果"
        four_piece = effect.four_piece if effect and effect.four_piece else "未配置 4 件套效果"
        two_label = QLabel(f"2件套：{two_piece}")
        four_label = QLabel(f"4件套：{four_piece}")
        two_label.setWordWrap(True)
        four_label.setWordWrap(True)
        two_label.setStyleSheet("color: #3c4043;")
        four_label.setStyleSheet("color: #56606b;")
        root.addWidget(two_label)
        root.addWidget(four_label)
        self.setToolTip(set_effect_tooltip(game, set_name))
        self._refresh_visual_state()

    def is_selected(self) -> bool:
        return self.check.isChecked()

    def _refresh_visual_state(self) -> None:
        self.setObjectName("TargetSetOptionCardSelected" if self.is_selected() else "TargetSetOptionCard")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.check.setChecked(not self.check.isChecked())
            event.accept()
            return
        super().mousePressEvent(event)


class SubstatDropGroup(QGroupBox):
    reorder_requested = Signal(int, int)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasFormat(SUBSTAT_CARD_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasFormat(SUBSTAT_CARD_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        if not event.mimeData().hasFormat(SUBSTAT_CARD_MIME):
            super().dropEvent(event)
            return
        try:
            source_index = int(bytes(event.mimeData().data(SUBSTAT_CARD_MIME)).decode("ascii"))
        except ValueError:
            return
        target_y = event.position().toPoint().y()
        target_index = self._drop_target_index(target_y)
        self.reorder_requested.emit(source_index, target_index)
        event.acceptProposedAction()

    def _drop_target_index(self, target_y: int) -> int:
        layout = self.layout()
        if layout is None:
            return 0
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget is None:
                continue
            if target_y < widget.geometry().center().y():
                return index
        return layout.count()


class SubstatEditCard(QFrame):
    changed = Signal()
    move_requested = Signal(int, int)

    def __init__(
        self,
        index: int,
        game: GameRules,
        main_stat: str,
        line: SubstatLine,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.game = game
        self.index = index
        self._drag_start_position = None
        self.setObjectName("OverviewCard")
        self.setMinimumHeight(74)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-weight: 800;")
        self.stat_combo = QComboBox()
        self.stat_combo.setMinimumWidth(150)
        self.roll_spin = _configure_step_spinbox(QSpinBox(), 96)
        self.roll_spin.setRange(0, 5)
        self.roll_spin.setPrefix("+")
        self.up_button = QPushButton("上移")
        self.down_button = QPushButton("下移")
        self.clear_button = QPushButton("清空")

        layout.addWidget(self.title_label)
        layout.addWidget(self.stat_combo, 1)
        layout.addWidget(QLabel("强化"))
        layout.addWidget(self.roll_spin)
        layout.addWidget(self.up_button)
        layout.addWidget(self.down_button)
        layout.addWidget(self.clear_button)

        self.stat_combo.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self.roll_spin.valueChanged.connect(lambda _value: self.changed.emit())
        self.up_button.clicked.connect(lambda _checked=False: self.move_requested.emit(self.index, -1))
        self.down_button.clicked.connect(lambda _checked=False: self.move_requested.emit(self.index, 1))
        self.clear_button.clicked.connect(self.clear)

        self.update_options(main_stat, line.stat)
        self.roll_spin.setValue(int(line.rolls))
        self.set_index(index, 4)

    def set_index(self, index: int, total: int) -> None:
        self.index = index
        self.title_label.setText(f"副属性 {index + 1}")
        self.up_button.setEnabled(index > 0)
        self.down_button.setEnabled(index < total - 1)

    def update_options(self, main_stat: str, current: str | None = None) -> None:
        value = current if current is not None else str(self.stat_combo.currentData() or "")
        self.stat_combo.blockSignals(True)
        try:
            self.stat_combo.clear()
            self.stat_combo.addItem("空", "")
            for stat in self.game.sub_stats:
                if stat != main_stat:
                    self.stat_combo.addItem(stat, stat)
            index = self.stat_combo.findData(value)
            self.stat_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.stat_combo.blockSignals(False)

    def clear(self) -> None:
        self.stat_combo.setCurrentIndex(0)
        self.roll_spin.setValue(0)
        self.changed.emit()

    def line(self) -> SubstatLine | None:
        stat = str(self.stat_combo.currentData() or "")
        if not stat:
            return None
        return SubstatLine(stat=stat, rolls=int(self.roll_spin.value()))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_position = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_start_position is None:
            super().mouseMoveEvent(event)
            return
        if not event.buttons() & Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(event)
            return
        distance = (event.position().toPoint() - self._drag_start_position).manhattanLength()
        if distance < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        mime = QMimeData()
        mime.setData(SUBSTAT_CARD_MIME, str(self.index).encode("ascii"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)
        self.setCursor(Qt.CursorShape.OpenHandCursor)


class GearPieceEditDialog(QDialog):
    def __init__(
        self,
        game: GameRules,
        character: CharacterPreset,
        piece: GearPiece,
        editable_position: bool,
        title: str,
        parent: QWidget | None = None,
        optimal_check_callback: Callable[[GearPiece], str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.game = game
        self.character = character
        self.editable_position = editable_position
        self._piece: GearPiece | None = None
        self._selected_set = piece.set_name if piece.set_name in game.sets else (game.sets[0] if game.sets else "")
        self._selected_main = piece.main_stat
        self._optimal_check_callback = optimal_check_callback
        self._set_buttons: dict[str, QPushButton] = {}
        self._main_buttons: dict[str, QPushButton] = {}
        self.substat_cards: list[SubstatEditCard] = []

        self.setWindowTitle(title)
        self.setMinimumSize(1180, 760)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        basic_group = QGroupBox("基础")
        basic_layout = QGridLayout(basic_group)
        basic_layout.setHorizontalSpacing(12)
        basic_layout.setVerticalSpacing(10)

        if editable_position:
            self.position_combo = QComboBox()
            for rule in game.positions:
                self.position_combo.addItem(game.position_name(rule.id), rule.id)
            position_index = self.position_combo.findData(piece.position)
            self.position_combo.setCurrentIndex(position_index if position_index >= 0 else 0)
            self.position_combo.currentIndexChanged.connect(lambda _index: self._position_changed())
            basic_layout.addWidget(QLabel("槽位"), 0, 0)
            basic_layout.addWidget(self.position_combo, 0, 1)
        else:
            self.position_combo = None
            self.position_label = _badge(game.position_name(piece.position))
            self.position_label.setProperty("position_value", piece.position)
            basic_layout.addWidget(QLabel("槽位"), 0, 0)
            basic_layout.addWidget(self.position_label, 0, 1)

        self.level_spin = _configure_step_spinbox(QSpinBox(), 110)
        self.level_spin.setRange(0, game.enhancement.max_level)
        self.level_spin.setSingleStep(game.enhancement.step)
        self.level_spin.setPrefix("+")
        self.level_spin.setValue(int(piece.level))
        self.initial_combo = QComboBox()
        self.initial_combo.addItem("3 条", 3)
        self.initial_combo.addItem("4 条", 4)
        initial_index = self.initial_combo.findData(piece.initial_substat_count)
        self.initial_combo.setCurrentIndex(initial_index if initial_index >= 0 else 1)
        self.locked_checkbox = QCheckBox("锁定当前槽位")
        self.locked_checkbox.setChecked(piece.locked)
        self.revealed_next_combo = QComboBox()
        self.revealed_next_hint = QLabel("仅初始 3 词条且 +3 前可记录；用于条件化强化期望。")
        self.revealed_next_hint.setObjectName("MutedText")
        self.revealed_next_hint.setWordWrap(True)

        basic_layout.addWidget(QLabel("等级"), 0, 2)
        basic_layout.addWidget(self.level_spin, 0, 3)
        basic_layout.addWidget(QLabel("初始词条"), 0, 4)
        basic_layout.addWidget(self.initial_combo, 0, 5)
        basic_layout.addWidget(self.locked_checkbox, 0, 6)
        basic_layout.addWidget(QLabel("预告第4副属性"), 1, 0)
        basic_layout.addWidget(self.revealed_next_combo, 1, 1, 1, 2)
        basic_layout.addWidget(self.revealed_next_hint, 1, 3, 1, 4)
        root.addWidget(basic_group)

        set_group = QGroupBox("套装")
        set_layout = QVBoxLayout(set_group)
        self.set_card_host = QWidget()
        self.set_card_grid = QGridLayout(self.set_card_host)
        self.set_card_grid.setHorizontalSpacing(10)
        self.set_card_grid.setVerticalSpacing(10)
        self.set_card_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._build_set_cards()
        self.set_card_scroll = QScrollArea()
        self.set_card_scroll.setWidgetResizable(True)
        self.set_card_scroll.setWidget(self.set_card_host)
        self.set_card_scroll.setMinimumHeight(245)
        set_layout.addWidget(self.set_card_scroll)
        root.addWidget(set_group, 2)

        main_group = QGroupBox("主属性")
        main_layout = QVBoxLayout(main_group)
        self.main_stat_card_host = QWidget()
        self.main_stat_card_grid = QGridLayout(self.main_stat_card_host)
        self.main_stat_card_grid.setHorizontalSpacing(10)
        self.main_stat_card_grid.setVerticalSpacing(10)
        main_layout.addWidget(self.main_stat_card_host)
        root.addWidget(main_group)

        substat_group = SubstatDropGroup("副属性")
        substat_group.reorder_requested.connect(self._move_substat_card_to_index)
        self.substat_layout = QVBoxLayout(substat_group)
        self.substat_layout.setSpacing(8)
        rows = list(piece.substats[:4]) + [SubstatLine(stat="", rolls=0) for _ in range(4 - len(piece.substats[:4]))]
        for index, line in enumerate(rows):
            card = SubstatEditCard(index, game, self._selected_main, line)
            card.move_requested.connect(self._move_substat_card)
            card.changed.connect(self._refresh_revealed_next_options)
            self.substat_cards.append(card)
            self.substat_layout.addWidget(card)
        root.addWidget(substat_group)
        self._initial_revealed_next_substat = piece.revealed_next_substat or ""
        self.initial_combo.currentIndexChanged.connect(lambda _index: self._refresh_revealed_next_options())
        self.level_spin.valueChanged.connect(lambda _value: self._refresh_revealed_next_options())

        self.check_result_label = QLabel("可在保存前检查这件装备是否进入当前最优搭配；未满级会按满级强化期望估值。")
        self.check_result_label.setWordWrap(True)
        self.check_result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.check_button = QPushButton("检查是否进入当前最优")
        self.check_button.setEnabled(self._optimal_check_callback is not None)
        self.check_button.clicked.connect(self._run_optimal_check)

        check_layout = QHBoxLayout()
        check_layout.addWidget(self.check_button)
        check_layout.addWidget(self.check_result_label, 1)
        root.addLayout(check_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._position_changed()
        self._select_set(self._selected_set)
        self._refresh_revealed_next_options(self._initial_revealed_next_substat)

    @property
    def piece(self) -> GearPiece | None:
        return self._piece

    def _position_value(self) -> Any:
        if self.position_combo is not None:
            return self.position_combo.currentData()
        return self.position_label.property("position_value")

    def _build_set_cards(self) -> None:
        for index, set_name in enumerate(self.game.sets):
            button = QPushButton(_set_card_label(self.game, set_name))
            button.setCheckable(True)
            button.setMinimumSize(240, 92)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            pixmap = set_icon_pixmap(self.game, set_name, 34)
            if pixmap is not None:
                button.setIcon(QIcon(pixmap))
                button.setIconSize(QSize(34, 34))
            button.setToolTip(set_effect_tooltip(self.game, set_name))
            button.clicked.connect(lambda _checked=False, name=set_name: self._select_set(name))
            self._set_buttons[set_name] = button
            self.set_card_grid.addWidget(button, index // 4, index % 4)
        for column in range(4):
            self.set_card_grid.setColumnStretch(column, 1)

    def _allowed_set_names(self) -> set[str]:
        return set(self.game.sets_for_position(self._position_value()))

    def _select_set(self, set_name: str) -> None:
        allowed = self._allowed_set_names()
        if set_name not in allowed:
            set_name = next((name for name in self.game.sets if name in allowed), set_name)
        if set_name not in self._set_buttons and self._set_buttons:
            set_name = next((name for name in self._set_buttons if name in allowed), next(iter(self._set_buttons)))
        self._selected_set = set_name
        for name, button in self._set_buttons.items():
            selected = name == set_name
            enabled = name in allowed
            button.setEnabled(enabled)
            button.setChecked(selected)
            button.setStyleSheet(_set_button_style(selected))

    def _clear_main_stat_cards(self) -> None:
        while self.main_stat_card_grid.count():
            item = self.main_stat_card_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._main_buttons = {}

    def _position_changed(self) -> None:
        position = self._position_value()
        allowed = self.game.main_stats_for(position)
        if self._selected_main not in allowed:
            preferred = self.character.preferred_mains_for(position)
            self._selected_main = next((stat for stat in preferred if stat in allowed), allowed[0])
        self._rebuild_main_stat_cards(allowed)
        self._select_set(self._selected_set)
        self._refresh_substat_options()

    def _rebuild_main_stat_cards(self, allowed: list[str]) -> None:
        self._clear_main_stat_cards()
        for index, stat in enumerate(allowed):
            button = QPushButton(stat)
            button.setCheckable(True)
            button.setMinimumHeight(46)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, value=stat: self._select_main_stat(value))
            self._main_buttons[stat] = button
            self.main_stat_card_grid.addWidget(button, index // 4, index % 4)
        for column in range(4):
            self.main_stat_card_grid.setColumnStretch(column, 1)
        self._select_main_stat(self._selected_main)

    def _select_main_stat(self, stat: str) -> None:
        if stat not in self._main_buttons and self._main_buttons:
            stat = next(iter(self._main_buttons))
        self._selected_main = stat
        for name, button in self._main_buttons.items():
            selected = name == stat
            button.setChecked(selected)
            button.setStyleSheet(_stat_button_style(selected))
        self._refresh_substat_options()
        self._refresh_revealed_next_options()

    def _refresh_substat_options(self) -> None:
        if not self.substat_cards:
            return
        for card in self.substat_cards:
            card.update_options(self._selected_main)

    def _current_substat_lines(self) -> list[SubstatLine]:
        return [line for card in self.substat_cards if (line := card.line()) is not None]

    def _revealed_next_eligible(self) -> bool:
        return (
            self.game.enhancement.revealed_next_substat_supported
            and
            int(self.initial_combo.currentData() or 0) == 3
            and int(self.level_spin.value()) < self.game.enhancement.initial_add_level
            and len(self._current_substat_lines()) == 3
        )

    def _refresh_revealed_next_options(self, preferred: str | None = None) -> None:
        current = preferred
        if current is None:
            current = str(self.revealed_next_combo.currentData() or "")
        existing = [line.stat for line in self._current_substat_lines()]
        available = self.game.available_substats(self._selected_main, existing)
        self.revealed_next_combo.blockSignals(True)
        try:
            self.revealed_next_combo.clear()
            self.revealed_next_combo.addItem("不记录", "")
            for stat in available:
                self.revealed_next_combo.addItem(stat, stat)
            index = self.revealed_next_combo.findData(current)
            self.revealed_next_combo.setCurrentIndex(index if index >= 0 else 0)
            eligible = self._revealed_next_eligible()
            self.revealed_next_combo.setEnabled(eligible)
            if not self.game.enhancement.revealed_next_substat_supported:
                hint = "当前游戏不支持记录预告第 4 副属性。"
            elif eligible:
                hint = "已启用：强化期望会固定使用这个第 4 副属性。"
            else:
                hint = "仅初始 3 词条、+3 前、已填写 3 条副属性时可记录；用于条件化强化期望。"
            self.revealed_next_hint.setText(hint)
        finally:
            self.revealed_next_combo.blockSignals(False)

    def _move_substat_card(self, index: int, offset: int) -> None:
        self._move_substat_card_to_index(index, index + offset)

    def _move_substat_card_to_index(self, index: int, target: int) -> None:
        if index < 0 or index >= len(self.substat_cards):
            return
        target = max(0, min(target, len(self.substat_cards) - 1))
        if index == target:
            return
        cards = list(self.substat_cards)
        card = cards.pop(index)
        cards.insert(target, card)
        self.substat_cards = cards
        for card_index, card in enumerate(self.substat_cards):
            card.set_index(card_index, len(self.substat_cards))
            self.substat_layout.removeWidget(card)
            self.substat_layout.addWidget(card)

    def _build_piece(self) -> GearPiece:
        substats = self._current_substat_lines()
        revealed_next_substat = (
            str(self.revealed_next_combo.currentData() or "") or None
            if self._revealed_next_eligible()
            else None
        )
        return GearPiece(
            position=self._position_value(),
            set_name=self._selected_set,
            main_stat=self._selected_main,
            level=int(self.level_spin.value()),
            initial_substat_count=int(self.initial_combo.currentData()),
            locked=self.locked_checkbox.isChecked(),
            substats=substats,
            revealed_next_substat=revealed_next_substat,
        )

    def _collect_piece(self) -> GearPiece:
        piece = self._build_piece()
        validate_gear_piece_against_game(piece, self.game)
        return piece

    def _run_optimal_check(self) -> None:
        if self._optimal_check_callback is None:
            return
        try:
            piece = self._collect_piece()
            self.check_result_label.setText(self._optimal_check_callback(piece))
        except Exception as exc:
            self.check_result_label.setText(f"当前编辑内容还不能检查：{exc}")

    def accept(self) -> None:  # type: ignore[override]
        try:
            piece = self._build_piece()
        except Exception as exc:
            QMessageBox.warning(self, "装备无法保存", str(exc))
            return

        consistency_errors, consistency_warnings = gear_piece_entry_consistency_issues(
            piece,
            self.game,
        )
        if consistency_errors:
            QMessageBox.warning(
                self,
                "装备配置不匹配",
                "当前强化配置和已填写副属性不匹配：\n\n"
                + "\n".join(f"- {item}" for item in consistency_errors),
            )
            return
        try:
            validate_gear_piece_against_game(piece, self.game)
        except Exception as exc:
            QMessageBox.warning(self, "装备无法保存", str(exc))
            return
        if consistency_warnings:
            answer = QMessageBox.question(
                self,
                "确认保存装备？",
                "当前强化配置和已填写副属性不完全匹配：\n\n"
                + "\n".join(f"- {item}" for item in consistency_warnings)
                + "\n\n仍然保存吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._piece = piece
        super().accept()


class TargetTemplateEditDialog(QDialog):
    def __init__(
        self,
        game: GameRules,
        character: CharacterPreset,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.game = game
        self.character = character
        self.template: CharacterPreset | None = None
        self.setWindowTitle("编辑目标模板规则：主属性目标 / 套装结构 / 副属性排序")
        self.resize(900, 720)
        root = QVBoxLayout(self)

        scope_label = QLabel(
            "目标模板不是装备模板，也不会生成或保存任何装备；当前装备和库存请在对应区域维护。"
            "这里仅定义计算目标规则：每个位置期望的主属性、期望达成的 4+2/2+2+2 套装结构、"
            "副属性有效排序和并列关系。"
        )
        scope_label.setWordWrap(True)
        scope_label.setObjectName("MutedText")
        root.addWidget(scope_label)

        form = QFormLayout()
        self.name_edit = QLineEdit(character.name)
        form.addRow("目标规则名称", self.name_edit)
        root.addLayout(form)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        main_group = QGroupBox("主属性目标（按位置）")
        main_grid = QGridLayout(main_group)
        self.main_stat_checks: dict[str, list[QCheckBox]] = {}
        for row_index, rule in enumerate(game.positions):
            key = position_key(rule.id)
            main_grid.addWidget(QLabel(game.position_name(rule.id)), row_index, 0)
            checks: list[QCheckBox] = []
            preferred = set(character.preferred_mains_for(rule.id))
            for column_index, stat in enumerate(rule.main_stats, start=1):
                check = QCheckBox(stat)
                check.setChecked(stat in preferred)
                checks.append(check)
                main_grid.addWidget(check, row_index, column_index)
            self.main_stat_checks[key] = checks
        content_layout.addWidget(main_group)

        set_group = QGroupBox("目标套装结构（4+2 / 2+2+2）")
        set_layout = QVBoxLayout(set_group)
        set_layout.addWidget(
            QLabel("每行是一条目标件数要求；同一行多个候选套装用 / 分隔，表示都可满足这条 2 件或 4 件目标。")
        )
        self.plan_name_edit = QLineEdit(character.active_set_plan().name if character.active_set_plan() else "自定义目标")
        set_layout.addWidget(self.plan_name_edit)
        set_grid = QGridLayout()
        set_grid.addWidget(QLabel("本条目标允许的套装"), 0, 0)
        set_grid.addWidget(QLabel("件数"), 0, 1)
        set_grid.addWidget(QLabel("操作"), 0, 2)
        self.set_requirement_rows: list[tuple[QLineEdit, QComboBox]] = []
        requirements = list(character.active_set_plan().requirements) if character.active_set_plan() else []
        for index in range(3):
            set_edit = QLineEdit()
            set_edit.setPlaceholderText("例如：云岿如我 或 啄木鸟电音 / 河豚电音")
            count_combo = QComboBox()
            for value, label in [(0, "不使用"), (2, "2 件"), (4, "4 件")]:
                count_combo.addItem(label, value)
            if index < len(requirements):
                requirement = requirements[index]
                set_edit.setText(" / ".join(requirement.set_names))
                count_index = count_combo.findData(requirement.pieces)
                count_combo.setCurrentIndex(count_index if count_index >= 0 else 0)
            choose_button = QPushButton("选择")
            choose_button.clicked.connect(lambda _checked=False, edit=set_edit: self._choose_set_names(edit))
            self.set_requirement_rows.append((set_edit, count_combo))
            set_grid.addWidget(set_edit, index + 1, 0)
            set_grid.addWidget(count_combo, index + 1, 1)
            set_grid.addWidget(choose_button, index + 1, 2)
        set_layout.addLayout(set_grid)
        content_layout.addWidget(set_group)

        substat_group = QGroupBox("副属性目标排序（支持并列）")
        substat_layout = QVBoxLayout(substat_group)
        substat_layout.addWidget(QLabel("rank=1 最优先；rank=0 表示不计入有效词条；相同 rank 表示并列，例如 A=B>C=D。"))
        self.substat_preview_label = QLabel("")
        self.substat_preview_label.setWordWrap(True)
        self.substat_preview_label.setObjectName("MutedText")
        substat_layout.addWidget(self.substat_preview_label)
        substat_grid = QGridLayout()
        substat_grid.addWidget(QLabel("副属性"), 0, 0)
        substat_grid.addWidget(QLabel("rank"), 0, 1)
        self.substat_rank_spins: dict[str, QSpinBox] = {}
        for index, stat in enumerate(game.sub_stats, start=1):
            rank = character.priority_rank_for(stat) or 0
            spin = _configure_step_spinbox(QSpinBox(), 104)
            spin.setRange(0, max(len(game.sub_stats), rank, 1))
            spin.setValue(rank)
            spin.valueChanged.connect(lambda _value: self._refresh_substat_preview())
            self.substat_rank_spins[stat] = spin
            substat_grid.addWidget(QLabel(stat), index, 0)
            substat_grid.addWidget(spin, index, 1)
        substat_layout.addLayout(substat_grid)
        content_layout.addWidget(substat_group)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._refresh_substat_preview()

    def _preferred_main_stats(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for key, checks in self.main_stat_checks.items():
            values = [check.text() for check in checks if check.isChecked()]
            if values:
                result[key] = values
        return result

    def _missing_main_target_position_names(self) -> list[str]:
        missing: list[str] = []
        for rule in self.game.positions:
            key = position_key(rule.id)
            checks = self.main_stat_checks.get(key, [])
            if checks and not any(check.isChecked() for check in checks):
                missing.append(self.game.position_name(rule.id))
        return missing

    def _confirm_missing_main_targets(self) -> bool:
        missing = self._missing_main_target_position_names()
        if not missing:
            return True
        answer = QMessageBox.question(
            self,
            "主属性目标未完整配置",
            (
                "以下位置没有选择任何主属性目标：\n"
                + "、".join(missing)
                + "\n\n保存后这些位置会按“不限制主属性”计算。"
                "如果这是漏勾，请取消后补上；如果是有意放宽目标，可以继续保存。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_unrestricted_set_plan(self, plan: SetPlan) -> bool:
        if not plan.is_unrestricted:
            return True
        answer = QMessageBox.question(
            self,
            "套装目标为空",
            (
                "当前没有启用任何套装目标；保存后 Action EV 和当前最优搭配会按“不限套装”计算，"
                "不会强制 4+2 或 2+2+2。\n\n"
                "如果这是漏配，请取消后配置套装目标；如果是有意调试不限套装，可以继续保存。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _ignored_set_target_rows(self) -> list[str]:
        ignored: list[str] = []
        for set_edit, count_combo in self.set_requirement_rows:
            pieces = int(count_combo.currentData() or 0)
            text = set_edit.text().strip()
            if pieces <= 0 and text:
                ignored.append(text)
        return ignored

    def _confirm_ignored_set_target_rows(self) -> bool:
        ignored = self._ignored_set_target_rows()
        if not ignored:
            return True
        answer = QMessageBox.question(
            self,
            "套装目标行未启用",
            (
                "以下套装目标行填写了套装，但件数仍是“不使用”，保存时会被忽略：\n"
                + "；".join(ignored)
                + "\n\n如果这是漏选件数，请取消后改成 2 件或 4 件；如果是有意暂不使用，可以继续保存。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _set_plan(self) -> SetPlan:
        requirements: list[SetRequirement] = []
        seen_sets: set[str] = set()
        game_sets = set(self.game.sets)
        for set_edit, count_combo in self.set_requirement_rows:
            pieces = int(count_combo.currentData() or 0)
            if pieces <= 0:
                continue
            set_names = self._set_names_from_text(set_edit.text())
            if not set_names:
                raise ValueError("套装结构里有启用的行没有填写目标套装。")
            unknown_sets = sorted(set(set_names) - game_sets)
            if unknown_sets:
                raise ValueError(f"套装结构包含未知套装：{', '.join(unknown_sets)}")
            duplicate_sets = [set_name for set_name in set_names if set_name in seen_sets]
            if duplicate_sets:
                raise ValueError(f"套装结构里重复选择了 {', '.join(duplicate_sets)}")
            seen_sets.update(set_names)
            requirements.append(SetRequirement(set_names=set_names, pieces=pieces))
        total = sum(requirement.pieces for requirement in requirements)
        if total not in {0, len(self.game.positions)}:
            raise ValueError(f"套装结构件数总和应为 0 或 {len(self.game.positions)}，当前为 {total}")
        return SetPlan(
            id="user_target_plan",
            name=self.plan_name_edit.text().strip() or "自定义目标",
            requirements=requirements,
        )

    def _set_names_from_text(self, text: str) -> list[str]:
        return list(
            dict.fromkeys(
                value.strip()
                for value in text.replace("，", "/").replace(",", "/").split("/")
                if value.strip()
            )
        )

    def _choose_set_names(self, set_edit: QLineEdit) -> None:
        selected = set(self._set_names_from_text(set_edit.text()))
        dialog = QDialog(self)
        dialog.setWindowTitle("选择目标套装（用于套装结构）")
        dialog.resize(900, 680)
        root = QVBoxLayout(dialog)
        note = QLabel(
            "可多选：同一行多个套装表示都能满足这条 2 件或 4 件目标；"
            "这里不是选择当前装备套装。点卡片或勾选框切换。"
        )
        note.setWordWrap(True)
        note.setObjectName("MutedText")
        root.addWidget(note)

        card_host = QWidget()
        card_grid = QGridLayout(card_host)
        card_grid.setHorizontalSpacing(10)
        card_grid.setVerticalSpacing(10)
        card_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        cards: list[TargetSetOptionCard] = []
        for index, set_name in enumerate(self.game.sets):
            card = TargetSetOptionCard(self.game, set_name, selected=set_name in selected)
            cards.append(card)
            card_grid.addWidget(card, index // 2, index % 2)
        for column in range(2):
            card_grid.setColumnStretch(column, 1)
        card_grid.setRowStretch((len(cards) + 1) // 2, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(card_host)
        root.addWidget(scroll, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = [card.set_name for card in cards if card.is_selected()]
        set_edit.setText(" / ".join(chosen))

    def _substat_priority(self) -> SubstatPriority:
        tiers: dict[int, list[str]] = {}
        for stat, spin in self.substat_rank_spins.items():
            rank = int(spin.value())
            if rank > 0:
                tiers.setdefault(rank, []).append(stat)
        ordered_tiers = [tiers[rank] for rank in sorted(tiers)]
        return SubstatPriority(core=ordered_tiers, usable=[])

    def _refresh_substat_preview(self) -> None:
        tiers: dict[int, list[str]] = {}
        for stat, spin in self.substat_rank_spins.items():
            rank = int(spin.value())
            if rank > 0:
                tiers.setdefault(rank, []).append(stat)
        ordered_tiers = [tiers[rank] for rank in sorted(tiers)]
        text = _priority_tiers_text(ordered_tiers) or "未选择有效副属性"
        self.substat_preview_label.setText(f"当前副属性有效排序：{text}")

    def accept(self) -> None:
        try:
            if not self._confirm_ignored_set_target_rows():
                return
            plan = self._set_plan()
            priority = self._substat_priority()
            if not priority.core:
                raise ValueError("至少选择一个有效副属性 rank。")
            if not self._confirm_unrestricted_set_plan(plan):
                return
            if not self._confirm_missing_main_targets():
                return
            target_set = plan.requirements[0].primary_set if plan.requirements else self.character.target_set
            existing_plans = [
                item for item in self.character.set_plans if item.id != plan.id
            ]
            self.template = self.character.model_copy(
                update={
                    "name": self.name_edit.text().strip() or self.character.name,
                    "target_set": target_set,
                    "preferred_main_stats": self._preferred_main_stats(),
                    "substat_priority": priority,
                    "effective_substats": {},
                    "set_plans": [plan, *existing_plans],
                    "default_set_plan": plan.id,
                }
            )
            self.template = CharacterPreset.model_validate(
                self.template.model_dump(mode="json", exclude_none=True)
            )
        except Exception as exc:
            QMessageBox.warning(self, "目标模板无法保存", str(exc))
            return
        super().accept()


class ActionEvWorker(QObject):
    progress = Signal(dict)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        game: GameRules,
        character: CharacterPreset,
        probability_model: ProbabilityModel,
        current_pieces: list[GearPiece],
        inventory_pieces: list[GearPiece],
        horizon: int,
        engine: str = DEFAULT_ACTION_EV_ENGINE,
    ) -> None:
        super().__init__()
        self.game = game
        self.character = character
        self.probability_model = probability_model
        self.current_pieces = current_pieces
        self.inventory_pieces = inventory_pieces
        self.horizon = horizon
        self.engine = normalize_action_ev_engine(engine)

    @Slot()
    def run(self) -> None:
        try:
            analysis = analyse_current_gear(self.current_pieces, self.game, self.character)
            rows = position_strategy_efficiency_rows(
                self.game,
                self.character,
                self.probability_model,
                analysis,
                inventory_pieces=[*self.current_pieces, *self.inventory_pieces],
                horizon=self.horizon,
                progress_callback=lambda payload: self.progress.emit(dict(payload)),
                use_state_dp=self.engine == "state_dp",
            )
            self.finished.emit(rows)
        except Exception:
            self.failed.emit(traceback.format_exc())


class _TransientPopupGuard(QObject):
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() in {QEvent.Type.ToolTip, QEvent.Type.WhatsThis}:
            return True
        if (
            _transient_popups_suppressed()
            and event.type() in {QEvent.Type.Show, QEvent.Type.ShowToParent}
            and isinstance(obj, QWidget)
        ):
            combo = _combo_popup_owner(obj)
            if combo is not None:
                combo.hidePopup()
                obj.hide()
                QTimer.singleShot(0, _hide_transient_popups)
                return True
        if (
            _transient_popups_suppressed()
            and event.type() in {QEvent.Type.Show, QEvent.Type.ShowToParent}
            and isinstance(obj, QWidget)
            and _is_transient_popup_widget(obj)
        ):
            obj.hide()
            QTimer.singleShot(0, _hide_transient_popups)
            return True
        return super().eventFilter(obj, event)


def _combo_popup_owner(widget: QWidget) -> QComboBox | None:
    app = QApplication.instance()
    if app is None:
        return None
    for candidate in app.allWidgets():
        if not isinstance(candidate, QComboBox):
            continue
        view = candidate.view()
        if view is None:
            continue
        if widget is view:
            return candidate
        if view.isAncestorOf(widget):
            return candidate
        view_window = view.window()
        if view_window is None or view_window is candidate.window():
            continue
        if widget is view_window or view_window.isAncestorOf(widget):
            return candidate
    return None


def _transient_popups_suppressed() -> bool:
    return time.monotonic() < _TRANSIENT_POPUP_SUPPRESS_UNTIL


def _is_transient_popup_widget(widget: QWidget) -> bool:
    if isinstance(widget, (QComboBox, QDialog, QMainWindow)):
        return False
    class_name = widget.metaObject().className()
    if class_name in _TRANSIENT_POPUP_CLASS_NAMES:
        return True
    return widget.windowType() in {Qt.WindowType.Popup, Qt.WindowType.ToolTip}


def _hide_transient_popups() -> None:
    QToolTip.hideText()
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.allWidgets():
        if isinstance(widget, QComboBox):
            widget.hidePopup()
            view = widget.view()
            if view is not None:
                view.hide()
                view_window = view.window()
                if view_window is not None and view_window.windowType() in {
                    Qt.WindowType.Popup,
                    Qt.WindowType.ToolTip,
                }:
                    view_window.hide()
    popup = app.activePopupWidget()
    if popup is not None:
        popup.hide()
    for widget in app.allWidgets():
        if isinstance(widget, QWidget) and widget.isVisible() and _is_transient_popup_widget(widget):
            widget.hide()
    for widget in app.topLevelWidgets():
        if not widget.isVisible():
            continue
        if _is_transient_popup_widget(widget):
            widget.hide()


def _suppress_transient_popups(duration_ms: int = 1800) -> None:
    global _TRANSIENT_POPUP_SUPPRESS_UNTIL
    _disable_transient_popup_effects()
    until = time.monotonic() + max(duration_ms, 0) / 1000
    _TRANSIENT_POPUP_SUPPRESS_UNTIL = max(_TRANSIENT_POPUP_SUPPRESS_UNTIL, until)
    _hide_transient_popups()
    for delay in (0, 50, 120, 250, 600, 1000, 1400, 1800):
        if delay <= duration_ms:
            QTimer.singleShot(delay, _hide_transient_popups)


def _install_transient_popup_guard() -> None:
    global _TRANSIENT_POPUP_GUARD
    _disable_transient_popup_effects()
    app = QApplication.instance()
    if app is None or _TRANSIENT_POPUP_GUARD is not None:
        return
    _TRANSIENT_POPUP_GUARD = _TransientPopupGuard(app)
    app.installEventFilter(_TRANSIENT_POPUP_GUARD)


class OptimizerWindow(QMainWindow):
    def __init__(self, width: int = 1500, height: int = 950) -> None:
        super().__init__()
        _install_transient_popup_guard()
        self.setWindowTitle("gacha-gear-optimizer")
        self.resize(width, height)
        self.setStyleSheet(APP_QSS)
        self.games = load_games()
        self.characters: list[CharacterPreset] = []
        self.agents: list[AgentMetadata] = []
        self._selected_agent_id_by_game: dict[str, str] = {}
        self._target_template_source_by_id: dict[str, str] = {}
        self._target_template_source_agent_by_id: dict[str, str] = {}
        self.probabilities: list[ProbabilityModel] = []
        self.current_confirmed_digest: str | None = None
        self._results_stale = True
        self._has_calculated_once = False
        self._last_weakest_label = "-"
        self._last_recommended_action_summary = "尚未计算"
        self._last_main_metric_summary = "-"
        self._last_action_engine = DEFAULT_ACTION_EV_ENGINE
        self._last_action_execution_mode = "-"
        self._inventory_loaded_storage_id = ""
        self._loaded_current_snapshot_id = ""
        self._loaded_current_snapshot_storage_id = ""
        self._worker_thread: QThread | None = None
        self._worker: ActionEvWorker | None = None
        self._action_process: QProcess | None = None
        self._action_process_cancel_requested = False
        self._action_run_dir: str | None = None
        self._action_input_path: str | None = None
        self._action_output_path: str | None = None
        self._action_progress_path: str | None = None
        self._action_error_path: str | None = None
        self._action_summary_path: str | None = None
        self._action_progress_offset = 0
        self._action_progress_started_at: float | None = None
        self._action_progress_current_unit_started_at: float | None = None
        self._action_progress_current_unit_key: tuple[Any, ...] | None = None
        self._action_progress_last_unit_done_at: float | None = None
        self._action_progress_last_total = 0.0
        self._action_progress_plan_expanded = False
        self._action_progress_percent = 0
        self._last_action_progress_payload: dict[str, Any] = {}
        self._last_action_progress_seen_at: float | None = None
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(400)
        self._progress_timer.timeout.connect(self._refresh_action_progress_clock)
        self._action_result_rows: list[dict[str, Any]] = []
        self._show_all_action_rows = False

        self.game_combo = QComboBox()
        self.character_combo = QComboBox()
        self.probability_combo = QComboBox()
        self.edit_target_template_button = QPushButton("编辑目标模板")
        self.edit_target_template_button.setToolTip(
            "编辑目标模板：每个位置期望主属性、4+2/2+2+2 套装结构、副属性有效排序；不保存装备。"
        )
        self.delete_target_template_button = QPushButton("删除自定义目标模板")
        self.delete_target_template_button.setToolTip("只删除自定义目标模板；不会删除库存或当前装备快照。")
        self.target_template_summary_label = QLabel("-")
        self.target_template_summary_label.setWordWrap(True)
        self.agent_button = QPushButton("选择代理人")
        self.agent_summary_label = QLabel("未选择代理人")
        self.agent_summary_label.setWordWrap(True)
        self.current_table = GearTable(editable_positions=False, row_label_prefix="当前")
        self.inventory_table = GearTable(editable_positions=True, row_label_prefix="库存")
        self.current_cards: list[PieceCard] = []
        self.inventory_cards: list[PieceCard] = []
        self._selected_inventory_source_row_value: int | None = None
        self._highlighted_inventory_source_rows: set[int] = set()
        self._highlighted_inventory_label = "入选"
        self.overview_game_label = QLabel("-")
        self.overview_character_label = QLabel("-")
        self.overview_probability_label = QLabel("-")
        self.overview_confirm_label = _badge("未确认", muted=True)
        self.overview_inventory_label = _badge("库存 0 件", muted=True)
        self.overview_stale_label = _badge("结果未生成", muted=True)
        self.overview_weakest_label = QLabel("-")
        self.overview_action_label = QLabel("尚未计算")
        self.overview_action_label.setWordWrap(True)
        self.overview_metric_label = QLabel("-")
        self.overview_metric_label.setWordWrap(True)
        self.overview_guide_label = QLabel(
            "先确认目标模板（位置主属性、套装结构、副属性有效排序），再维护库存与当前装备；确认当前装备后再计算最优搭配或 Action EV。"
        )
        self.overview_guide_label.setWordWrap(True)
        self.input_audit_label = QLabel("-")
        self.input_audit_label.setWordWrap(True)
        self.input_audit_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.result_input_audit_label = QLabel("-")
        self.result_input_audit_label.setWordWrap(True)
        self.result_input_audit_label.setObjectName("MutedText")
        self.result_input_audit_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.copy_input_audit_button = QPushButton("复制输入审计")
        self.copy_result_input_audit_button = QPushButton("复制本次输入口径")
        self.current_template_combo = QComboBox()
        self.load_current_template_button = QPushButton("载入快照")
        self.confirm_button = QPushButton("确认当前装备")
        self.save_current_button = QPushButton("保存为快照")
        self.rename_current_template_button = QPushButton("重命名快照")
        self.delete_current_template_button = QPushButton("删除快照")
        self.load_example_button = QPushButton("载入示例当前装备")
        self.add_inventory_button = QPushButton("添加库存件")
        self.copy_inventory_button = QPushButton("复制选中库存")
        self.clear_substats_button = QPushButton("清空选中副词条")
        self.delete_inventory_button = QPushButton("删除选中库存件")
        self.save_inventory_button = QPushButton("保存库存到本机")
        self.export_inventory_button = QPushButton("导出完整明细")
        self.position_filter = QComboBox()
        self.set_filter = QComboBox()
        self.main_filter = QComboBox()
        self.target_set_filter = QCheckBox("只看目标套装")
        self.weak_position_filter = QCheckBox("只看当前弱位")
        self.unfinished_filter = QCheckBox("只看未满级胚子")
        self.replaceable_filter = QCheckBox("只看可替换当前")
        self.duplicate_filter = QCheckBox("只看重复库存")
        self.clear_inventory_filters_button = QPushButton("清除筛选")
        self.inventory_summary_table = QTableWidget()
        self.inventory_card_status_label = QLabel("库存会以卡片展示，点卡片查看完整明细。")
        self.inventory_card_status_label.setWordWrap(True)
        self.inventory_card_host = QWidget()
        self.inventory_card_grid = QGridLayout(self.inventory_card_host)
        self.inventory_card_grid.setHorizontalSpacing(12)
        self.inventory_card_grid.setVerticalSpacing(12)
        self.inventory_card_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.inventory_card_scroll = QScrollArea()
        self.inventory_card_scroll.setWidgetResizable(True)
        self.inventory_card_scroll.setWidget(self.inventory_card_host)
        self.inventory_detail_label = QLabel("库存为空。")
        self.inventory_detail_label.setWordWrap(True)
        self.best_button = QPushButton("计算当前最优搭配（含强化期望）")
        self.action_button = QPushButton("计算调律建议")
        self.portfolio_button = QPushButton("BOX 决策/多代理人审计")
        self.cancel_action_button = QPushButton("取消计算")
        self.cancel_action_button.setEnabled(False)
        self.horizon_combo = QComboBox()
        self.horizon_note_label = QLabel("horizon=1 为完整概率分布精确计算。")
        self.horizon_note_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ActionProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumHeight(36)
        self.progress_bar.setFormat("精确计算 0%")
        self.progress_label = QLabel("当前装备未确认。")
        self.progress_label.setObjectName("ProgressTitle")
        self.progress_label.setWordWrap(True)
        self.progress_meter_label = QLabel("")
        self.progress_meter_label.setObjectName("ProgressMeter")
        self.progress_meter_label.setWordWrap(True)
        self.progress_detail_label = QLabel("")
        self.progress_detail_label.setObjectName("ProgressDetail")
        self.progress_detail_label.setWordWrap(True)
        self.progress_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.tabs = QTabWidget()
        self.result_tabs = QTabWidget()
        self.result_recommend_icon = QLabel("")
        self.result_recommend_icon.setFixedSize(38, 38)
        self.result_recommend_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_recommend_title = QLabel("暂无推荐")
        self.result_recommend_title.setStyleSheet("font-weight: 800; font-size: 17px;")
        self.result_recommend_detail = QLabel("计算 Action EV 后会在这里显示调律推荐或库存升级机会。")
        self.result_recommend_detail.setWordWrap(True)
        self.best_table = QTableWidget()
        self.action_table = QTableWidget()
        self.action_loadout_table = QTableWidget()
        self.action_plan_summary_label = QLabel("尚无 H=2 方案。")
        self.action_plan_summary_label.setWordWrap(True)
        self.action_plan_branch_table = QTableWidget()
        self.action_plan_loadout_table = QTableWidget()
        self.portfolio_status_label = QLabel("尚无 BOX 多代理人审计结果。")
        self.portfolio_status_label.setWordWrap(True)
        self.portfolio_table = QTableWidget()
        self.action_table_status_label = QLabel("尚无 Action EV 明细。")
        self.action_table_status_label.setWordWrap(True)
        self.show_all_actions_button = QPushButton("显示全部")
        self.show_all_actions_button.setEnabled(False)
        self.log_toggle_button = QPushButton("显示运行日志")
        self.log_toggle_button.setCheckable(True)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setVisible(False)

        self._build_ui()
        self._connect_signals()
        self._update_horizon_note()
        self._load_games()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        selectors = QGroupBox("基础配置")
        form = QFormLayout(selectors)
        form.addRow("游戏", self.game_combo)
        agent_row = QWidget()
        agent_layout = QHBoxLayout(agent_row)
        agent_layout.setContentsMargins(0, 0, 0, 0)
        agent_layout.addWidget(self.agent_button)
        agent_layout.addWidget(self.agent_summary_label, 1)
        form.addRow("代理人", agent_row)
        target_row = QWidget()
        target_layout = QHBoxLayout(target_row)
        target_layout.setContentsMargins(0, 0, 0, 0)
        target_layout.addWidget(self.character_combo, 1)
        target_layout.addWidget(self.edit_target_template_button)
        target_layout.addWidget(self.delete_target_template_button)
        form.addRow("目标模板（主属性 / 套装 / 副属性排序）", target_row)
        form.addRow("计算目标摘要", self.target_template_summary_label)
        form.addRow("概率模型", self.probability_combo)
        layout.addWidget(selectors)

        overview_page = QWidget()
        overview_layout = QVBoxLayout(overview_page)
        status_group = QGroupBox("总览")
        status_layout = QGridLayout(status_group)
        status_layout.addWidget(QLabel("游戏"), 0, 0)
        status_layout.addWidget(self.overview_game_label, 0, 1)
        status_layout.addWidget(QLabel("代理人 / 目标模板"), 0, 2)
        status_layout.addWidget(self.overview_character_label, 0, 3)
        status_layout.addWidget(QLabel("概率模型"), 0, 4)
        status_layout.addWidget(self.overview_probability_label, 0, 5)
        status_layout.addWidget(QLabel("当前装备"), 1, 0)
        status_layout.addWidget(self.overview_confirm_label, 1, 1)
        status_layout.addWidget(QLabel("库存"), 1, 2)
        status_layout.addWidget(self.overview_inventory_label, 1, 3)
        status_layout.addWidget(QLabel("结果状态"), 1, 4)
        status_layout.addWidget(self.overview_stale_label, 1, 5)
        status_layout.addWidget(QLabel("当前最弱位置"), 2, 0)
        status_layout.addWidget(self.overview_weakest_label, 2, 1, 1, 5)
        overview_layout.addWidget(status_group)

        recommendation_group = QGroupBox("推荐摘要")
        recommendation_layout = QVBoxLayout(recommendation_group)
        recommendation_layout.addWidget(self.overview_action_label)
        recommendation_layout.addWidget(self.overview_metric_label)
        recommendation_layout.addWidget(self.overview_guide_label)
        overview_layout.addWidget(recommendation_group)
        input_audit_group = QGroupBox("计算输入审计")
        input_audit_layout = QVBoxLayout(input_audit_group)
        input_audit_actions = QHBoxLayout()
        input_audit_actions.addStretch(1)
        input_audit_actions.addWidget(self.copy_input_audit_button)
        input_audit_layout.addLayout(input_audit_actions)
        input_audit_layout.addWidget(self.input_audit_label)
        overview_layout.addWidget(input_audit_group)
        overview_layout.addStretch(1)
        self.tabs.addTab(overview_page, "总览")

        inventory_page = QWidget()
        inventory_page_layout = QVBoxLayout(inventory_page)
        inventory_group = QGroupBox("背包库存（未装备盘）")
        inventory_layout = QVBoxLayout(inventory_group)
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("位置"))
        filter_layout.addWidget(self.position_filter)
        filter_layout.addWidget(QLabel("套装"))
        filter_layout.addWidget(self.set_filter)
        filter_layout.addWidget(QLabel("主属性"))
        filter_layout.addWidget(self.main_filter)
        filter_layout.addWidget(self.target_set_filter)
        filter_layout.addWidget(self.weak_position_filter)
        filter_layout.addWidget(self.unfinished_filter)
        filter_layout.addWidget(self.replaceable_filter)
        filter_layout.addWidget(self.duplicate_filter)
        filter_layout.addWidget(self.clear_inventory_filters_button)
        filter_layout.addStretch(1)
        inventory_layout.addLayout(filter_layout)
        self.inventory_summary_table.setVisible(False)
        inventory_layout.addWidget(self.inventory_card_status_label)
        inventory_layout.addWidget(self.inventory_card_scroll, 1)
        detail_group = QGroupBox("副词条详情")
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.addWidget(self.inventory_detail_label)
        inventory_layout.addWidget(detail_group)
        inventory_buttons = QHBoxLayout()
        inventory_buttons.addWidget(self.add_inventory_button)
        inventory_buttons.addWidget(self.copy_inventory_button)
        inventory_buttons.addWidget(self.clear_substats_button)
        inventory_buttons.addWidget(self.delete_inventory_button)
        inventory_buttons.addWidget(self.save_inventory_button)
        inventory_buttons.addWidget(self.export_inventory_button)
        inventory_buttons.addStretch(1)
        inventory_layout.addLayout(inventory_buttons)
        inventory_page_layout.addWidget(inventory_group)
        self.tabs.addTab(inventory_page, "库存")

        current_page = QWidget()
        current_page_layout = QVBoxLayout(current_page)
        current_group = QGroupBox("当前装备（身上 6 件）")
        current_layout = QVBoxLayout(current_group)
        template_group = QGroupBox("当前装备快照")
        template_layout = QHBoxLayout(template_group)
        template_layout.addWidget(QLabel("已保存快照"))
        template_layout.addWidget(self.current_template_combo, 1)
        template_layout.addWidget(self.load_current_template_button)
        template_layout.addWidget(self.save_current_button)
        template_layout.addWidget(self.rename_current_template_button)
        template_layout.addWidget(self.delete_current_template_button)
        template_layout.addWidget(self.load_example_button)
        current_layout.addWidget(template_group)
        self.current_card_grid = QGridLayout()
        self.current_card_grid.setHorizontalSpacing(12)
        self.current_card_grid.setVerticalSpacing(12)
        current_layout.addLayout(self.current_card_grid)
        current_buttons = QHBoxLayout()
        current_buttons.addWidget(self.confirm_button)
        current_buttons.addStretch(1)
        current_layout.addLayout(current_buttons)
        current_page_layout.addWidget(current_group)
        self.tabs.addTab(current_page, "当前装备")

        result_page = QWidget()
        result_page_layout = QVBoxLayout(result_page)
        action_group = QGroupBox("计算")
        action_layout = QVBoxLayout(action_group)
        settings = QHBoxLayout()
        self.horizon_combo.addItem("horizon=1", 1)
        self.horizon_combo.addItem("horizon=2", 2)
        settings.addWidget(QLabel("Action EV 展望步数"))
        settings.addWidget(self.horizon_combo)
        settings.addWidget(self.best_button)
        settings.addWidget(self.action_button)
        settings.addWidget(self.portfolio_button)
        settings.addWidget(self.cancel_action_button)
        settings.addStretch(1)
        action_layout.addLayout(settings)
        action_layout.addWidget(self.horizon_note_label)
        action_layout.addWidget(self.progress_label)
        action_layout.addWidget(self.progress_meter_label)
        action_layout.addWidget(self.progress_bar)
        action_layout.addWidget(self.progress_detail_label)
        result_input_audit_group = QGroupBox("本次输入口径")
        result_input_audit_layout = QVBoxLayout(result_input_audit_group)
        result_input_audit_actions = QHBoxLayout()
        result_input_audit_actions.addStretch(1)
        result_input_audit_actions.addWidget(self.copy_result_input_audit_button)
        result_input_audit_layout.addLayout(result_input_audit_actions)
        result_input_audit_layout.addWidget(self.result_input_audit_label)
        action_layout.addWidget(result_input_audit_group)
        result_page_layout.addWidget(action_group)

        recommend_card = QFrame()
        recommend_card.setObjectName("RecommendCard")
        recommend_layout = QVBoxLayout(recommend_card)
        recommend_header = QHBoxLayout()
        recommend_header.addWidget(self.result_recommend_icon)
        recommend_header.addWidget(self.result_recommend_title, 1)
        recommend_layout.addLayout(recommend_header)
        recommend_layout.addWidget(self.result_recommend_detail)
        result_page_layout.addWidget(recommend_card)

        action_detail_page = QWidget()
        action_detail_layout = QVBoxLayout(action_detail_page)
        action_detail_header = QHBoxLayout()
        action_detail_header.addWidget(self.action_table_status_label, 1)
        action_detail_header.addWidget(self.show_all_actions_button)
        action_detail_layout.addLayout(action_detail_header)
        action_detail_layout.addWidget(self.action_table)
        self.result_tabs.addTab(action_detail_page, "Action EV 明细")

        plan_page = QWidget()
        plan_layout = QVBoxLayout(plan_page)
        plan_layout.addWidget(self.action_plan_summary_label)
        plan_layout.addWidget(QLabel("条件分支"))
        plan_layout.addWidget(self.action_plan_branch_table)
        plan_layout.addWidget(QLabel("代表分支搭配"))
        plan_layout.addWidget(self.action_plan_loadout_table)
        self.result_tabs.addTab(plan_page, "H=2 方案")

        loadout_page = QWidget()
        loadout_layout = QVBoxLayout(loadout_page)
        loadout_layout.addWidget(QLabel("当前最优搭配"))
        loadout_layout.addWidget(self.best_table)
        loadout_layout.addWidget(QLabel("推荐调律后代表分支搭配"))
        loadout_layout.addWidget(self.action_loadout_table)
        self.result_tabs.addTab(loadout_page, "搭配结果")

        portfolio_page = QWidget()
        portfolio_layout = QVBoxLayout(portfolio_page)
        portfolio_layout.addWidget(self.portfolio_status_label)
        portfolio_layout.addWidget(self.portfolio_table)
        self.result_tabs.addTab(portfolio_page, "BOX 决策")

        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        log_layout.addWidget(self.log_toggle_button)
        log_layout.addWidget(self.log)
        self.result_tabs.addTab(log_page, "运行日志")
        result_group = QGroupBox("结果")
        result_layout = QVBoxLayout(result_group)
        result_layout.addWidget(self.result_tabs)
        result_page_layout.addWidget(result_group)
        self.tabs.addTab(result_page, "计算结果")
        layout.addWidget(self.tabs, 1)
        self.tabs.setCurrentIndex(0)

        self.setCentralWidget(root)

    def _connect_signals(self) -> None:
        self.tabs.currentChanged.connect(lambda _index: self._tab_context_changed())
        self.result_tabs.currentChanged.connect(lambda _index: self._tab_context_changed())
        self.game_combo.currentIndexChanged.connect(lambda _index: self._reload_game_context())
        self.character_combo.currentIndexChanged.connect(lambda _index: self._target_template_changed())
        self.probability_combo.currentIndexChanged.connect(lambda _index: self._probability_changed())
        self.agent_button.clicked.connect(self.open_agent_selector)
        self.edit_target_template_button.clicked.connect(self.edit_target_template)
        self.delete_target_template_button.clicked.connect(self.delete_target_template)
        self.copy_input_audit_button.clicked.connect(self.copy_input_audit)
        self.copy_result_input_audit_button.clicked.connect(self.copy_input_audit)
        self.current_table.changed.connect(self._current_changed)
        self.inventory_table.changed.connect(self._inventory_changed)
        self.position_filter.currentIndexChanged.connect(lambda _index: self._refresh_inventory_view())
        self.set_filter.currentIndexChanged.connect(lambda _index: self._refresh_inventory_view())
        self.main_filter.currentIndexChanged.connect(lambda _index: self._refresh_inventory_view())
        self.target_set_filter.stateChanged.connect(lambda _state: self._refresh_inventory_view())
        self.weak_position_filter.stateChanged.connect(lambda _state: self._refresh_inventory_view())
        self.unfinished_filter.stateChanged.connect(lambda _state: self._refresh_inventory_view())
        self.replaceable_filter.stateChanged.connect(lambda _state: self._refresh_inventory_view())
        self.duplicate_filter.stateChanged.connect(lambda _state: self._refresh_inventory_view())
        self.clear_inventory_filters_button.clicked.connect(self.clear_inventory_filters)
        self.log_toggle_button.toggled.connect(self._set_log_visible)
        self.confirm_button.clicked.connect(self.confirm_current)
        self.load_current_template_button.clicked.connect(self.load_current_template)
        self.save_current_button.clicked.connect(self.save_current)
        self.rename_current_template_button.clicked.connect(self.rename_current_template)
        self.delete_current_template_button.clicked.connect(self.delete_current_template)
        self.load_example_button.clicked.connect(self.load_example_current)
        self.add_inventory_button.clicked.connect(self.add_inventory)
        self.copy_inventory_button.clicked.connect(self.copy_selected_inventory)
        self.clear_substats_button.clicked.connect(self.clear_selected_inventory_substats)
        self.delete_inventory_button.clicked.connect(self.delete_inventory)
        self.save_inventory_button.clicked.connect(self.save_inventory)
        self.export_inventory_button.clicked.connect(self.export_inventory_details)
        self.best_button.clicked.connect(self.run_best_loadout)
        self.action_button.clicked.connect(self.run_action_ev)
        self.portfolio_button.clicked.connect(self.run_portfolio_audit)
        self.cancel_action_button.clicked.connect(self.cancel_action_ev)
        self.show_all_actions_button.clicked.connect(self.toggle_action_rows)
        self.horizon_combo.currentIndexChanged.connect(lambda _index: self._update_horizon_note())
        self.current_template_combo.currentIndexChanged.connect(lambda _index: self._update_action_buttons())

    def _tab_context_changed(self) -> None:
        _suppress_transient_popups()

    def _load_games(self) -> None:
        self.game_combo.blockSignals(True)
        self.game_combo.clear()
        for game in self.games:
            self.game_combo.addItem(f"{game.name} ({game.id})", game.id)
        self.game_combo.blockSignals(False)
        self._reload_game_context()

    def _reload_game_context(self) -> None:
        _suppress_transient_popups()
        game = self.selected_game()
        selected_character_id = str(self.character_combo.currentData() or "")
        self._reload_target_template_options(selected_character_id)
        self.probabilities = load_probability_models(game.id)
        self.probability_combo.blockSignals(True)
        self.probability_combo.clear()
        for model in self.probabilities:
            self.probability_combo.addItem(f"{model.name} ({model.id})", model.id)
        self.probability_combo.blockSignals(False)
        self._reload_character_context()

    def _reload_target_template_options(self, selected_character_id: str | None = None) -> None:
        _suppress_transient_popups()
        game = self.selected_game()
        base_characters = load_characters(game.id)
        try:
            user_templates = load_user_target_templates(game.id)
            user_template_sources = load_user_target_template_sources(game.id)
            user_template_source_agents = load_user_target_template_source_agents(game.id)
        except Exception as exc:
            user_templates = []
            user_template_sources = {}
            user_template_source_agents = {}
            if hasattr(self, "log"):
                self.log.append(f"用户目标模板读取失败，已退回内置目标模板：{exc}")
            if hasattr(self, "progress_label"):
                self.progress_label.setText("用户目标模板读取失败，已退回内置目标模板。")
        self.characters = [*base_characters, *user_templates]
        self._target_template_source_by_id = {
            **{character.id: character.id for character in base_characters},
            **user_template_sources,
        }
        self._target_template_source_agent_by_id = user_template_source_agents
        self.agents = agent_metadata_with_fallbacks(game.id, base_characters)
        self.character_combo.blockSignals(True)
        self.character_combo.clear()
        for character in self.characters:
            prefix = "自定义 · " if character.id.startswith("user_") else ""
            self.character_combo.addItem(f"{prefix}{character.name} ({character.id})", character.id)
        if selected_character_id:
            index = self.character_combo.findData(selected_character_id)
            if index >= 0:
                self.character_combo.setCurrentIndex(index)
        self.character_combo.blockSignals(False)

    def _target_template_summary_text(self, character: CharacterPreset) -> str:
        plan = character.active_set_plan()
        if plan is None or plan.is_unrestricted:
            plan_text = "不限套装"
        else:
            plan_text = " + ".join(
                f"{' / '.join(requirement.set_names)} {requirement.pieces}"
                for requirement in plan.requirements
            )
        main_parts = []
        unrestricted_main_positions = []
        game = self.selected_game()
        for rule in game.positions:
            mains = character.preferred_mains_for(rule.id)
            if mains:
                main_parts.append(f"{game.position_name(rule.id)}:{'/'.join(mains)}")
            else:
                unrestricted_main_positions.append(game.position_name(rule.id))
        if main_parts:
            main_text = "；".join(main_parts)
            if unrestricted_main_positions:
                main_text += f"；未限制：{'/'.join(unrestricted_main_positions)}"
        else:
            main_text = "全部位置不限制主属性"
        priority_text = _priority_tiers_text(character.priority_tiers()) or "未配置有效副属性"
        return "\n".join(
            [
                "目标模板=计算目标，不保存装备；只影响主属性目标、套装结构和副属性排序。",
                f"期望套装结构：{plan_text}",
                f"每位置期望主属性：{main_text}",
                f"副属性有效排序：{priority_text}",
            ]
        )

    def _refresh_target_template_controls(self) -> None:
        character = self.selected_character()
        is_user_template = character.id.startswith("user_")
        self.delete_target_template_button.setEnabled(is_user_template)
        self.target_template_summary_label.setText(self._target_template_summary_text(character))

    def selected_agent(self) -> AgentMetadata | None:
        if not self.agents:
            return None
        game_id = self.selected_game().id if self.games else ""
        selected_id = self._selected_agent_id_by_game.get(game_id)
        source_agent_id = self._selected_target_template_source_agent_id()
        if source_agent_id:
            for agent in self.agents:
                if agent.agent_id == source_agent_id:
                    return agent
        source_character_id = self._selected_target_template_source_character_id()
        if source_character_id:
            for agent in self.agents:
                if agent.agent_id == selected_id and agent.character_preset_id == source_character_id:
                    return agent
            for agent in self.agents:
                if agent.character_preset_id == source_character_id:
                    return agent
        for agent in self.agents:
            if agent.agent_id == selected_id:
                return agent
        character_id = self.character_combo.currentData()
        for agent in self.agents:
            if agent.agent_id == character_id and agent.character_preset_id == character_id:
                return agent
        for agent in self.agents:
            if agent.character_preset_id == character_id:
                return agent
        return self.agents[0]

    def _agent_summary_text(self, agent: AgentMetadata | None) -> str:
        if agent is None:
            return "未选择代理人"
        parts = [agent.name, agent.rarity, agent.attribute, agent.specialty, agent.faction]
        visible = [part for part in parts if part and part != UNKNOWN_LABEL]
        label = " / ".join(visible) if visible else agent.name
        version = f" · {agent.release_version}" if agent.release_version else ""
        return f"{label}{version} -> 目标模板 {agent.character_preset_id}"

    def _data_scope_text(self) -> str:
        storage_id = self.selected_storage_character_id()
        legacy_id = self.selected_legacy_storage_character_id()
        if storage_id == legacy_id:
            return f"数据归属：{storage_id}"
        return f"数据归属：{storage_id}；目标模板来源：{legacy_id}"

    def _inventory_scope_text(self) -> str:
        target_id = self.selected_storage_character_id()
        source_id = self._inventory_loaded_storage_id or target_id
        if source_id == target_id:
            return f"库存归属：{target_id}"
        return f"库存来源：旧来源 {source_id}；保存会写入 {target_id}"

    def _agent_card_widget(
        self,
        agent: AgentMetadata,
        *,
        selected: bool,
        on_click: Callable[[], None] | None = None,
    ) -> AgentCard:
        card = AgentCard(agent, selected=selected, summary=self._agent_summary_text(agent))
        if on_click is not None:
            card.clicked.connect(on_click)
        return card

    def _refresh_agent_selector_summary(self) -> None:
        agent = self.selected_agent()
        summary = self._agent_summary_text(agent)
        if agent is not None:
            summary = f"{summary}\n{self._data_scope_text()}"
        self.agent_summary_label.setText(summary)
        self.agent_button.setText("切换代理人" if agent else "选择代理人")

    def _select_agent(self, agent: AgentMetadata) -> None:
        _suppress_transient_popups()
        index = self.character_combo.findData(agent.character_preset_id)
        if index < 0:
            QMessageBox.warning(
                self,
                "代理人缺少目标模板",
                f"{agent.name} 引用的目标模板 {agent.character_preset_id} 不存在，暂不能计算；目标模板应定义位置主属性、套装结构和副属性有效排序。",
            )
            return
        self._selected_agent_id_by_game[self.selected_game().id] = agent.agent_id
        if self.character_combo.currentIndex() == index:
            self._refresh_agent_selector_summary()
            self._refresh_overview()
            self._clear_results("已切换代理人，请确认当前装备。")
            return
        self.character_combo.blockSignals(True)
        try:
            self.character_combo.setCurrentIndex(index)
        finally:
            self.character_combo.blockSignals(False)
        self._reload_character_context()

    def open_agent_selector(self) -> None:
        _suppress_transient_popups()
        if not self.agents:
            QMessageBox.information(self, "暂无代理人", "当前游戏还没有代理人元数据或目标模板（计算目标）。")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("切换代理人")
        dialog.resize(940, 640)
        root = QVBoxLayout(dialog)

        filters = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("搜索代理人")
        attribute_filter = QComboBox()
        specialty_filter = QComboBox()
        attribute_filter.addItem("全部")
        for value in agent_filter_values(self.agents, "attribute"):
            attribute_filter.addItem(value)
        specialty_filter.addItem("全部")
        for value in agent_filter_values(self.agents, "specialty"):
            specialty_filter.addItem(value)
        filters.addWidget(QLabel("搜索"))
        filters.addWidget(search, 1)
        filters.addWidget(QLabel("属性"))
        filters.addWidget(attribute_filter)
        filters.addWidget(QLabel("职介"))
        filters.addWidget(specialty_filter)
        root.addLayout(filters)

        status = QLabel("")
        status.setWordWrap(True)
        root.addWidget(status)
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        current_agent = self.selected_agent()

        def choose_agent(selected: AgentMetadata) -> None:
            _suppress_transient_popups(1800)
            self._select_agent(selected)
            dialog.accept()
            _suppress_transient_popups(1800)

        def clear_grid() -> None:
            while grid.count():
                item = grid.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        def rebuild_grid() -> None:
            clear_grid()
            filtered_agents = filter_agent_metadata(
                self.agents,
                attribute=attribute_filter.currentText(),
                specialty=specialty_filter.currentText(),
                text=search.text(),
            )
            status.setText(f"按实装版本从新到旧展示；当前筛选 {len(filtered_agents)} / {len(self.agents)} 名代理人。")
            for index, agent in enumerate(filtered_agents):
                card = self._agent_card_widget(
                    agent,
                    selected=current_agent is not None and agent.agent_id == current_agent.agent_id,
                    on_click=lambda selected=agent: choose_agent(selected),
                )
                grid.addWidget(card, index // 3, index % 3)
            grid.setRowStretch((len(filtered_agents) + 2) // 3, 1)

        for column in range(3):
            grid.setColumnStretch(column, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(grid_host)
        root.addWidget(scroll)
        search.textChanged.connect(lambda _text: rebuild_grid())
        attribute_filter.currentIndexChanged.connect(lambda _index: rebuild_grid())
        specialty_filter.currentIndexChanged.connect(lambda _index: rebuild_grid())
        rebuild_grid()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)
        dialog.exec()
        _suppress_transient_popups()

    def _reload_character_context(self) -> None:
        _suppress_transient_popups()
        game = self.selected_game()
        character = self.selected_character()
        selected_id = self._selected_agent_id_by_game.get(game.id)
        selected_agent = next((agent for agent in self.agents if agent.agent_id == selected_id), None)
        if selected_agent is None or selected_agent.character_preset_id != character.id:
            matching_agent = next(
                (
                    agent
                    for agent in self.agents
                    if agent.agent_id == character.id and agent.character_preset_id == character.id
                ),
                None,
            )
            if matching_agent is None:
                matching_agent = next(
                    (agent for agent in self.agents if agent.character_preset_id == character.id),
                    None,
            )
            if matching_agent is not None:
                self._selected_agent_id_by_game[game.id] = matching_agent.agent_id
        storage_character_id = self.selected_storage_character_id()
        fallback_storage_ids = [self.selected_legacy_storage_character_id()]
        current_pieces = _initial_current_pieces(game, storage_character_id, fallback_storage_ids)
        inventory_pieces, inventory_source_id = _initial_inventory_with_source(
            game,
            storage_character_id,
            fallback_storage_ids,
        )
        self._inventory_loaded_storage_id = inventory_source_id
        self.current_table.set_context(game, character, current_pieces)
        self.inventory_table.set_context(game, character, inventory_pieces)
        self.current_confirmed_digest = None
        self._last_weakest_label = "-"
        self._last_recommended_action_summary = "尚未计算"
        self._last_main_metric_summary = "-"
        self._last_action_engine = DEFAULT_ACTION_EV_ENGINE
        self._last_action_execution_mode = "-"
        self._has_calculated_once = False
        self._clear_loaded_current_snapshot()
        self._refresh_target_template_controls()
        self._refresh_current_template_controls()
        self._refresh_current_cards()
        self._refresh_inventory_filters()
        self._refresh_inventory_view()
        self._refresh_agent_selector_summary()
        self._clear_results("已切换代理人、目标模板或游戏，请先确认当前装备。")
        self._update_action_buttons()

    def _target_template_changed(self) -> None:
        if not self.characters or self.current_table.game is None or self.inventory_table.game is None:
            return
        _suppress_transient_popups()
        game = self.selected_game()
        character = self.selected_character()
        current_pieces = self._hidden_table_pieces(self.current_table)
        inventory_pieces = self._hidden_table_pieces(self.inventory_table)
        self.current_table.set_context(game, character, current_pieces)
        self.inventory_table.set_context(game, character, inventory_pieces)
        self._inventory_loaded_storage_id = self.selected_storage_character_id()
        self.current_confirmed_digest = None
        self._last_weakest_label = "-"
        self._last_recommended_action_summary = "尚未计算"
        self._last_main_metric_summary = "-"
        self._last_action_engine = DEFAULT_ACTION_EV_ENGINE
        self._last_action_execution_mode = "-"
        self._has_calculated_once = False
        self._clear_loaded_current_snapshot()
        self._refresh_target_template_controls()
        self._refresh_current_template_controls(mark_unloaded=True)
        self._refresh_current_cards()
        self._refresh_inventory_filters()
        self._refresh_inventory_view()
        self._refresh_agent_selector_summary()
        self._clear_results("目标模板已变化：库存和当前装备未改动，请重新确认后计算。")
        self._update_action_buttons()

    def selected_game(self) -> GameRules:
        game_id = self.game_combo.currentData()
        for game in self.games:
            if game.id == game_id:
                return game
        return self.games[0]

    def selected_character(self) -> CharacterPreset:
        character_id = self.character_combo.currentData()
        for character in self.characters:
            if character.id == character_id:
                return character
        return self.characters[0]

    def _character_by_id(self, character_id: str) -> CharacterPreset | None:
        return next((character for character in self.characters if character.id == character_id), None)

    def _select_portfolio_targets_dialog(self) -> tuple[list[PortfolioTarget], PortfolioMode] | None:
        _suppress_transient_popups()
        dialog = QDialog(self)
        dialog.setWindowTitle("BOX 决策/多代理人审计")
        dialog.resize(860, 680)
        root = QVBoxLayout(dialog)
        note = QLabel(
            "Phase 1 仅做 H=1 BOX 调律审计：主 EV 只看进入更优 best_loadout 的成型收益；"
            "建设方向单独审计，不参与排序；不替换现有单角色调律推荐，也不做同队装备互斥精确分配。"
        )
        note.setWordWrap(True)
        note.setObjectName("MutedText")
        root.addWidget(note)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Portfolio 模式"))
        mode_combo = QComboBox()
        mode_combo.addItem("任一代理人有用（ANY_USEFUL）", PortfolioMode.ANY_USEFUL.value)
        mode_combo.addItem("加权总收益（WEIGHTED_SUM）", PortfolioMode.WEIGHTED_SUM.value)
        mode_row.addWidget(mode_combo)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        host = QWidget()
        grid = QGridLayout(host)
        grid.setColumnStretch(1, 1)
        grid.addWidget(QLabel("选择"), 0, 0)
        grid.addWidget(QLabel("代理人 / 目标模板"), 0, 1)
        grid.addWidget(QLabel("weight"), 0, 2)
        current_agent = self.selected_agent()
        controls: list[tuple[AgentMetadata, QCheckBox, QDoubleSpinBox]] = []
        for row_index, agent in enumerate(self.agents, start=1):
            character = self._character_by_id(agent.character_preset_id)
            check = QCheckBox()
            check.setChecked(current_agent is not None and agent.agent_id == current_agent.agent_id)
            check.setEnabled(character is not None)
            label = QLabel(
                f"{agent.name} / {agent.rarity} / {agent.attribute} / {agent.specialty} -> "
                f"{agent.character_preset_id if character is not None else '缺目标模板'}"
            )
            label.setWordWrap(True)
            weight_spin = QDoubleSpinBox()
            weight_spin.setRange(0.0, 10.0)
            weight_spin.setSingleStep(0.1)
            weight_spin.setDecimals(2)
            weight_spin.setValue(1.0)
            weight_spin.setEnabled(character is not None)
            controls.append((agent, check, weight_spin))
            grid.addWidget(check, row_index, 0)
            grid.addWidget(label, row_index, 1)
            grid.addWidget(weight_spin, row_index, 2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        targets: list[PortfolioTarget] = []
        for agent, check, weight_spin in controls:
            if not check.isChecked():
                continue
            character = self._character_by_id(agent.character_preset_id)
            if character is None:
                continue
            targets.append(
                PortfolioTarget(
                    agent_id=agent.agent_id,
                    name=agent.name,
                    character=character,
                    weight=float(weight_spin.value()),
                )
            )
        try:
            mode = PortfolioMode(str(mode_combo.currentData() or PortfolioMode.ANY_USEFUL.value))
        except ValueError:
            mode = PortfolioMode.ANY_USEFUL
        return targets, mode

    def _selected_target_template_source_character_id(self) -> str:
        character_id = str(self.character_combo.currentData() or "")
        return self._target_template_source_by_id.get(character_id, "")

    def _selected_target_template_source_agent_id(self) -> str:
        character_id = str(self.character_combo.currentData() or "")
        return self._target_template_source_agent_by_id.get(character_id, "")

    def selected_storage_character_id(self) -> str:
        source_agent_id = self._selected_target_template_source_agent_id()
        if source_agent_id:
            return source_agent_id
        agent = self.selected_agent()
        if agent is not None:
            return agent.agent_id
        return self.selected_character().id

    def selected_legacy_storage_character_id(self) -> str:
        source_character_id = self._selected_target_template_source_character_id()
        if source_character_id:
            return source_character_id
        agent = self.selected_agent()
        if agent is not None:
            return agent.character_preset_id
        return self.selected_character().id

    def selected_probability_model(self) -> ProbabilityModel:
        model_id = self.probability_combo.currentData()
        for model in self.probabilities:
            if model.id == model_id:
                return model
        return self.probabilities[0]

    def edit_target_template(self) -> None:
        game = self.selected_game()
        character = self.selected_character()
        dialog = TargetTemplateEditDialog(game, character, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.template is None:
            self.progress_label.setText("已取消编辑目标模板；目标规则未变化。")
            return
        source_character_id = (
            self._target_template_source_by_id.get(character.id)
            or self.selected_legacy_storage_character_id()
        )
        selected_agent = self.selected_agent()
        source_agent_id = (
            self._target_template_source_agent_by_id.get(character.id)
            or (selected_agent.agent_id if selected_agent is not None else "")
        )
        saved = save_user_target_template(
            game.id,
            dialog.template,
            dialog.template.name,
            source_character_id=source_character_id,
            source_agent_id=source_agent_id,
        )
        self._reload_target_template_options(saved.id)
        self._target_template_changed()
        self.progress_label.setText(
            f"已保存目标模板：{saved.name}。它只影响目标规则，不改库存或当前装备快照。\n"
            + self._target_template_summary_text(saved)
        )

    def delete_target_template(self) -> None:
        character = self.selected_character()
        if not character.id.startswith("user_"):
            QMessageBox.information(self, "内置目标模板", "内置目标模板不能删除；可以编辑后另存为自定义目标模板。")
            return
        answer = QMessageBox.question(
            self,
            "删除自定义目标模板？",
            f"确定删除自定义目标模板“{character.name}”吗？库存和当前装备不会删除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.progress_label.setText("已取消删除目标模板；目标规则未变化。")
            return
        game = self.selected_game()
        fallback_target_id = self.selected_legacy_storage_character_id()
        delete_user_target_template(game.id, character.id)
        self._reload_target_template_options(fallback_target_id)
        self._target_template_changed()
        active = self.selected_character()
        self.progress_label.setText(
            f"已删除自定义目标模板：{character.name}。已切回目标模板：{active.name}。\n"
            + self._target_template_summary_text(active)
        )

    def _probability_changed(self) -> None:
        self._clear_results("概率模型已变化。")
        self._refresh_overview()

    def _set_badge_text(self, label: QLabel, text: str, muted: bool = False) -> None:
        label.setText(text)
        label.setObjectName("MutedBadge" if muted else "Badge")
        label.style().unpolish(label)
        label.style().polish(label)

    def _has_visible_results(self) -> bool:
        return self.best_table.rowCount() > 0 or self.action_table.rowCount() > 0

    def _result_status_text(self) -> tuple[str, bool]:
        if self._results_stale and self._has_calculated_once:
            return "结果已过期", False
        if self._has_visible_results() and not self._results_stale:
            return "结果有效", False
        return "结果未生成", True

    def _refresh_overview(self) -> None:
        if not self.games or not self.characters or not self.probabilities:
            return
        agent = self.selected_agent()
        self.overview_game_label.setText(self.game_combo.currentText() or "-")
        if agent is not None:
            version = f" · 实装 {agent.release_version}" if agent.release_version else ""
            self.overview_character_label.setText(
                f"{agent.name} ({agent.rarity}/{agent.attribute}/{agent.specialty})"
                f" · {agent.faction}{version} · 目标模板 {self.character_combo.currentText()}"
                f" · {self._data_scope_text()}"
            )
        else:
            self.overview_character_label.setText(self.character_combo.currentText() or "-")
        self.overview_probability_label.setText(self.probability_combo.currentText() or "-")
        confirmed = self.current_confirmed_digest is not None
        self._set_badge_text(self.overview_confirm_label, "已确认" if confirmed else "未确认", not confirmed)
        self._set_badge_text(
            self.overview_inventory_label,
            f"库存 {self.inventory_table.rowCount()} 件",
            self.inventory_table.rowCount() == 0,
        )
        status_text, muted = self._result_status_text()
        self._set_badge_text(self.overview_stale_label, status_text, muted)
        self.overview_weakest_label.setText(self._last_weakest_label)
        self.overview_action_label.setText(self._last_recommended_action_summary)
        self.overview_metric_label.setText(self._last_main_metric_summary)
        guide = "没有结果。先确认目标规则，再维护库存、确认当前装备，然后点击“计算当前最优搭配（含强化期望）”“计算调律建议”或“BOX 决策/多代理人审计”。"
        if self._results_stale and self._has_calculated_once:
            guide = "装备、库存或概率模型已变化，旧结果不可作为当前结论，请重新计算。"
        elif self._has_visible_results() and not self._results_stale:
            guide = "结果已更新，可在“计算结果”页查看 Action EV 明细、H=2 方案、搭配结果、BOX 决策和运行日志。"
        self.overview_guide_label.setText(guide)
        audit_text = self._input_audit_text()
        self.input_audit_label.setText(audit_text)
        self.result_input_audit_label.setText(audit_text)

    def _input_audit_text(self) -> str:
        game = self.selected_game()
        character = self.selected_character()
        agent = self.selected_agent()
        agent_text = agent.name if agent is not None else "未选择代理人"
        confirmed_text = "已确认" if self.current_confirmed_digest else "未确认"
        current_count = self.current_table.rowCount()
        inventory_count = self.inventory_table.rowCount()
        locked_count = 0
        unfinished_count = 0
        current_digest = ""
        inventory_digest = ""
        try:
            current_pieces = self._hidden_table_pieces(self.current_table)
            current_digest = _pieces_digest(current_pieces)
            inventory_pieces = self._hidden_table_pieces(self.inventory_table)
            inventory_digest = _pieces_digest(inventory_pieces)
            locked_count = sum(1 for piece in inventory_pieces if piece.locked)
            unfinished_count = sum(
                1 for piece in inventory_pieces if piece.level < game.enhancement.max_level
            )
        except Exception:
            pass
        horizon = int(self.horizon_combo.currentData() or 1)
        input_digest = hashlib.sha256(
            json.dumps(
                {
                    "game_id": game.id,
                    "agent_id": agent.agent_id if agent is not None else "",
                    "storage_id": self.selected_storage_character_id(),
                    "legacy_storage_id": self.selected_legacy_storage_character_id(),
                    "inventory_loaded_storage_id": self._inventory_loaded_storage_id,
                    "target_template_id": character.id,
                    "probability_model_id": self.selected_probability_model().id,
                    "horizon": horizon,
                    "current_confirmed": bool(self.current_confirmed_digest),
                    "current_digest": self.current_confirmed_digest or current_digest,
                    "inventory_digest": inventory_digest,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return "\n".join(
            [
                f"代理人：{agent_text}；目标模板：{character.name} ({character.id})",
                f"{self._data_scope_text()}；{self._inventory_scope_text()}",
                f"游戏/概率模型：{game.name} ({game.id}) / {self.probability_combo.currentText() or '-'}；horizon={horizon}",
                f"当前装备：{current_count}/{len(game.positions)} 件，{confirmed_text}；库存：{inventory_count} 件，其中未满级 {unfinished_count} 件、锁定 {locked_count} 件",
                f"输入指纹：{_short_digest(input_digest)}；当前装备指纹：{_short_digest(self.current_confirmed_digest or current_digest)}；库存指纹：{_short_digest(inventory_digest)}",
                self._target_template_summary_text(character),
            ]
        )

    def copy_input_audit(self) -> None:
        text = self._input_audit_text()
        QApplication.clipboard().setText(text)
        self.progress_label.setText("已复制本次输入口径，可直接发给 GPT 或用于复核。")

    def _clear_loaded_current_snapshot(self) -> None:
        self._loaded_current_snapshot_id = ""
        self._loaded_current_snapshot_storage_id = ""

    def _current_template_items(self) -> list[dict[str, Any]]:
        game_id = self.selected_game().id
        for storage_id in _unique_storage_ids(
            self.selected_storage_character_id(),
            self.selected_legacy_storage_character_id(),
        ):
            try:
                items = load_user_current_gears(game_id, storage_id)
                if items or current_gear_store_path(game_id, storage_id).exists():
                    return [
                        {**item, "_storage_id": storage_id}
                        for item in items
                    ]
            except Exception:
                continue
        return []

    def _refresh_current_template_controls(
        self,
        selected_id: str | None = None,
        *,
        mark_unloaded: bool = False,
    ) -> None:
        templates = self._current_template_items()
        previous_id = str(self.current_template_combo.currentData() or "")
        target_id = selected_id if selected_id is not None else previous_id
        if not target_id and templates and not mark_unloaded:
            target_id = str(templates[-1]["id"])

        self.current_template_combo.blockSignals(True)
        try:
            self.current_template_combo.clear()
            if templates:
                if mark_unloaded:
                    self.current_template_combo.addItem("未载入快照", "")
                for item in templates:
                    count = len(item.get("pieces") or [])
                    suffix = f" · {count}/6 件" if count != 6 else " · 6/6 件"
                    if str(item.get("_storage_id") or "") != self.selected_storage_character_id():
                        suffix += " · 旧来源"
                    self.current_template_combo.addItem(f"{item['label']}{suffix}", item["id"])
                index = self.current_template_combo.findData(target_id) if target_id else -1
                if index >= 0:
                    self.current_template_combo.setCurrentIndex(index)
                elif mark_unloaded:
                    self.current_template_combo.setCurrentIndex(0)
                else:
                    self.current_template_combo.setCurrentIndex(self.current_template_combo.count() - 1)
            else:
                self.current_template_combo.addItem("未保存快照", "")
                self.current_template_combo.setCurrentIndex(0)
        finally:
            self.current_template_combo.blockSignals(False)

        has_template = bool(templates)
        has_selected_template = bool(str(self.current_template_combo.currentData() or ""))
        self.load_current_template_button.setEnabled(has_template and has_selected_template)
        self.rename_current_template_button.setEnabled(has_template and has_selected_template)
        self.delete_current_template_button.setEnabled(has_template and has_selected_template)

    def _selected_current_template(self) -> dict[str, Any] | None:
        template_id = str(self.current_template_combo.currentData() or "")
        if not template_id:
            return None
        return next(
            (item for item in self._current_template_items() if item["id"] == template_id),
            None,
        )

    def _selected_current_snapshot_is_loaded(self) -> bool:
        template = self._selected_current_template()
        if template is None:
            return False
        storage_id = str(template.get("_storage_id") or self.selected_storage_character_id())
        return (
            str(template.get("id") or "") == self._loaded_current_snapshot_id
            and storage_id == self._loaded_current_snapshot_storage_id
        )

    def _hidden_table_pieces(self, table: GearTable) -> list[GearPiece]:
        pieces, _warnings = table.collect_pieces()
        return pieces

    def _refresh_current_cards(self) -> None:
        if not hasattr(self, "current_card_grid") or not self.characters:
            return
        _suppress_transient_popups()
        parent = self.current_card_grid.parentWidget() or self
        parent.setUpdatesEnabled(False)
        try:
            while self.current_card_grid.count():
                item = self.current_card_grid.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.current_cards = []
            game = self.selected_game()
            character = self.selected_character()
            pieces = self._hidden_table_pieces(self.current_table)
            by_position = {position_key(piece.position): index for index, piece in enumerate(pieces)}
            layout = game.board_layout or [
                [rule.id for rule in game.positions[:3]],
                [rule.id for rule in game.positions[3:6]],
            ]
            for row_index, layout_row in enumerate(layout):
                for column_index, position in enumerate(layout_row):
                    if position is None:
                        spacer = QLabel("")
                        self.current_card_grid.addWidget(spacer, row_index, column_index)
                        continue
                    source_row = by_position.get(position_key(position))
                    if source_row is None:
                        card = PieceCard(-1)
                        card.update_empty(game, position)
                        card.clicked.connect(
                            lambda _row=-1, target_position=position: self.edit_current_position(target_position)
                        )
                    else:
                        card = PieceCard(source_row)
                        card.update_piece(pieces[source_row], game, character)
                        card.clicked.connect(self.edit_current_piece)
                    self.current_cards.append(card)
                    self.current_card_grid.addWidget(card, row_index, column_index)
        finally:
            parent.setUpdatesEnabled(True)
            parent.update()
        self._refresh_overview()

    def _best_loadout_row_summary(self, row: dict[str, Any], current_count: int) -> str:
        return (
            f"{_loadout_source_ref(row, current_count)} / "
            f"{self.selected_game().position_name(row['position'])} / "
            f"{row['set_name']} / {_loadout_main_stat_label(row)} / "
            f"{_loadout_level_from_row(row)} / 期望有效 {row.get('effective_rolls', '-')}"
        )

    def _optimal_loadout_check_text(
        self,
        source: str,
        source_row: int | None,
        candidate: GearPiece,
    ) -> str:
        game = self.selected_game()
        character = self.selected_character()
        current_pieces = self._hidden_table_pieces(self.current_table)
        inventory_pieces = self._hidden_table_pieces(self.inventory_table)
        target_global_index: int

        if source == "current":
            if source_row is None or source_row < 0 or source_row >= len(current_pieces):
                return "检查失败：当前装备行已经不存在。"
            current_pieces[source_row] = candidate
            target_global_index = source_row
        elif source == "inventory":
            if source_row is None or source_row < 0 or source_row >= len(inventory_pieces):
                return "检查失败：库存行已经不存在。"
            inventory_pieces[source_row] = candidate
            target_global_index = len(current_pieces) + source_row
        else:
            inventory_pieces = [*inventory_pieces, candidate]
            target_global_index = len(current_pieces) + len(inventory_pieces) - 1

        rows = best_loadout_rows(
            [*current_pieces, *inventory_pieces],
            game,
            character,
            current_count=len(current_pieces),
            include_upgrade_expectation=True,
        )
        target_id = f"piece:{target_global_index}"
        selected = next((row for row in rows if row.get("_inventory_id") == target_id), None)
        if selected is not None:
            return (
                "检查结果：这件会进入当前最优搭配（未满级按满级强化期望估值）。\n"
                f"{self._best_loadout_row_summary(selected, len(current_pieces))}"
            )

        same_position = [
            row for row in rows if position_key(row["position"]) == position_key(candidate.position)
        ]
        if same_position:
            chosen = same_position[0]
            return (
                "检查结果：这件暂时不在当前最优搭配里（未满级按满级强化期望估值）。\n"
                f"同槽位最优选择：{self._best_loadout_row_summary(chosen, len(current_pieces))}"
            )
        return "检查结果：当前套装硬约束下没有形成完整最优搭配，请检查 6 个槽位和套装结构。"

    def edit_current_piece(self, row: int) -> None:
        pieces = self._hidden_table_pieces(self.current_table)
        if row < 0 or row >= len(pieces):
            return
        dialog = GearPieceEditDialog(
            self.selected_game(),
            self.selected_character(),
            pieces[row],
            editable_position=False,
            title=f"编辑当前装备：{self.selected_game().position_name(pieces[row].position)}",
            parent=self,
            optimal_check_callback=lambda candidate, source_row=row: self._optimal_loadout_check_text(
                "current",
                source_row,
                candidate,
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.piece is None:
            return
        pieces[row] = dialog.piece
        self.current_table.set_context(self.selected_game(), self.selected_character(), pieces)
        self._current_changed()

    def edit_current_position(self, position: str | int) -> None:
        pieces = self._hidden_table_pieces(self.current_table)
        target_key = position_key(position)
        existing_row = next(
            (index for index, piece in enumerate(pieces) if position_key(piece.position) == target_key),
            None,
        )
        if existing_row is not None:
            self.edit_current_piece(existing_row)
            return
        game = self.selected_game()
        character = self.selected_character()
        piece = _default_inventory_piece(game, character, position).model_copy(update={"locked": False})
        dialog = GearPieceEditDialog(
            game,
            character,
            piece,
            editable_position=False,
            title=f"新增当前装备：{game.position_name(position)}",
            parent=self,
            optimal_check_callback=lambda candidate: self._optimal_loadout_check_text(
                "new_inventory",
                None,
                candidate,
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.piece is None:
            return
        pieces.append(dialog.piece)
        self.current_table.set_context(game, character, pieces)
        self._current_changed()

    def edit_inventory_piece(self, source_row: int) -> None:
        pieces = self._hidden_table_pieces(self.inventory_table)
        if source_row < 0 or source_row >= len(pieces):
            return
        dialog = GearPieceEditDialog(
            self.selected_game(),
            self.selected_character(),
            pieces[source_row],
            editable_position=True,
            title=f"编辑库存件 #{source_row + 1}",
            parent=self,
            optimal_check_callback=lambda candidate, row_index=source_row: self._optimal_loadout_check_text(
                "inventory",
                row_index,
                candidate,
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.piece is None:
            return
        pieces[source_row] = dialog.piece
        self.inventory_table.set_context(self.selected_game(), self.selected_character(), pieces)
        self._inventory_changed()
        self._focus_inventory_source_row(source_row)
        self.progress_label.setText(
            f"已更新库存 #{source_row + 1}；不会自动计算。"
            + self._inventory_filter_hidden_suffix(source_row)
        )

    def _selected_inventory_source_row(self) -> int | None:
        return self._selected_inventory_source_row_value

    def _has_selected_inventory_piece(self) -> bool:
        if self.inventory_table.game is None:
            return False
        source_row = self._selected_inventory_source_row()
        if source_row is None:
            return False
        pieces = self._hidden_table_pieces(self.inventory_table)
        return 0 <= source_row < len(pieces)

    def select_inventory_piece(self, source_row: int) -> None:
        self._selected_inventory_source_row_value = source_row
        for card in self.inventory_cards:
            card.set_selected(card.row_index == source_row)
            card.set_highlighted(
                card.row_index in self._highlighted_inventory_source_rows,
                self._highlighted_inventory_label,
            )
        self._refresh_inventory_detail()
        self._update_action_buttons()

    def _focus_inventory_source_row(self, source_row: int) -> None:
        self._selected_inventory_source_row_value = source_row
        self._refresh_inventory_view()

    def _clear_inventory_card_grid(self) -> None:
        while self.inventory_card_grid.count():
            item = self.inventory_card_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _refresh_inventory_filters(self) -> None:
        game = self.selected_game()
        pieces = self._hidden_table_pieces(self.inventory_table)
        current_values = {
            "position": self.position_filter.currentData(),
            "set": self.set_filter.currentData(),
            "main": self.main_filter.currentData(),
        }
        self.position_filter.blockSignals(True)
        self.set_filter.blockSignals(True)
        self.main_filter.blockSignals(True)
        try:
            self.position_filter.clear()
            self.position_filter.addItem("全部", "")
            for rule in game.positions:
                self.position_filter.addItem(game.position_name(rule.id), position_key(rule.id))
            self.set_filter.clear()
            self.set_filter.addItem("全部", "")
            for set_name in game.sets:
                self.set_filter.addItem(set_name, set_name)
            self.main_filter.clear()
            self.main_filter.addItem("全部", "")
            for main_stat in sorted({piece.main_stat for piece in pieces}):
                self.main_filter.addItem(main_stat, main_stat)
            for combo, value in [
                (self.position_filter, current_values["position"]),
                (self.set_filter, current_values["set"]),
                (self.main_filter, current_values["main"]),
            ]:
                index = combo.findData(value)
                combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.position_filter.blockSignals(False)
            self.set_filter.blockSignals(False)
            self.main_filter.blockSignals(False)

    def _inventory_piece_visible(
        self,
        piece: GearPiece,
        source_row: int | None = None,
        duplicate_labels: dict[int, str] | None = None,
    ) -> bool:
        position_filter = str(self.position_filter.currentData() or "")
        set_filter = str(self.set_filter.currentData() or "")
        main_filter = str(self.main_filter.currentData() or "")
        if position_filter and position_key(piece.position) != position_filter:
            return False
        if set_filter and piece.set_name != set_filter:
            return False
        if main_filter and piece.main_stat != main_filter:
            return False
        if self.target_set_filter.isChecked() and piece.set_name not in self._target_set_names():
            return False
        if self.weak_position_filter.isChecked() and not self._piece_is_current_weak_position(piece):
            return False
        if self.unfinished_filter.isChecked() and piece.level >= self.selected_game().enhancement.max_level:
            return False
        if self.replaceable_filter.isChecked() and not self._piece_can_replace_current(piece):
            return False
        if self.duplicate_filter.isChecked() and (
            source_row is None or source_row not in (duplicate_labels or {})
        ):
            return False
        return True

    def _inventory_filters_active(self) -> bool:
        combo_active = any(
            str(combo.currentData() or "")
            for combo in [self.position_filter, self.set_filter, self.main_filter]
        )
        check_active = any(
            check.isChecked()
            for check in [
                self.target_set_filter,
                self.weak_position_filter,
                self.unfinished_filter,
                self.replaceable_filter,
                self.duplicate_filter,
            ]
        )
        return combo_active or check_active

    def _inventory_filter_summary_text(self) -> str:
        parts: list[str] = []
        for label, combo in [
            ("位置", self.position_filter),
            ("套装", self.set_filter),
            ("主属性", self.main_filter),
        ]:
            if str(combo.currentData() or ""):
                parts.append(f"{label}={combo.currentText()}")
        for text, check in [
            ("目标套装", self.target_set_filter),
            ("当前弱位", self.weak_position_filter),
            ("未满级", self.unfinished_filter),
            ("可替换当前", self.replaceable_filter),
            ("重复库存", self.duplicate_filter),
        ]:
            if check.isChecked():
                parts.append(text)
        return f"筛选：{'，'.join(parts)}；" if parts else ""

    def _refresh_inventory_filter_action_state(self) -> None:
        has_selected_inventory = self._has_selected_inventory_piece()
        busy = self._action_busy()
        has_inventory_piece = self.inventory_table.rowCount() > 0
        self.copy_inventory_button.setEnabled(not busy and has_selected_inventory)
        self.clear_substats_button.setEnabled(not busy and has_selected_inventory)
        self.delete_inventory_button.setEnabled(not busy and has_selected_inventory)
        self.export_inventory_button.setEnabled(not busy and has_inventory_piece)
        self.clear_inventory_filters_button.setEnabled(
            self._inventory_filters_active() and not busy
        )

    def _inventory_source_row_visible_under_filters(self, source_row: int) -> bool:
        pieces = self._hidden_table_pieces(self.inventory_table)
        if source_row < 0 or source_row >= len(pieces):
            return False
        duplicate_labels = _inventory_duplicate_row_labels(pieces)
        return self._inventory_piece_visible(pieces[source_row], source_row, duplicate_labels)

    def _inventory_filter_hidden_suffix(self, source_row: int, subject: str = "这件") -> str:
        if (
            self._inventory_filters_active()
            and not self._inventory_source_row_visible_under_filters(source_row)
        ):
            return f" 当前筛选隐藏了{subject}；点“清除筛选”可查看。"
        return ""

    def clear_inventory_filters(self) -> None:
        combos = [self.position_filter, self.set_filter, self.main_filter]
        checks = [
            self.target_set_filter,
            self.weak_position_filter,
            self.unfinished_filter,
            self.replaceable_filter,
            self.duplicate_filter,
        ]
        for combo in combos:
            combo.blockSignals(True)
        for check in checks:
            check.blockSignals(True)
        try:
            for combo in combos:
                index = combo.findData("")
                combo.setCurrentIndex(index if index >= 0 else 0)
            for check in checks:
                check.setChecked(False)
        finally:
            for combo in combos:
                combo.blockSignals(False)
            for check in checks:
                check.blockSignals(False)
        self._refresh_inventory_view()
        self.progress_label.setText("已清除库存筛选；显示全部库存。")

    def _target_set_names(self) -> set[str]:
        character = self.selected_character()
        plan = character.active_set_plan()
        if plan is None or plan.is_unrestricted:
            return {character.target_set}
        return set(plan.target_sets)

    def _current_pieces_by_position(self) -> dict[str, GearPiece]:
        return {
            position_key(piece.position): piece
            for piece in self._hidden_table_pieces(self.current_table)
        }

    def _current_weak_position_key(self) -> str | None:
        pieces = self._hidden_table_pieces(self.current_table)
        if not pieces:
            return None
        try:
            analysis = analyse_current_gear(pieces, self.selected_game(), self.selected_character())
        except Exception:
            return None
        return position_key(analysis.weakest_position) if analysis.weakest_position is not None else None

    def _piece_is_current_weak_position(self, piece: GearPiece) -> bool:
        weak_position = self._current_weak_position_key()
        return weak_position is not None and position_key(piece.position) == weak_position

    def _piece_can_replace_current(self, piece: GearPiece) -> bool:
        current = self._current_pieces_by_position().get(position_key(piece.position))
        if current is None or current.locked:
            return False
        try:
            candidate_score = score_piece(piece, self.selected_game(), self.selected_character())
            current_score = score_piece(current, self.selected_game(), self.selected_character())
        except Exception:
            return False
        return candidate_score.weighted_score > current_score.weighted_score

    def _refresh_inventory_view(self) -> None:
        if not self.characters:
            return
        _suppress_transient_popups()
        game = self.selected_game()
        character = self.selected_character()
        pieces = self._hidden_table_pieces(self.inventory_table)
        duplicate_labels = _inventory_duplicate_row_labels(pieces)
        rows = [
            (source_row, piece)
            for source_row, piece in enumerate(pieces)
            if self._inventory_piece_visible(piece, source_row, duplicate_labels)
        ]
        visible_source_rows = {source_row for source_row, _piece in rows}
        if self._selected_inventory_source_row_value not in visible_source_rows:
            self._selected_inventory_source_row_value = rows[0][0] if rows else None

        self.inventory_card_host.setUpdatesEnabled(False)
        try:
            self._clear_inventory_card_grid()
            self.inventory_cards = []
            column_count = 3
            for visible_index, (source_row, piece) in enumerate(rows):
                card = PieceCard(source_row, show_actions=True, show_equip=True)
                card.update_piece(piece, game, character)
                card.set_selected(source_row == self._selected_inventory_source_row_value)
                card.set_highlighted(
                    source_row in self._highlighted_inventory_source_rows,
                    self._highlighted_inventory_label,
                )
                card.set_duplicate_warning(duplicate_labels.get(source_row, ""))
                card.clicked.connect(self.select_inventory_piece)
                card.edit_requested.connect(self.edit_inventory_piece)
                card.equip_requested.connect(self.equip_inventory_piece)
                card.copy_requested.connect(self.copy_inventory_piece)
                card.clear_requested.connect(self.clear_inventory_piece_substats)
                card.delete_requested.connect(self.delete_inventory_piece)
                self.inventory_cards.append(card)
                self.inventory_card_grid.addWidget(card, visible_index // column_count, visible_index % column_count)
            for column in range(column_count):
                self.inventory_card_grid.setColumnStretch(column, 1)
        finally:
            self.inventory_card_host.setUpdatesEnabled(True)
            self.inventory_card_host.update()
        selected_card = next(
            (
                card
                for card in self.inventory_cards
                if card.row_index == self._selected_inventory_source_row_value
            ),
            None,
        )
        if selected_card is not None:
            self.inventory_card_scroll.ensureWidgetVisible(selected_card)

        duplicate_status = (
            f"重复提示 {len(duplicate_labels)} 件；"
            if duplicate_labels
            else ""
        )
        highlight_status = _inventory_highlight_summary(
            self._highlighted_inventory_source_rows,
            self._highlighted_inventory_label,
        )
        highlight_count_status = _inventory_highlight_count_summary(
            self._highlighted_inventory_source_rows,
            self._has_visible_results(),
        )
        hidden_highlight_status = _inventory_hidden_highlight_summary(
            self._highlighted_inventory_source_rows,
            visible_source_rows,
        )
        filter_status = self._inventory_filter_summary_text()
        if rows:
            self.inventory_card_status_label.setText(
                f"显示 {len(rows)} / {len(pieces)} 件库存；"
                f"{highlight_count_status}"
                f"{highlight_status}"
                f"{hidden_highlight_status}"
                f"{filter_status}"
                f"{duplicate_status}"
                f"{self._inventory_scope_text()}。"
                "点卡片看完整副属性；点“装备”会和当前同槽位互换。"
            )
        elif self.duplicate_filter.isChecked() and not duplicate_labels:
            self.inventory_card_status_label.setText(
                f"当前没有重复库存；{highlight_status}{hidden_highlight_status}{filter_status}{self._inventory_scope_text()}。"
            )
        else:
            self.inventory_card_status_label.setText(
                f"没有符合筛选条件的库存；{highlight_status}{hidden_highlight_status}{filter_status}{duplicate_status}{self._inventory_scope_text()}。"
            )
        self._refresh_inventory_detail()
        self._refresh_inventory_filter_action_state()
        self._refresh_overview()

    def _refresh_inventory_detail(self) -> None:
        source_row = self._selected_inventory_source_row()
        pieces = self._hidden_table_pieces(self.inventory_table)
        if source_row is None or source_row < 0 or source_row >= len(pieces):
            if self.duplicate_filter.isChecked() and not _inventory_duplicate_row_labels(pieces):
                self.inventory_detail_label.setText("当前没有重复库存。")
            else:
                self.inventory_detail_label.setText("库存为空或当前筛选没有可见库存。")
            return
        piece = pieces[source_row]
        effective = _piece_effective_label(piece, self.selected_game(), self.selected_character())
        duplicate_note = _inventory_duplicate_row_labels(pieces).get(source_row, "")
        self.inventory_detail_label.setText(
            f"库存 #{source_row + 1}    {self.selected_game().position_name(piece.position)}    "
            f"{piece.set_name}    {piece.main_stat}    等级 {piece.level}/{self.selected_game().enhancement.max_level}\n"
            f"有效 {effective}    锁定：{'是' if piece.locked else '否'}\n"
            f"副属性：{_piece_substat_label(piece)}"
            + (
                f"\n{_piece_revealed_next_substat_label(piece, self.selected_game())}"
                if piece.revealed_next_substat
                else ""
            )
            + (f"\n重复提示：{duplicate_note}" if duplicate_note else "")
        )

    def _inventory_changed(self) -> None:
        self._highlighted_inventory_source_rows = set()
        self._highlighted_inventory_label = "入选"
        self._refresh_inventory_filters()
        self._refresh_inventory_view()
        self._clear_results("库存已变化。")

    def _set_log_visible(self, visible: bool) -> None:
        self.log.setVisible(visible)
        self.log_toggle_button.setText("隐藏运行日志" if visible else "显示运行日志")

    def _set_result_recommend_icon(self, set_name: str | None) -> None:
        if not set_name:
            self.result_recommend_icon.clear()
            self.result_recommend_icon.setText("")
            self.result_recommend_icon.setToolTip("")
            return
        pixmap = set_icon_pixmap(self.selected_game(), set_name, 36)
        if pixmap is None:
            self.result_recommend_icon.clear()
            self.result_recommend_icon.setText("盘")
        else:
            self.result_recommend_icon.setPixmap(pixmap)
            self.result_recommend_icon.setText("")
        self.result_recommend_icon.setToolTip(set_effect_tooltip(self.selected_game(), set_name))

    def _update_horizon_note(self) -> None:
        horizon = int(self.horizon_combo.currentData() or 1)
        if horizon == 2:
            self.horizon_note_label.setText(
                "horizon=2 为完整概率分布精确计算，可能耗时较长；计算期间可取消。"
            )
        else:
            self.horizon_note_label.setText("horizon=1 为完整概率分布精确计算。")
        if hasattr(self, "input_audit_label"):
            self._refresh_overview()

    def _current_changed(self) -> None:
        self.current_confirmed_digest = None
        self._clear_loaded_current_snapshot()
        self._highlighted_inventory_source_rows = set()
        self._highlighted_inventory_label = "入选"
        self._clear_results("当前装备已变化，请重新确认。")
        self._update_action_buttons()
        self._refresh_current_cards()
        self._refresh_inventory_view()

    def _action_busy(self) -> bool:
        return self._worker is not None or self._action_process is not None

    def _clear_results(self, message: str = "") -> None:
        self._results_stale = True
        self._highlighted_inventory_source_rows = set()
        self._highlighted_inventory_label = "入选"
        self.best_table.setRowCount(0)
        self.best_table.setColumnCount(0)
        self.action_table.setRowCount(0)
        self.action_table.setColumnCount(0)
        self._action_result_rows = []
        self._show_all_action_rows = False
        self.action_table_status_label.setText("尚无 Action EV 明细。")
        self.show_all_actions_button.setEnabled(False)
        self.show_all_actions_button.setText("显示全部")
        self.action_loadout_table.setRowCount(0)
        self.action_loadout_table.setColumnCount(0)
        self.action_plan_summary_label.setText("尚无 H=2 方案。")
        self.action_plan_branch_table.setRowCount(0)
        self.action_plan_branch_table.setColumnCount(0)
        self.action_plan_loadout_table.setRowCount(0)
        self.action_plan_loadout_table.setColumnCount(0)
        self.portfolio_status_label.setText("尚无 BOX 多代理人审计结果。")
        self.portfolio_table.setRowCount(0)
        self.portfolio_table.setColumnCount(0)
        if not self._action_busy():
            self._progress_timer.stop()
            self._action_progress_started_at = None
            self._action_progress_current_unit_started_at = None
            self._action_progress_current_unit_key = None
            self._action_progress_last_unit_done_at = None
            self._action_progress_last_total = 0.0
            self._action_progress_plan_expanded = False
            self._action_progress_percent = 0
            self._last_action_progress_payload = {}
            self._last_action_progress_seen_at = None
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("精确计算 0%")
            self.progress_label.setText(message or "等待操作。")
            self.progress_meter_label.setText("")
            self.progress_detail_label.setText("")
            if self._has_calculated_once:
                self._last_recommended_action_summary = "结果已过期，请重新计算。"
                self._last_main_metric_summary = "-"
                self._last_action_engine = DEFAULT_ACTION_EV_ENGINE
                self._last_action_execution_mode = "-"
                self.result_recommend_title.setText("结果已过期")
                self.result_recommend_detail.setText(message or "输入已变化，请重新计算。")
                self._set_result_recommend_icon(None)
            else:
                self.result_recommend_title.setText("暂无推荐")
                self.result_recommend_detail.setText("计算 Action EV 后会在这里显示调律推荐或库存升级机会。")
                self._set_result_recommend_icon(None)
            self._refresh_overview()

    def _start_action_progress(self) -> None:
        now = time.monotonic()
        self._action_progress_started_at = now
        self._action_progress_current_unit_started_at = None
        self._action_progress_current_unit_key = None
        self._action_progress_last_unit_done_at = None
        self._action_progress_last_total = 0.0
        self._action_progress_plan_expanded = False
        self._last_action_progress_seen_at = now
        self._last_action_progress_payload = {}
        self._action_progress_percent = 0
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("精确计算 0%")
        self.progress_label.setText("正在计算 Action EV。")
        self.progress_meter_label.setText("总进度 0% | action 待开始 | 已耗时 00:00 | ETA 校准中")
        self.progress_detail_label.setText("后台计算已启动，等待第一个进度事件。")
        self._progress_timer.start()

    def _stop_action_progress(self) -> None:
        self._progress_timer.stop()
        self._last_action_progress_payload = {}
        self._last_action_progress_seen_at = None
        self._action_progress_current_unit_started_at = None
        self._action_progress_current_unit_key = None

    def _raw_action_progress_percent(self, payload: dict[str, Any]) -> int:
        event = str(payload.get("event") or "")
        if event == "complete":
            return 100
        total = _progress_float(payload.get("total")) or 0.0
        completed = _progress_float(payload.get("completed")) or 0.0
        if total <= 0:
            return self._action_progress_percent
        percent = int(completed / total * 100)
        return max(0, min(99, percent))

    def _action_progress_inner_text(self, payload: dict[str, Any]) -> str:
        inner_event = str(payload.get("inner_event") or "")
        if not inner_event:
            return ""
        event_labels = {
            "outcomes_start": "展开结果",
            "outcome_done": "结果",
            "state_start": "DP状态",
            "state_action_start": "DP动作",
            "state_action_done": "DP动作完成",
            "state_done": "DP状态完成",
            "memo_hit": "缓存命中",
            "outcome_distribution_start": "生成结果分布",
            "outcome_distribution_done": "结果分布完成",
            "outcome_aggregate_start": "聚合同类结果",
            "outcome_aggregate_done": "聚合完成",
            "candidate_generation_start": "生成候选",
            "candidate_generation_step_start": "候选组",
            "candidate_generation_step_done": "候选组完成",
            "upgrade_generation_start": "强化分布",
            "upgrade_generation_done": "强化分布完成",
            "state_transition_cache_hit": "状态转移缓存命中",
            "state_transition_cache_miss": "状态转移展开",
        }
        label = event_labels.get(inner_event, inner_event)
        completed = payload.get("inner_completed")
        total = payload.get("inner_total")
        if total not in (None, ""):
            label = f"{label} {_format_progress_count(completed)}/{_format_progress_count(total)}"
        depth = payload.get("inner_depth")
        horizon = payload.get("inner_horizon")
        suffixes = []
        if depth not in (None, "", 0):
            suffixes.append(f"深度 {depth}")
        if horizon not in (None, ""):
            suffixes.append(f"h={horizon}")
        inner_strategy = payload.get("inner_action_strategy")
        inner_set = payload.get("inner_action_set")
        if inner_strategy:
            suffixes.append(str(inner_strategy))
        if inner_set:
            suffixes.append(str(inner_set))
        inner_position = payload.get("inner_action_position")
        inner_main = payload.get("inner_action_main_stat")
        if inner_position not in (None, ""):
            suffixes.append(f"位置 {inner_position}")
        if inner_main:
            suffixes.append(str(inner_main))
        return f"内部：{label}" + (f"（{'，'.join(suffixes)}）" if suffixes else "")

    def _update_action_progress_state(self, payload: dict[str, Any], now: float) -> None:
        event = str(payload.get("event") or "")
        unit_key = (
            payload.get("spec_index"),
            payload.get("unit_label"),
            payload.get("label"),
        )
        if event == "unit_start":
            if unit_key != self._action_progress_current_unit_key:
                self._action_progress_current_unit_started_at = now
                self._action_progress_current_unit_key = unit_key
        elif event == "unit_done":
            self._action_progress_last_unit_done_at = now
            self._action_progress_current_unit_started_at = None
            self._action_progress_current_unit_key = None
        elif event == "unit_progress" and self._action_progress_current_unit_started_at is None:
            self._action_progress_current_unit_started_at = now
            self._action_progress_current_unit_key = unit_key

        total = _progress_float(payload.get("total"))
        if total is not None and total > self._action_progress_last_total:
            if self._action_progress_last_total > 0:
                self._action_progress_plan_expanded = True
            self._action_progress_last_total = total

    def _action_progress_meter_text(
        self,
        payload: dict[str, Any],
        now: float,
        stable_percent: int,
    ) -> str:
        parts = [f"总进度 {stable_percent}%"]
        spec_index = payload.get("spec_index")
        spec_total = payload.get("spec_total")
        if spec_index not in (None, "") and spec_total not in (None, ""):
            parts.append(f"action {spec_index}/{spec_total}")
        else:
            completed = payload.get("completed")
            total = payload.get("total")
            if total not in (None, "", 0):
                parts.append(
                    f"action {_format_progress_count(completed)}/{_format_progress_count(total)}"
                )

        if self._action_progress_started_at is not None:
            elapsed = now - self._action_progress_started_at
            parts.append(f"已耗时 {_format_duration(elapsed)}")
            if 0 < stable_percent < 99:
                remaining = elapsed * (100 - stable_percent) / stable_percent
                parts.append(f"保守剩余约 {_format_duration(remaining)}")
            elif stable_percent <= 0:
                parts.append("ETA 首个 action 完成后校准")
            elif stable_percent >= 99 and str(payload.get("event") or "") != "complete":
                parts.append("收尾中")

        if self._action_progress_current_unit_started_at is not None:
            unit_elapsed = now - self._action_progress_current_unit_started_at
            parts.append(f"当前 action {_format_duration(unit_elapsed)}")
        if self._action_progress_plan_expanded:
            parts.append("计划已扩展，进度条不回退")
        if payload.get("derived_from_fixed_positions"):
            parts.append("随机=固定分支加权汇总")
        return " | ".join(parts)

    def _render_action_progress(self, payload: dict[str, Any]) -> None:
        now = time.monotonic()
        self._update_action_progress_state(payload, now)
        raw_percent = self._raw_action_progress_percent(payload)
        stable_percent = max(self._action_progress_percent, raw_percent)
        self._action_progress_percent = stable_percent
        self.progress_bar.setValue(stable_percent)
        self.progress_bar.setFormat(f"精确计算 {stable_percent}%")

        label = str(payload.get("label") or payload.get("event") or "计算中")
        label_parts = [label]
        if payload.get("derived_from_fixed_positions"):
            label_parts.append("汇总固定位置分支")
        spec_index = payload.get("spec_index")
        spec_total = payload.get("spec_total")
        if spec_index not in (None, "") and spec_total not in (None, ""):
            label_parts.append(f"action {spec_index}/{spec_total}")
        unit_label = payload.get("unit_label")
        if unit_label:
            label_parts.append(str(unit_label))
        self.progress_label.setText(" / ".join(label_parts))
        self.progress_meter_label.setText(
            self._action_progress_meter_text(payload, now, stable_percent)
        )

        detail_parts = []
        total = payload.get("total")
        if total not in (None, "", 0):
            detail_parts.append(
                "整体 "
                f"{_format_progress_count(payload.get('completed'))}/{_format_progress_count(total)}"
            )
        inner_text = self._action_progress_inner_text(payload)
        if inner_text:
            detail_parts.append(inner_text)
        if raw_percent < stable_percent and str(payload.get("event") or "") != "complete":
            detail_parts.append("计划已扩展，进度条保持不回退")
        if payload.get("derived_from_fixed_positions"):
            detail_parts.append("随机位置按固定位置分支概率加权汇总，不是单独随机枚举")
        if "dp_steps" in payload:
            detail_parts.append(f"内部步数 {payload['dp_steps']}")
        if "dp_states" in payload:
            detail_parts.append(f"DP状态 {payload['dp_states']}（诊断）")
        if "memo_hits" in payload:
            detail_parts.append(f"缓存命中 {payload['memo_hits']}")
        if "aggregated_outcome_cache_hits" in payload:
            detail_parts.append(f"outcome缓存命中 {payload['aggregated_outcome_cache_hits']}")
        if "aggregated_outcome_cache_misses" in payload:
            detail_parts.append(f"outcome缓存展开 {payload['aggregated_outcome_cache_misses']}")
        if "state_transition_cache_hits" in payload:
            detail_parts.append(f"状态转移缓存命中 {payload['state_transition_cache_hits']}")
        if "state_transition_cache_misses" in payload:
            detail_parts.append(f"状态转移展开 {payload['state_transition_cache_misses']}")

        if self._action_progress_started_at is not None:
            elapsed = now - self._action_progress_started_at
            detail_parts.append(f"已耗时 {_format_duration(elapsed)}")
        if self._last_action_progress_seen_at is not None:
            stale_seconds = now - self._last_action_progress_seen_at
            if stale_seconds >= 10:
                detail_parts.append("仍在精确计算，可取消；这不代表程序卡死。")
            elif stale_seconds >= 2:
                detail_parts.append(f"最近进度 {_format_duration(stale_seconds)} 前")
        self.progress_detail_label.setText(" | ".join(detail_parts))

    def _refresh_action_progress_clock(self) -> None:
        self._poll_action_process_progress()
        if not self._action_busy():
            self._progress_timer.stop()
            return
        payload = self._last_action_progress_payload or {"label": "正在等待计算进度"}
        self._render_action_progress(payload)

    def _update_action_buttons(self, busy: bool = False) -> None:
        busy = busy or self._action_busy()
        enabled = self.current_confirmed_digest is not None and not busy
        self.best_button.setEnabled(enabled)
        self.action_button.setEnabled(enabled)
        self.portfolio_button.setEnabled(enabled)
        self.cancel_action_button.setEnabled(self._action_process is not None)
        has_current_piece = self.current_table.rowCount() > 0
        self.confirm_button.setEnabled(not busy and has_current_piece)
        has_current_template = bool(str(self.current_template_combo.currentData() or ""))
        self.load_current_template_button.setEnabled(not busy and has_current_template)
        self.save_current_button.setEnabled(not busy and has_current_piece)
        self.rename_current_template_button.setEnabled(not busy and has_current_template)
        self.delete_current_template_button.setEnabled(not busy and has_current_template)
        self.load_example_button.setEnabled(not busy)
        self.add_inventory_button.setEnabled(not busy)
        has_selected_inventory = self._has_selected_inventory_piece()
        has_inventory_piece = self.inventory_table.rowCount() > 0
        self.copy_inventory_button.setEnabled(not busy and has_selected_inventory)
        self.clear_substats_button.setEnabled(not busy and has_selected_inventory)
        self.delete_inventory_button.setEnabled(not busy and has_selected_inventory)
        self.save_inventory_button.setEnabled(not busy)
        self.export_inventory_button.setEnabled(not busy and has_inventory_piece)
        self.clear_inventory_filters_button.setEnabled(not busy and self._inventory_filters_active())
        self.inventory_card_scroll.setEnabled(not busy)
        for card in self.current_cards:
            card.setEnabled(not busy)

    def _collect_current_or_warn(self) -> list[GearPiece] | None:
        game = self.selected_game()
        pieces, warnings = self.current_table.collect_pieces()
        try:
            validate_current_gear_against_game(pieces, game, require_complete=True)
        except Exception as exc:
            warnings.append(str(exc))
        if warnings:
            self._show_warning("当前装备还不能确认", warnings)
            return None
        return pieces

    def _collect_current_partial_or_warn(self) -> list[GearPiece] | None:
        game = self.selected_game()
        pieces, warnings = self.current_table.collect_pieces()
        try:
            validate_current_gear_against_game(pieces, game, require_complete=False)
        except Exception as exc:
            warnings.append(str(exc))
        if warnings:
            self._show_warning("当前装备快照还不能用于 BOX 审计", warnings)
            return None
        return pieces

    def _collect_current_template_or_warn(self) -> list[GearPiece] | None:
        pieces, warnings = self.current_table.collect_pieces()
        if warnings:
            self._show_warning("当前装备快照里有不能保存的装备", warnings)
            return None
        if not pieces:
            QMessageBox.warning(self, "没有可保存的当前装备快照", "当前装备还是空的，请先录入或从库存装备。")
            return None
        return pieces

    def _collect_inventory_or_warn(self) -> list[GearPiece] | None:
        pieces, warnings = self.inventory_table.collect_pieces()
        if warnings:
            self._show_warning("库存里有不能计算的装备", warnings)
            return None
        return pieces

    def _confirm_inventory_duplicate_save(self, pieces: list[GearPiece]) -> bool:
        exact_groups = _inventory_duplicate_groups(pieces)
        unordered_groups = _inventory_duplicate_groups(pieces, unordered_substats=True)
        exact_row_sets = {tuple(rows) for rows in exact_groups}
        similar_groups = [
            rows for rows in unordered_groups if tuple(rows) not in exact_row_sets
        ]
        if not exact_groups and not similar_groups:
            return True

        parts = ["保存前发现库存里可能有重复装备："]
        if exact_groups:
            parts.append(f"完全重复：{_duplicate_group_summary(exact_groups)}")
        if similar_groups:
            parts.append(f"疑似重复（副属性顺序不同但内容一致）：{_duplicate_group_summary(similar_groups)}")
        parts.append("继续保存会保留这些重复项；取消后可以先删除或整理库存。")
        answer = QMessageBox.question(
            self,
            "库存疑似重复",
            "\n\n".join(parts),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_empty_inventory_overwrite(self, pieces: list[GearPiece]) -> bool:
        if pieces:
            return True
        game_id = self.selected_game().id
        target_id = self.selected_storage_character_id()
        source_id = self._inventory_loaded_storage_id or target_id
        path = user_inventory_store_path(game_id, target_id)
        overwrites_target = path.exists()
        masks_source = source_id != target_id
        if not overwrites_target and not masks_source:
            return True
        risk_parts = ["当前库存为空；继续保存会写入 0 件库存。"]
        if overwrites_target:
            risk_parts.append("这会把已保存的本机库存覆盖为空列表。")
        if masks_source:
            risk_parts.append(
                f"当前显示的库存来源是 {source_id}；保存后会优先读取 {target_id} 的空库存，旧来源库存会被遮住。"
            )
        risk_parts.extend(
            [
                f"将写入的文件：{path}",
                "如果只是筛选后看不到库存，请先点“清除筛选”；如果确实要清空本机库存，再选择继续。",
            ]
        )
        answer = QMessageBox.question(
            self,
            "保存空库存？",
            "\n\n".join(risk_parts),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def confirm_current(self) -> None:
        pieces = self._collect_current_or_warn()
        if pieces is None:
            return
        self.current_confirmed_digest = _pieces_digest(pieces)
        analysis = analyse_current_gear(pieces, self.selected_game(), self.selected_character())
        self._last_weakest_label = analysis.weakest_position_name or "-"
        self.progress_label.setText(
            f"当前装备已确认。最弱位置：{analysis.weakest_position_name or '-'}。"
        )
        self._update_action_buttons()
        self._refresh_overview()

    def load_current_template(self) -> None:
        template = self._selected_current_template()
        if template is None:
            QMessageBox.information(self, "没有当前装备快照", "当前代理人还没有保存过当前装备快照。")
            return
        storage_id = str(template.get("_storage_id") or self.selected_storage_character_id())
        self.current_table.set_context(
            self.selected_game(),
            self.selected_character(),
            list(template["pieces"]),
        )
        self._current_changed()
        self._loaded_current_snapshot_id = str(template["id"])
        self._loaded_current_snapshot_storage_id = storage_id
        self.progress_label.setText(f"已载入当前装备快照：{template['label']}。")

    def save_current(self) -> None:
        pieces = self._collect_current_template_or_warn()
        if pieces is None:
            return
        current = self._selected_current_template()
        default_label = (
            str(current["label"])
            if current is not None and self._selected_current_snapshot_is_loaded()
            else "当前装备"
        )
        label, ok = QInputDialog.getText(self, "保存当前装备快照", "快照名称", text=default_label)
        if not ok:
            return
        saved = save_user_current_gear(
            self.selected_game().id,
            self.selected_storage_character_id(),
            pieces,
            label or "当前装备",
        )
        self._loaded_current_snapshot_id = str(saved["id"])
        self._loaded_current_snapshot_storage_id = self.selected_storage_character_id()
        self._refresh_current_template_controls(saved["id"])
        self.progress_label.setText(f"已保存当前装备快照：{saved['label']}（{len(pieces)}/6 件）。")

    def rename_current_template(self) -> None:
        template = self._selected_current_template()
        if template is None:
            QMessageBox.information(self, "没有当前装备快照", "当前代理人还没有保存过当前装备快照。")
            return
        was_loaded = self._selected_current_snapshot_is_loaded()
        storage_id = str(template.get("_storage_id") or self.selected_storage_character_id())
        label, ok = QInputDialog.getText(
            self,
            "重命名当前装备快照",
            "快照名称",
            text=str(template["label"]),
        )
        if not ok:
            return
        saved = save_user_current_gear(
            self.selected_game().id,
            storage_id,
            list(template["pieces"]),
            label or str(template["label"]),
        )
        if saved["id"] != template["id"]:
            delete_user_current_gear(
                self.selected_game().id,
                storage_id,
                str(template["id"]),
            )
        if was_loaded:
            self._loaded_current_snapshot_id = str(saved["id"])
            self._loaded_current_snapshot_storage_id = storage_id
        self._refresh_current_template_controls(saved["id"])
        self.progress_label.setText(f"已重命名当前装备快照：{saved['label']}。")

    def delete_current_template(self) -> None:
        template = self._selected_current_template()
        if template is None:
            QMessageBox.information(self, "没有当前装备快照", "当前代理人还没有保存过当前装备快照。")
            return
        answer = QMessageBox.question(
            self,
            "删除当前装备快照？",
            f"确定删除当前装备快照“{template['label']}”吗？当前正在编辑的盘面不会被清空。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        was_loaded = self._selected_current_snapshot_is_loaded()
        delete_user_current_gear(
            self.selected_game().id,
            str(template.get("_storage_id") or self.selected_storage_character_id()),
            str(template["id"]),
        )
        if was_loaded:
            self._clear_loaded_current_snapshot()
        self._refresh_current_template_controls()
        self.progress_label.setText(f"已删除当前装备快照：{template['label']}。当前编辑盘面不变。")

    def load_example_current(self) -> None:
        game = self.selected_game()
        character = self.selected_character()
        examples = list_current_examples(game.id, self.selected_legacy_storage_character_id())
        if not examples:
            QMessageBox.information(self, "没有示例", "当前游戏、代理人或目标模板没有当前装备示例。")
            return
        pieces = _complete_position_pieces(game, character, load_current_example(examples[0]["path"]))
        self.current_table.set_context(game, character, pieces)
        self._current_changed()

    def add_inventory(self) -> None:
        game = self.selected_game()
        character = self.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id).model_copy(update={"locked": False})
        dialog = GearPieceEditDialog(
            game,
            character,
            piece,
            editable_position=True,
            title="新增库存件",
            parent=self,
            optimal_check_callback=lambda candidate: self._optimal_loadout_check_text(
                "new_inventory",
                None,
                candidate,
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.piece is None:
            self.progress_label.setText("已取消新增库存；库存未变化。")
            return
        new_source_row = self.inventory_table.rowCount()
        self.inventory_table.add_piece(dialog.piece)
        self._focus_inventory_source_row(new_source_row)
        self.tabs.setCurrentIndex(1)
        self.progress_label.setText(
            "已添加一件库存；不会自动计算。"
            + self._inventory_filter_hidden_suffix(new_source_row)
        )

    def copy_selected_inventory(self) -> None:
        source_row = self._selected_inventory_source_row()
        if source_row is None:
            self.progress_label.setText("请先选中一件库存。")
            return
        self.copy_inventory_piece(source_row)

    def copy_inventory_piece(self, source_row: int | None) -> None:
        pieces = self._hidden_table_pieces(self.inventory_table)
        if source_row is None or source_row < 0 or source_row >= len(pieces):
            self.progress_label.setText("库存行已不存在，请重新选择。")
            return
        new_source_row = len(pieces)
        self.inventory_table.add_piece(pieces[source_row].model_copy(deep=True))
        self._focus_inventory_source_row(new_source_row)
        self.progress_label.setText(
            "已复制选中库存；新副本会标记为重复，保存前会再次提醒。"
            + self._inventory_filter_hidden_suffix(new_source_row)
        )

    def clear_selected_inventory_substats(self) -> None:
        source_row = self._selected_inventory_source_row()
        if source_row is None:
            self.progress_label.setText("请先选中一件库存。")
            return
        self.clear_inventory_piece_substats(source_row)

    def clear_inventory_piece_substats(self, source_row: int | None) -> None:
        pieces = self._hidden_table_pieces(self.inventory_table)
        if source_row is None or source_row < 0 or source_row >= len(pieces):
            self.progress_label.setText("库存行已不存在，请重新选择。")
            return
        piece = pieces[source_row]
        answer = QMessageBox.question(
            self,
            "清空副词条？",
            (
                f"确定清空库存 #{source_row + 1} 的副词条吗？\n"
                f"{self.selected_game().position_name(piece.position)} / {piece.set_name} / {piece.main_stat} / +{piece.level}\n\n"
                "清空只影响当前本机库存草稿，仍需点击“保存库存到本机”才会持久化。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.progress_label.setText("已取消清空副词条；库存未变化。")
            return
        pieces[source_row] = pieces[source_row].model_copy(
            update={"substats": [], "revealed_next_substat": None}
        )
        self.inventory_table.set_context(self.selected_game(), self.selected_character(), pieces)
        self._inventory_changed()
        self.progress_label.setText(
            "已清空选中库存副词条；不会自动计算。"
            + self._inventory_filter_hidden_suffix(source_row)
        )

    def delete_inventory(self) -> None:
        source_row = self._selected_inventory_source_row()
        if source_row is None:
            self.progress_label.setText("请先选中一件库存。")
            return
        self.delete_inventory_piece(source_row)

    def delete_inventory_piece(self, source_row: int | None) -> None:
        pieces = self._hidden_table_pieces(self.inventory_table)
        if source_row is None or source_row < 0 or source_row >= len(pieces):
            self.progress_label.setText("库存行已不存在，请重新选择。")
            return
        piece = pieces[source_row]
        answer = QMessageBox.question(
            self,
            "删除库存件？",
            (
                f"确定删除库存 #{source_row + 1} 吗？\n"
                f"{self.selected_game().position_name(piece.position)} / {piece.set_name} / {piece.main_stat} / +{piece.level}\n\n"
                "删除只影响当前本机库存草稿，仍需点击“保存库存到本机”才会持久化。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.progress_label.setText("已取消删除库存；库存未变化。")
            return
        pieces.pop(source_row)
        self._selected_inventory_source_row_value = (
            min(source_row, len(pieces) - 1)
            if pieces
            else None
        )
        self.inventory_table.set_context(self.selected_game(), self.selected_character(), pieces)
        self._inventory_changed()
        self.progress_label.setText("已删除选中库存；不会自动计算。")

    def equip_inventory_piece(self, source_row: int | None) -> None:
        inventory_pieces = self._hidden_table_pieces(self.inventory_table)
        current_pieces = self._hidden_table_pieces(self.current_table)
        if source_row is None or source_row < 0 or source_row >= len(inventory_pieces):
            self.progress_label.setText("库存行已不存在，请重新选择。")
            return
        target_piece = inventory_pieces[source_row]
        target_position = position_key(target_piece.position)
        current_index = next(
            (
                index
                for index, piece in enumerate(current_pieces)
                if position_key(piece.position) == target_position
            ),
            None,
        )
        if current_index is None:
            current_pieces.append(target_piece.model_copy(deep=True))
            del inventory_pieces[source_row]
            returned_inventory_row: int | None = None
        else:
            previous_current = current_pieces[current_index]
            current_pieces[current_index] = target_piece.model_copy(deep=True)
            inventory_pieces[source_row] = previous_current.model_copy(deep=True)
            returned_inventory_row = source_row
        game = self.selected_game()
        character = self.selected_character()
        self.current_table.set_context(game, character, current_pieces)
        self.inventory_table.set_context(game, character, inventory_pieces)
        self.current_confirmed_digest = None
        self._selected_inventory_source_row_value = returned_inventory_row
        self._refresh_current_cards()
        self._refresh_inventory_filters()
        if returned_inventory_row is not None:
            self._focus_inventory_source_row(returned_inventory_row)
        else:
            self._refresh_inventory_view()
        self._clear_results("已完成当前装备和库存互换，请重新确认当前装备。")
        self._update_action_buttons()
        returned_current_suffix = (
            self._inventory_filter_hidden_suffix(source_row, "换回库存的旧当前件")
            if current_index is not None
            else ""
        )
        returned_label = f"库存 #{source_row + 1} 现在是换下来的旧当前件" if current_index is not None else ""
        self.progress_label.setText(
            f"已装备库存 #{source_row + 1} 到 {game.position_name(target_piece.position)}"
            + (f"；{returned_label}。" if returned_label else "；该槽位之前为空。")
            + returned_current_suffix
        )

    def save_inventory(self) -> None:
        pieces = self._collect_inventory_or_warn()
        if pieces is None:
            return
        if not self._confirm_empty_inventory_overwrite(pieces):
            self.progress_label.setText("已取消保存空库存；本机库存未变化。")
            return
        if not self._confirm_inventory_duplicate_save(pieces):
            self.progress_label.setText("已取消保存库存；请先处理重复装备。")
            return
        path = save_user_inventory(self.selected_game().id, self.selected_storage_character_id(), pieces)
        self._inventory_loaded_storage_id = self.selected_storage_character_id()
        self._refresh_inventory_view()
        self.progress_label.setText(f"已保存 {len(pieces)} 件库存：{path}")

    def export_inventory_details(self) -> None:
        pieces = self._hidden_table_pieces(self.inventory_table)
        if not pieces:
            self.progress_label.setText("库存为空，暂无可导出的完整明细。")
            return
        duplicate_labels = _inventory_duplicate_row_labels(pieces)
        duplicate_summary = _inventory_duplicate_export_summary(pieces)
        input_audit = self._input_audit_text()
        output_path = PROJECT_ROOT / "reports" / "inventory_export.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {
                    "game_id": self.selected_game().id,
                    "storage_id": self.selected_storage_character_id(),
                    "legacy_storage_id": self.selected_legacy_storage_character_id(),
                    "target_template_id": self.selected_character().id,
                    "target_template_name": self.selected_character().name,
                    "agent_id": self.selected_agent().agent_id if self.selected_agent() is not None else "",
                    "inventory_loaded_storage_id": self._inventory_loaded_storage_id,
                    "character_id": self.selected_storage_character_id(),
                    "input_audit": input_audit,
                    "input_audit_lines": input_audit.splitlines(),
                    "duplicate_summary": duplicate_summary,
                    "pieces": [
                        _inventory_export_piece_payload(
                            piece,
                            index,
                            duplicate_labels.get(index - 1, ""),
                        )
                        for index, piece in enumerate(pieces, start=1)
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.progress_label.setText(f"已导出 {len(pieces)} 件库存完整明细：{output_path}")

    def _ensure_current_still_confirmed(self, pieces: list[GearPiece]) -> bool:
        if self.current_confirmed_digest != _pieces_digest(pieces):
            QMessageBox.warning(self, "需要重新确认", "当前装备已变化，请先点击“确认当前装备”。")
            self.current_confirmed_digest = None
            self._update_action_buttons()
            return False
        return True

    def _restore_worker_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            if "__gear_piece__" in value:
                return GearPiece.model_validate(value["__gear_piece__"])
            return {key: self._restore_worker_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._restore_worker_value(item) for item in value]
        return value

    def _worker_rows_from_output(self) -> list[dict[str, Any]]:
        if not self._action_output_path:
            return []
        payload = json.loads(Path(self._action_output_path).read_text(encoding="utf-8-sig"))
        self._set_action_execution_metadata(
            str(payload.get("engine") or self._last_action_engine or DEFAULT_ACTION_EV_ENGINE),
            str(payload.get("execution_mode") or self._last_action_execution_mode or "worker_process"),
        )
        rows = payload.get("rows", [])
        if not isinstance(rows, list):
            raise ValueError("worker output rows must be a list")
        return [self._restore_worker_value(row) for row in rows]

    def _worker_error_text(self) -> str:
        if not self._action_error_path or not Path(self._action_error_path).exists():
            return "Action EV worker failed without writing an error file."
        payload = json.loads(Path(self._action_error_path).read_text(encoding="utf-8-sig"))
        traceback_text = str(payload.get("traceback") or "")
        message = str(payload.get("message") or "Action EV worker failed.")
        return traceback_text or message

    def _poll_action_process_progress(self) -> None:
        if not self._action_progress_path:
            return
        path = Path(self._action_progress_path)
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(self._action_progress_offset)
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    self._last_action_progress_payload = payload
                    self._last_action_progress_seen_at = time.monotonic()
            self._action_progress_offset = handle.tell()

    def _action_process_environment(self) -> QProcessEnvironment:
        env = QProcessEnvironment.systemEnvironment()
        existing = env.value("PYTHONPATH", "")
        src_path = str(PROJECT_ROOT / "src")
        env.insert("PYTHONPATH", src_path if not existing else f"{src_path}{os.pathsep}{existing}")
        env.insert("PYTHONIOENCODING", "utf-8")
        return env

    def _current_action_ev_engine(self) -> str:
        return normalize_action_ev_engine(os.environ.get(ACTION_EV_ENGINE_ENV) or DEFAULT_ACTION_EV_ENGINE)

    def _set_action_execution_metadata(self, engine: str, execution_mode: str) -> None:
        self._last_action_engine = normalize_action_ev_engine(engine)
        self._last_action_execution_mode = execution_mode

    def _start_action_ev_process(
        self,
        current_pieces: list[GearPiece],
        inventory_pieces: list[GearPiece],
        horizon: int,
        engine: str,
    ) -> None:
        run_id = uuid.uuid4().hex
        run_dir = Path(tempfile.mkdtemp(prefix=f"{ACTION_PROCESS_TEMP_PREFIX}{run_id[:8]}-"))
        input_path = run_dir / "input.json"
        output_path = run_dir / "result.json"
        progress_path = run_dir / "progress.jsonl"
        error_path = run_dir / "error.json"
        summary_path = run_dir / "summary.json"
        input_audit = self._input_audit_text()
        payload = {
            "run_id": run_id,
            "game_id": self.selected_game().id,
            "character_id": self.selected_character().id,
            "probability_model_id": self.selected_probability_model().id,
            "current_pieces": [_model_payload(piece) for piece in current_pieces],
            "inventory_pieces": [_model_payload(piece) for piece in inventory_pieces],
            "horizon": horizon,
            "engine": engine,
            "input_audit": input_audit,
            "input_audit_lines": input_audit.splitlines(),
        }
        input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(
            [
                "-m",
                "gear_optimizer.action_ev_worker",
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
        process.setProcessEnvironment(self._action_process_environment())
        process.setWorkingDirectory(str(PROJECT_ROOT))
        process.readyReadStandardError.connect(self._append_action_process_stderr)
        process.readyReadStandardOutput.connect(self._append_action_process_stdout)
        process.finished.connect(self._on_action_process_finished)
        process.errorOccurred.connect(self._on_action_process_error)

        self._action_process = process
        self._action_process_cancel_requested = False
        self._action_run_dir = str(run_dir)
        self._action_input_path = str(input_path)
        self._action_output_path = str(output_path)
        self._action_progress_path = str(progress_path)
        self._action_error_path = str(error_path)
        self._action_summary_path = str(summary_path)
        self._action_progress_offset = 0
        self._set_action_execution_metadata(engine, "worker_process")
        self._start_action_progress()
        self.progress_detail_label.setText(
            f"horizon=2 正在子进程中精确计算；engine={engine}；主窗口可继续切换 Tab，也可取消。"
        )
        self.log.append(f"Action EV engine: {_engine_label(engine)}；执行方式：QProcess 子进程。")
        self._update_action_buttons(busy=True)
        process.start()

    def _on_action_process_error(self, error: QProcess.ProcessError) -> None:
        if self._action_process_cancel_requested:
            return
        self.log.append(f"Action EV worker process error: {error}")

    def _append_action_process_stderr(self) -> None:
        if self._action_process is None:
            return
        text = bytes(self._action_process.readAllStandardError()).decode("utf-8", errors="replace")
        if text.strip():
            self.log.append(text.strip())

    def _append_action_process_stdout(self) -> None:
        if self._action_process is None:
            return
        text = bytes(self._action_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if text.strip():
            self.log.append(text.strip())

    def _clear_action_process_state(self) -> None:
        self._action_process = None
        self._action_process_cancel_requested = False

    def cancel_action_ev(self) -> None:
        if self._action_process is not None:
            self._action_process_cancel_requested = True
            self.progress_label.setText("正在取消 Action EV 计算。")
            self.progress_meter_label.setText("取消中 | 已停止接收新推荐")
            self.progress_detail_label.setText("用户取消，未生成新推荐。")
            self.log.append("用户取消 Action EV 精确计算，未生成新推荐。")
            self.log_toggle_button.setChecked(True)
            self._action_process.terminate()
            QTimer.singleShot(1500, self._kill_action_process_if_running)
        elif self._worker_thread is not None:
            self.log.append("当前 horizon=1 计算无法安全中断；请等待它完成。")

    def _kill_action_process_if_running(self) -> None:
        if self._action_process is not None and self._action_process.state() != QProcess.ProcessState.NotRunning:
            self._action_process.kill()

    def _on_action_process_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        self._poll_action_process_progress()
        cancelled = self._action_process_cancel_requested
        self._stop_action_progress()
        self._clear_action_process_state()
        if cancelled:
            self.progress_label.setText("Action EV 计算已取消。")
            self.progress_meter_label.setText("已取消 | 未更新推荐")
            self.progress_detail_label.setText("用户取消，未生成新推荐。")
            self.result_recommend_title.setText("计算已取消")
            self.result_recommend_detail.setText(
                f"用户取消，未生成新推荐；旧结果未被覆盖。\n{self._action_execution_summary_text()}"
            )
            self.log.append("Action EV worker 已停止：用户取消，未生成新推荐。")
            self.log_toggle_button.setChecked(True)
            self.result_tabs.setCurrentIndex(4)
            self._update_action_buttons()
            self._refresh_overview()
            return
        if exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0:
            self._on_action_failed(self._worker_error_text())
            return
        try:
            rows = self._worker_rows_from_output()
        except Exception:
            self._on_action_failed(traceback.format_exc())
            return
        self._on_action_finished(rows)
        if self._action_run_dir:
            removed = cleanup_successful_action_run_dirs(Path(self._action_run_dir).parent)
            if removed:
                self.log.append(f"已清理 {len(removed)} 个旧的成功 Action EV 临时目录。")

    def run_best_loadout(self) -> None:
        current_pieces = self._collect_current_or_warn()
        if current_pieces is None or not self._ensure_current_still_confirmed(current_pieces):
            return
        inventory_pieces = self._collect_inventory_or_warn()
        if inventory_pieces is None:
            return
        rows = best_loadout_rows(
            [*current_pieces, *inventory_pieces],
            self.selected_game(),
            self.selected_character(),
            current_count=len(current_pieces),
            include_upgrade_expectation=True,
        )
        game = self.selected_game()
        self._fill_table(
            self.best_table,
            _loadout_display_rows(rows, game, len(current_pieces)),
        )
        self._highlighted_inventory_source_rows = _inventory_source_rows_from_loadout_rows(
            rows,
            len(current_pieces),
        )
        self._highlighted_inventory_label = "最优"
        if self._highlighted_inventory_source_rows:
            self._selected_inventory_source_row_value = min(self._highlighted_inventory_source_rows)
        self._refresh_inventory_view()
        self._has_calculated_once = True
        self._results_stale = False
        self._last_recommended_action_summary = "当前最优搭配已更新（含未满级强化期望）。"
        self._last_main_metric_summary = _loadout_result_summary(
            rows,
            len(current_pieces),
            len(current_pieces) + len(inventory_pieces),
        )
        self.result_recommend_title.setText("当前最优搭配已更新（含强化期望）")
        self.result_recommend_detail.setText(self._last_main_metric_summary)
        first_set = str(rows[0].get("set_name") or "") if rows else ""
        self._set_result_recommend_icon(first_set or None)
        self.tabs.setCurrentIndex(3)
        self.result_tabs.setCurrentIndex(2)
        self.progress_label.setText("当前最优搭配已计算完成；未满级按满级强化期望估值。")
        self._refresh_overview()

    def run_portfolio_audit(self) -> None:
        current_pieces = self._collect_current_partial_or_warn()
        if current_pieces is None:
            return
        inventory_pieces = self._collect_inventory_or_warn()
        if inventory_pieces is None:
            return
        selection = self._select_portfolio_targets_dialog()
        if selection is None:
            self.progress_label.setText("已取消 BOX 多代理人审计。")
            return
        targets, mode = selection
        if not targets:
            QMessageBox.information(self, "未选择代理人", "请至少选择一个代理人参与 BOX 审计。")
            self.progress_label.setText("BOX 审计未运行：未选择代理人。")
            return
        try:
            rows = portfolio_action_rows(
                self.selected_game(),
                self.selected_probability_model(),
                targets,
                current_pieces,
                inventory_pieces,
                mode=mode,
                horizon=1,
                action_scope="tuning",
            )
        except Exception as exc:
            self.progress_label.setText("BOX 多代理人审计失败。")
            self.log.append(f"BOX Portfolio EV failed: {type(exc).__name__}: {exc}")
            self.log_toggle_button.setChecked(True)
            self.result_tabs.setCurrentIndex(4)
            return

        display_rows = [row.to_display_row() for row in rows]
        self._fill_table(self.portfolio_table, display_rows)
        target_names = "、".join(target.name for target in targets)
        self.portfolio_status_label.setText(
            f"BOX H=1 审计完成：{len(rows)} 个 action；模式={mode.label}；"
            f"目标代理人={target_names}。\n"
            "说明：Portfolio EV 只统计进入更优 best_loadout 的成型收益；"
            "建设审计单独展示，不参与主 EV 排序；"
            "本表为 BOX 调律审计，不混入库存强化；"
            "Phase 1 不做 H=2，不做同队装备互斥精确分配，不替换单角色推荐。"
        )
        self.progress_label.setText("BOX 多代理人审计已计算完成。")
        self.log.append(
            f"BOX Portfolio EV 完成：mode={mode.value}；targets={target_names}；rows={len(rows)}。"
        )
        self.result_tabs.setCurrentIndex(3)
        self.tabs.setCurrentIndex(3)
        self._refresh_overview()

    def run_action_ev(self) -> None:
        current_pieces = self._collect_current_or_warn()
        if current_pieces is None or not self._ensure_current_still_confirmed(current_pieces):
            return
        inventory_pieces = self._collect_inventory_or_warn()
        if inventory_pieces is None:
            return
        try:
            engine = self._current_action_ev_engine()
        except ValueError as exc:
            QMessageBox.warning(self, "Action EV 引擎配置无效", str(exc))
            return
        horizon = int(self.horizon_combo.currentData() or 1)
        if horizon == 2:
            self._start_action_ev_process(current_pieces, inventory_pieces, horizon, engine)
            self.tabs.setCurrentIndex(3)
            return
        self._update_action_buttons(busy=True)
        self._set_action_execution_metadata(engine, "qthread")
        self.log.append(f"Action EV engine: {_engine_label(engine)}；执行方式：QThread 后台线程。")
        self._start_action_progress()
        self.progress_detail_label.setText(f"horizon=1 正在后台线程精确计算；engine={engine}。")
        self._worker_thread = QThread(self)
        self._worker = ActionEvWorker(
            self.selected_game(),
            self.selected_character(),
            self.selected_probability_model(),
            current_pieces,
            inventory_pieces,
            horizon,
            engine,
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_action_progress)
        self._worker.finished.connect(self._on_action_finished)
        self._worker.failed.connect(self._on_action_failed)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.failed.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()
        self.tabs.setCurrentIndex(3)

    def _on_action_progress(self, payload: dict) -> None:
        self._last_action_progress_payload = dict(payload)
        self._last_action_progress_seen_at = time.monotonic()

    def _render_action_table(self) -> None:
        display_rows = [_action_display_row(row) for row in self._action_result_rows]
        total = len(display_rows)
        if total == 0:
            self._fill_table(self.action_table, [])
            self.action_table_status_label.setText("尚无 Action EV 明细。")
            self.show_all_actions_button.setEnabled(False)
            self.show_all_actions_button.setText("显示全部")
            return

        limit = ACTION_DETAIL_DISPLAY_LIMIT
        visible_rows = display_rows if self._show_all_action_rows else display_rows[:limit]
        self._fill_table(self.action_table, visible_rows)
        shown = len(visible_rows)
        upgrade_count = sum(1 for row in self._action_result_rows if row.get("策略") == "强化库存胚子")
        tuning_count = total - upgrade_count
        scope_text = f"调律母盘 {tuning_count} 条，库存升级机会 {upgrade_count} 条；库存升级不参与主调律推荐。"
        if total > limit:
            self.action_table_status_label.setText(
                f"默认按推荐口径显示前 {limit} 条；完整精确结果共 {total} 条，{scope_text}可展开审计。"
            )
            self.show_all_actions_button.setEnabled(True)
            self.show_all_actions_button.setText(
                f"收起到前 {limit} 条" if self._show_all_action_rows else f"显示全部 {total} 条"
            )
        else:
            self.action_table_status_label.setText(f"已显示全部 {shown} 条 Action EV 明细；{scope_text}")
            self.show_all_actions_button.setEnabled(False)
            self.show_all_actions_button.setText("已显示全部")

    def toggle_action_rows(self) -> None:
        if len(self._action_result_rows) <= ACTION_DETAIL_DISPLAY_LIMIT:
            return
        self._show_all_action_rows = not self._show_all_action_rows
        self._render_action_table()

    def _action_gain_summary_text(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        horizon = int(rows[0].get("horizon") or self.horizon_combo.currentData() or 1)
        if horizon != 1:
            return ""
        valid_tuning_rows = [
            row
            for row in rows
            if not str(row.get("套装约束") or "").startswith("未满足")
            and row.get("策略") != "强化库存胚子"
        ]
        positive_tuning_rows = [
            row for row in valid_tuning_rows if _action_row_has_positive_gain(row)
        ]
        upgrade_rows = [
            row
            for row in rows
            if row.get("策略") == "强化库存胚子"
            and not str(row.get("套装约束") or "").startswith("未满足")
        ]
        positive_upgrade_rows = [row for row in upgrade_rows if _action_row_has_positive_gain(row)]
        parts: list[str] = []
        if not valid_tuning_rows:
            parts.append("调律策略：没有满足当前套装硬约束的策略")
        elif not positive_tuning_rows:
            parts.append("调律策略：当前可用调律 action 均无有效提升")
        else:
            best_tuning = max(
                positive_tuning_rows,
                key=lambda row: _float_value(row.get("有效/母盘")),
            )
            parts.append(
                f"调律策略：{len(positive_tuning_rows)}/{len(valid_tuning_rows)} 个有效提升为正；"
                f"调律有效/母盘最高为 {best_tuning.get('有效/母盘', '-')}"
            )
        if positive_upgrade_rows:
            best_upgrade = max(
                positive_upgrade_rows,
                key=lambda row: _float_value(row.get("有效提升")),
            )
            parts.append(
                f"库存升级机会：{len(positive_upgrade_rows)}/{len(upgrade_rows)} 个升级机会有效提升为正；"
                f"最高期望有效提升 {best_upgrade.get('有效提升', '-')}；"
                "非调律，仅提示，不参与主调律推荐"
            )
        elif upgrade_rows:
            parts.append("库存升级机会：暂无有效提升；非调律，仅提示")
        return "H=1 快速判断：" + "；".join(parts) + "。"

    def _recommended_action_card_text(self, row: dict[str, Any]) -> str:
        is_upgrade = row.get("策略") == "强化库存胚子"
        if is_upgrade:
            ranking_scope = "库存升级机会不参与主调律推荐；仅在没有有效提升为正的调律 action 时，作为非调律机会展示"
        else:
            ranking_scope = "桌面主推荐先要求有效提升为正，并通过固定/锁定比较门槛；再按有效/母盘、有效提升排序，审计排序向量仅作 tie-break"
        fields = [
            ("动作类型", _action_type_label(row)),
            ("推荐动作" if not is_upgrade else "机会动作", _action_display_strategy_label(row)),
            ("目标套装", row.get("目标套装", "-")),
            ("目标位置", row.get("位置", "-")),
            ("主属性", row.get("主属性", "-")),
            ("固定副属性", row.get("固定副属性", "-")),
            ("horizon", row.get("horizon", "-")),
            ("方案类型", row.get("方案类型", "-")),
            ("第一步 action", row.get("第一步 action", "-")),
            ("第二步策略摘要", row.get("第二步策略摘要", "-")),
            ("有效期望", _effective_gain_summary(row)),
            ("增益判断", _action_gain_label(row)),
            ("有效/母盘", row.get("有效/母盘", "-")),
            ("比较口径", row.get("比较口径", row.get("相对随机", "-"))),
            ("排序口径", ranking_scope),
            ("计算口径", "精确；完整概率分布枚举，不使用 Monte Carlo/近似/partial 推荐"),
            ("计算引擎", _engine_label(str(row.get("_engine") or self._last_action_engine))),
            ("执行方式", _execution_mode_label(str(row.get("_execution_mode") or self._last_action_execution_mode))),
        ]
        if is_upgrade:
            fields.insert(
                3,
                (
                    "库存编号",
                    _inventory_label_from_piece_id(
                        row.get("_upgrade_inventory_id"),
                        self.current_table.rowCount(),
                    ),
                ),
            )
        detail = "\n".join(f"{label}：{_format_value(value)}" for label, value in fields)
        explanation = _action_row_explanation(row)
        if explanation:
            detail = f"{detail}\n说明：{explanation}"
        return detail

    def _action_execution_summary_text(self) -> str:
        return (
            f"计算引擎：{_engine_label(self._last_action_engine)}\n"
            f"执行方式：{_execution_mode_label(self._last_action_execution_mode)}"
        )

    def _action_plan_summary_text(self, row: dict[str, Any]) -> str:
        plan_type = str(row.get("方案类型") or "-")
        fields = [
            ("方案类型", plan_type),
            ("动作类型", _action_type_label(row)),
            ("第一步 action", row.get("第一步 action", "-")),
            ("第二步策略摘要", row.get("第二步策略摘要", "-")),
            ("比较口径", row.get("比较口径", row.get("相对随机", "-"))),
            ("代表路径说明", row.get("代表路径说明", "-")),
        ]
        if plan_type == "条件策略":
            fields.append(("代表分支搭配", "混合结果，不存在唯一典型搭配"))
        else:
            fields.extend(
                [
                    ("代表路径", row.get("代表路径", "-")),
                    ("代表分支搭配", row.get("代表分支搭配", row.get("预期搭配", "-"))),
                ]
            )
        return "\n".join(f"{label}：{_format_value(value)}" for label, value in fields)

    def _render_action_plan(self, recommended: dict[str, Any] | None) -> None:
        if not recommended:
            self.action_plan_summary_label.setText("尚无 H=2 方案。")
            self._fill_table(self.action_plan_branch_table, [])
            self._fill_table(self.action_plan_loadout_table, [])
            return

        self.action_plan_summary_label.setText(self._action_plan_summary_text(recommended))
        raw_branches = recommended.get("条件分支")
        branches = [dict(branch) for branch in raw_branches] if isinstance(raw_branches, list) else []
        self._fill_table(self.action_plan_branch_table, branches)

        raw_loadout_rows = recommended.get("_representative_loadout_rows")
        plan_type = str(recommended.get("方案类型") or "")
        if plan_type == "条件策略":
            loadout_rows = []
        elif isinstance(raw_loadout_rows, list):
            loadout_rows = _loadout_display_rows(
                raw_loadout_rows,
                self.selected_game(),
                self.current_table.rowCount(),
            )
        else:
            loadout_rows = []
        self._fill_table(self.action_plan_loadout_table, loadout_rows)

    def _on_action_finished(self, rows: list[dict]) -> None:
        self._stop_action_progress()
        self._worker = None
        self._worker_thread = None
        self._action_progress_percent = 100
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("精确计算 100%")
        self._action_result_rows = _sorted_action_rows([
            {
                **dict(row),
                "_engine": self._last_action_engine,
                "_execution_mode": self._last_action_execution_mode,
            }
            for row in rows
        ])
        self._show_all_action_rows = False
        self._render_action_table()
        raw_recommended = recommended_action_ev_row(rows)
        recommended = _desktop_recommended_action_row(self._action_result_rows)
        best_upgrade = _best_positive_upgrade_row(self._action_result_rows)
        highlight_row = recommended if recommended is not None else best_upgrade
        self._highlighted_inventory_source_rows = _inventory_source_rows_from_action_row(
            highlight_row,
            self.current_table.rowCount(),
        )
        if recommended is not None:
            self._highlighted_inventory_label = "推荐"
        elif best_upgrade is not None:
            self._highlighted_inventory_label = "机会"
        else:
            self._highlighted_inventory_label = "入选"
        if self._highlighted_inventory_source_rows:
            self._selected_inventory_source_row_value = min(self._highlighted_inventory_source_rows)
        self._refresh_inventory_view()
        loadout_rows = []
        if recommended:
            raw_loadout_rows = recommended.get("_representative_loadout_rows")
            if recommended.get("方案类型") != "条件策略" and isinstance(raw_loadout_rows, list):
                loadout_rows = _loadout_display_rows(
                    raw_loadout_rows,
                    self.selected_game(),
                    self.current_table.rowCount(),
                )
        self._fill_table(self.action_loadout_table, loadout_rows)
        self._render_action_plan(recommended)
        self.log.append(
            f"Action EV 完成：engine={_engine_label(self._last_action_engine)}；"
            f"执行方式={_execution_mode_label(self._last_action_execution_mode)}。"
        )
        self.log.append(action_ev_brief(rows))
        if raw_recommended is not None and recommended is None:
            self.log.append(
                "排序最高 action 没有有效提升，已从桌面主推荐卡隐藏："
                f"{_action_visible_summary(raw_recommended, self.current_table.rowCount())}"
            )
        if raw_recommended is not None and recommended is not None:
            raw_summary = _action_visible_summary(raw_recommended, self.current_table.rowCount())
            recommended_summary_for_audit = _action_visible_summary(
                recommended,
                self.current_table.rowCount(),
            )
            if raw_summary != recommended_summary_for_audit:
                self.log.append(
                    "桌面主推荐按有效口径选择："
                    f"{recommended_summary_for_audit}；引擎审计排序最高：{raw_summary}"
                )
        if recommended:
            recommended_summary = _action_visible_summary(recommended, self.current_table.rowCount())
            self.log.append(f"推荐：{recommended_summary}")
            gain_summary = self._action_gain_summary_text(self._action_result_rows)
            has_positive_upgrade = any(
                row.get("策略") == "强化库存胚子"
                and _action_row_has_positive_gain(row)
                and not str(row.get("套装约束") or "").startswith("未满足")
                for row in self._action_result_rows
            )
            self._last_recommended_action_summary = recommended_summary
            self._last_main_metric_summary = (
                f"{_effective_gain_summary(recommended)}；"
                f"有效/母盘：{recommended.get('有效/母盘', '-')}"
            )
            if "当前可用调律 action 均无有效提升" in gain_summary and has_positive_upgrade:
                self.result_recommend_title.setText("调律暂无有效提升；有库存升级机会")
            elif "当前可用调律 action 均无有效提升" in gain_summary:
                self.result_recommend_title.setText("H=1 暂无有效提升")
            else:
                self.result_recommend_title.setText("推荐调律 action")
            detail = self._recommended_action_card_text(recommended)
            self.result_recommend_detail.setText(f"{gain_summary}\n{detail}" if gain_summary else detail)
            self._set_result_recommend_icon(str(recommended.get("目标套装") or ""))
        elif best_upgrade:
            gain_summary = self._action_gain_summary_text(self._action_result_rows)
            opportunity_summary = _action_visible_summary(best_upgrade, self.current_table.rowCount())
            self.log.append(f"库存升级机会：{opportunity_summary}")
            self._last_recommended_action_summary = "暂无可推荐调律 action；有库存升级机会。"
            self._last_main_metric_summary = (
                f"{opportunity_summary}\n"
                f"{_effective_gain_summary(best_upgrade)}"
            )
            self.result_recommend_title.setText("暂无可推荐调律 action；有库存升级机会")
            detail = self._recommended_action_card_text(best_upgrade)
            self.result_recommend_detail.setText(f"{gain_summary}\n{detail}" if gain_summary else detail)
            self._set_result_recommend_icon(str(best_upgrade.get("目标套装") or ""))
        else:
            gain_summary = self._action_gain_summary_text(self._action_result_rows)
            if raw_recommended is not None:
                suppressed_summary = _action_visible_summary(
                    raw_recommended,
                    self.current_table.rowCount(),
                )
                self._last_recommended_action_summary = "暂无有效提升 action。"
                self.result_recommend_title.setText("暂无有效提升 action")
                self.result_recommend_detail.setText(
                    "\n".join(
                        part
                        for part in [
                            gain_summary,
                            f"排序最高 action 仅有非有效收益，当前桌面主口径不作为推荐：{suppressed_summary}",
                            self._action_execution_summary_text(),
                        ]
                        if part
                    )
                )
                self._set_result_recommend_icon(str(raw_recommended.get("目标套装") or ""))
            else:
                self._last_recommended_action_summary = "没有找到满足当前硬约束的推荐 action。"
                self.result_recommend_title.setText("暂无可推荐 action")
                self.result_recommend_detail.setText(
                    f"{self._last_recommended_action_summary}\n{self._action_execution_summary_text()}"
                )
            self._last_main_metric_summary = "-"
            if raw_recommended is None:
                self._set_result_recommend_icon(None)
        self._has_calculated_once = True
        self._results_stale = False
        self.progress_label.setText("Action EV 结果已计算完成。")
        self.progress_meter_label.setText("总进度 100% | 已完成 | 结果已更新")
        self.progress_detail_label.setText("整体 100/100 | 已完成")
        self.result_tabs.setCurrentIndex(0)
        self._refresh_overview()
        self._update_action_buttons()

    def _on_action_failed(self, traceback_text: str) -> None:
        self._stop_action_progress()
        self._worker = None
        self._worker_thread = None
        self.progress_label.setText("Action EV 计算失败。")
        self.progress_meter_label.setText("计算失败 | 未更新推荐")
        self.progress_detail_label.setText("后台计算已停止，错误详情已写入运行日志。")
        self.log.append(traceback_text)
        self.result_recommend_title.setText("Action EV 计算失败")
        self.result_recommend_detail.setText(f"运行日志已展开，请查看错误详情。\n{self._action_execution_summary_text()}")
        self.log_toggle_button.setChecked(True)
        self.result_tabs.setCurrentIndex(4)
        self.tabs.setCurrentIndex(3)
        QMessageBox.critical(self, "计算失败", traceback_text)
        self._refresh_overview()
        self._update_action_buttons()

    def _fill_table(self, table: QTableWidget, rows: list[dict[str, Any]]) -> None:
        table.clear()
        if not rows:
            table.setRowCount(0)
            table.setColumnCount(0)
            return
        columns = list(rows[0])
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setRowCount(len(rows))
        table.verticalHeader().setVisible(False)
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                item = QTableWidgetItem(_format_value(row.get(column)))
                if column in SUMMARY_NUMERIC_COLUMNS:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_index, column_index, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)

    def _show_warning(self, title: str, warnings: list[str]) -> None:
        QMessageBox.warning(self, title, "\n".join(warnings[:12]))
        self.log.append(f"{title}\n" + "\n".join(warnings))


def _disable_transient_popup_effects() -> None:
    for effect in [
        Qt.UIEffect.UI_AnimateCombo,
        Qt.UIEffect.UI_AnimateMenu,
        Qt.UIEffect.UI_AnimateToolBox,
        Qt.UIEffect.UI_AnimateTooltip,
        Qt.UIEffect.UI_FadeMenu,
        Qt.UIEffect.UI_FadeTooltip,
    ]:
        QApplication.setEffectEnabled(effect, False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the native PySide6 desktop app.")
    parser.add_argument("--width", type=int, default=1500)
    parser.add_argument("--height", type=int, default=950)
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    _disable_transient_popup_effects()
    window = OptimizerWindow(width=args.width, height=args.height)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
