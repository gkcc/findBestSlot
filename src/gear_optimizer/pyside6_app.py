from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from typing import Any
import uuid

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
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
from gear_optimizer.models import CharacterPreset, GameRules, GearPiece, ProbabilityModel, SubstatLine, position_key
from gear_optimizer.position_ev import (
    action_ev_brief,
    best_loadout_rows,
    position_strategy_efficiency_rows,
    recommended_action_ev_row,
)
from gear_optimizer.presets import list_current_examples, load_current_example
from gear_optimizer.scoring import analyse_current_gear
from gear_optimizer.scoring import score_piece
from gear_optimizer.ui_assets import set_effect_tooltip, set_icon, set_icon_pixmap
from gear_optimizer.user_current_gear import load_user_current_gears, save_user_current_gear
from gear_optimizer.user_inventory import load_user_inventory, save_user_inventory, user_inventory_store_path


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
]
GEAR_COLUMN_WIDTHS = [
    78,
    128,
    116,
    88,
    76,
    56,
    112,
    78,
    112,
    78,
    112,
    78,
    112,
    78,
]
LEVEL_COMBO_MIN_WIDTH = 82
ROLL_SPINBOX_MIN_WIDTH = 72
SUMMARY_NUMERIC_COLUMNS = {"有效", "质量", "当前有效", "期望有效", "当前质量", "期望质量", "质量/母盘", "有效/母盘"}
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
QFrame#PieceCard, QFrame#OverviewCard, QFrame#RecommendCard {
    background: #ffffff;
    border: 1px solid #d7dce2;
    border-radius: 8px;
}
QFrame#PieceCard:hover {
    border-color: #1a73e8;
}
QProgressBar {
    border: 1px solid #9db7f5;
    border-radius: 6px;
    background: #e8f0fe;
    color: #174ea6;
    text-align: center;
    font-weight: 700;
}
QProgressBar::chunk {
    border-radius: 5px;
    margin: 2px;
    background-color: #1a73e8;
}
"""


def _model_payload(item: Any) -> Any:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    return item


def _pieces_digest(pieces: list[GearPiece]) -> str:
    encoded = json.dumps(
        [_model_payload(piece) for piece in pieces],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _default_piece(game: GameRules, character: CharacterPreset, position: str | int) -> GearPiece:
    rule = game.position(position)
    preferred = character.preferred_mains_for(rule.id)
    main_stat = preferred[0] if preferred and preferred[0] in rule.main_stats else rule.main_stats[0]
    set_plan = character.active_set_plan()
    set_name = character.target_set
    if set_plan and set_plan.requirements:
        set_name = set_plan.requirements[0].primary_set
    elif game.sets:
        set_name = character.target_set if character.target_set in game.sets else game.sets[0]
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


def _initial_current_pieces(game: GameRules, character: CharacterPreset) -> list[GearPiece]:
    try:
        saved = load_user_current_gears(game.id, character.id)
        if saved:
            return _complete_position_pieces(game, character, list(saved[-1]["pieces"]))
    except Exception:
        pass
    try:
        examples = list_current_examples(game.id, character.id)
        if examples:
            return _complete_position_pieces(game, character, load_current_example(examples[0]["path"]))
    except Exception:
        pass
    return [_default_piece(game, character, rule.id) for rule in game.positions]


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


def _badge(text: str, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName("MutedBadge" if muted else "Badge")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


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


def _loadout_main_stat_label(row: dict[str, Any]) -> str:
    piece = row.get("_piece")
    if isinstance(piece, GearPiece):
        return piece.main_stat
    return str(row.get("main_stat") or "-")


def _loadout_substat_label(row: dict[str, Any]) -> str:
    piece = row.get("_piece")
    if isinstance(piece, GearPiece):
        return _piece_substat_label(piece)
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
                "估值口径": "满级强化期望" if row.get("_expected_upgrade") else "当前值/代表结果",
                "当前有效": row.get("_current_effective_rolls", row.get("effective_rolls", "-")),
                "期望有效": row.get("effective_rolls", "-"),
                "当前质量": row.get("_current_quality_score", row.get("quality_score", "-")),
                "期望质量": row.get("quality_score", "-"),
                "副词条": _loadout_substat_label(row),
                "排序向量": row.get("quality_vector", "-"),
            }
        )
    return display_rows


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
                piece = GearPiece(
                    position=position,
                    set_name=str(self._combo_value(row, COL_SET)),
                    main_stat=main_stat,
                    level=int(self._combo_value(row, COL_LEVEL)),
                    initial_substat_count=int(self._combo_value(row, COL_INITIAL)),
                    locked=self._checkbox_value(row, COL_LOCKED),
                    substats=substats,
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

        self.setCellWidget(row, COL_SET, self._combo([(name, name) for name in game.sets], piece.set_name))
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
            spin = QSpinBox()
            spin.setRange(0, 5)
            spin.setMinimumWidth(ROLL_SPINBOX_MIN_WIDTH)
            spin.setValue(int(line.rolls))
            spin.valueChanged.connect(lambda _value: self._emit_changed())
            self.setCellWidget(row, roll_col, spin)

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

    def __init__(
        self,
        row_index: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.row_index = row_index
        self.setObjectName("PieceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(150)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.icon_label = QLabel("")
        self.icon_label.setFixedSize(34, 34)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.position_label = QLabel("-")
        self.position_label.setStyleSheet("font-weight: 800; font-size: 16px;")
        self.locked_badge = _badge("未锁", muted=True)
        header.addWidget(self.icon_label)
        header.addWidget(self.position_label)
        header.addStretch(1)
        header.addWidget(self.locked_badge)
        layout.addLayout(header)

        self.set_label = QLabel("-")
        self.main_label = QLabel("-")
        self.substat_label = QLabel("-")
        self.substat_label.setWordWrap(True)
        self.metrics_label = QLabel("有效 - / 质量 -")
        self.metrics_label.setObjectName("MutedBadge")
        layout.addWidget(self.set_label)
        layout.addWidget(self.main_label)
        layout.addWidget(self.substat_label, 1)
        layout.addWidget(self.metrics_label)

    def update_piece(
        self,
        piece: GearPiece,
        game: GameRules,
        character: CharacterPreset,
    ) -> None:
        effective, quality = _piece_metric_labels(piece, game, character)
        pixmap = set_icon_pixmap(game, piece.set_name, 32)
        if pixmap is not None:
            self.icon_label.setPixmap(pixmap)
            self.icon_label.setText("")
        else:
            self.icon_label.clear()
            self.icon_label.setText("盘")
        self.icon_label.setToolTip(set_effect_tooltip(game, piece.set_name))
        self.position_label.setText(game.position_name(piece.position))
        self.locked_badge.setText("锁定" if piece.locked else "未锁")
        self.locked_badge.setObjectName("Badge" if piece.locked else "MutedBadge")
        self.locked_badge.style().unpolish(self.locked_badge)
        self.locked_badge.style().polish(self.locked_badge)
        self.set_label.setText(f"套装：{piece.set_name}")
        self.main_label.setText(f"主属性：{piece.main_stat}  +{piece.level}")
        self.substat_label.setText(f"副词条：{_piece_substat_label(piece)}")
        self.metrics_label.setText(f"有效 {effective} / 质量 {quality}")

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.row_index)
        super().mousePressEvent(event)


class GearPieceEditDialog(QDialog):
    def __init__(
        self,
        game: GameRules,
        character: CharacterPreset,
        piece: GearPiece,
        editable_position: bool,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._piece: GearPiece | None = None
        self.table = GearTable(
            editable_positions=editable_position,
            row_label_prefix="装备",
        )
        self.table.set_context(game, character, [piece])
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(125)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(buttons)
        self.resize(1120, 220)

    @property
    def piece(self) -> GearPiece | None:
        return self._piece

    def accept(self) -> None:  # type: ignore[override]
        pieces, warnings = self.table.collect_pieces()
        if warnings:
            QMessageBox.warning(self, "装备无法保存", "\n".join(warnings[:8]))
            return
        self._piece = pieces[0] if pieces else None
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
    ) -> None:
        super().__init__()
        self.game = game
        self.character = character
        self.probability_model = probability_model
        self.current_pieces = current_pieces
        self.inventory_pieces = inventory_pieces
        self.horizon = horizon

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
            )
            self.finished.emit(rows)
        except Exception:
            self.failed.emit(traceback.format_exc())


class OptimizerWindow(QMainWindow):
    def __init__(self, width: int = 1500, height: int = 950) -> None:
        super().__init__()
        self.setWindowTitle("gacha-gear-optimizer")
        self.resize(width, height)
        self.setStyleSheet(APP_QSS)
        self.games = load_games()
        self.characters: list[CharacterPreset] = []
        self.probabilities: list[ProbabilityModel] = []
        self.current_confirmed_digest: str | None = None
        self._results_stale = True
        self._has_calculated_once = False
        self._last_weakest_label = "-"
        self._last_recommended_action_summary = "尚未计算"
        self._last_main_metric_summary = "-"
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
        self._action_progress_percent = 0
        self._last_action_progress_payload: dict[str, Any] = {}
        self._last_action_progress_seen_at: float | None = None
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(400)
        self._progress_timer.timeout.connect(self._refresh_action_progress_clock)

        self.game_combo = QComboBox()
        self.character_combo = QComboBox()
        self.probability_combo = QComboBox()
        self.current_table = GearTable(editable_positions=False, row_label_prefix="当前")
        self.inventory_table = GearTable(editable_positions=True, row_label_prefix="库存")
        self.current_cards: list[PieceCard] = []
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
        self.overview_guide_label = QLabel("先维护库存与当前装备，确认当前装备后再计算最优搭配或调律建议。")
        self.overview_guide_label.setWordWrap(True)
        self.confirm_button = QPushButton("确认当前装备")
        self.save_current_button = QPushButton("保存当前装备到本机")
        self.load_example_button = QPushButton("载入示例当前装备")
        self.add_inventory_button = QPushButton("添加库存件")
        self.delete_inventory_button = QPushButton("删除选中库存件")
        self.save_inventory_button = QPushButton("保存库存到本机")
        self.position_filter = QComboBox()
        self.set_filter = QComboBox()
        self.main_filter = QComboBox()
        self.inventory_summary_table = QTableWidget()
        self.inventory_detail_label = QLabel("选择一件库存查看副词条详情。")
        self.inventory_detail_label.setWordWrap(True)
        self.best_button = QPushButton("计算当前最优搭配")
        self.action_button = QPushButton("计算调律建议")
        self.cancel_action_button = QPushButton("取消计算")
        self.cancel_action_button.setEnabled(False)
        self.horizon_combo = QComboBox()
        self.horizon_note_label = QLabel("horizon=1 为完整概率分布精确计算。")
        self.horizon_note_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumHeight(30)
        self.progress_bar.setFormat("0%")
        self.progress_label = QLabel("当前装备未确认。")
        self.progress_detail_label = QLabel("")
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
        self.result_recommend_detail = QLabel("计算调律建议后会在这里显示推荐 action 和主要收益。")
        self.result_recommend_detail.setWordWrap(True)
        self.best_table = QTableWidget()
        self.action_table = QTableWidget()
        self.action_loadout_table = QTableWidget()
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
        form.addRow("角色模板", self.character_combo)
        form.addRow("概率模型", self.probability_combo)
        layout.addWidget(selectors)

        overview_page = QWidget()
        overview_layout = QVBoxLayout(overview_page)
        status_group = QGroupBox("总览")
        status_layout = QGridLayout(status_group)
        status_layout.addWidget(QLabel("游戏"), 0, 0)
        status_layout.addWidget(self.overview_game_label, 0, 1)
        status_layout.addWidget(QLabel("角色"), 0, 2)
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
        filter_layout.addStretch(1)
        inventory_layout.addLayout(filter_layout)
        self.inventory_summary_table.setAlternatingRowColors(True)
        self.inventory_summary_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.inventory_summary_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.inventory_summary_table.verticalHeader().setVisible(False)
        inventory_layout.addWidget(self.inventory_summary_table)
        detail_group = QGroupBox("副词条详情")
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.addWidget(self.inventory_detail_label)
        inventory_layout.addWidget(detail_group)
        inventory_buttons = QHBoxLayout()
        inventory_buttons.addWidget(self.add_inventory_button)
        inventory_buttons.addWidget(self.delete_inventory_button)
        inventory_buttons.addWidget(self.save_inventory_button)
        inventory_buttons.addStretch(1)
        inventory_layout.addLayout(inventory_buttons)
        inventory_page_layout.addWidget(inventory_group)
        self.tabs.addTab(inventory_page, "库存")

        current_page = QWidget()
        current_page_layout = QVBoxLayout(current_page)
        current_group = QGroupBox("当前装备（身上 6 件）")
        current_layout = QVBoxLayout(current_group)
        self.current_card_grid = QGridLayout()
        self.current_card_grid.setHorizontalSpacing(12)
        self.current_card_grid.setVerticalSpacing(12)
        current_layout.addLayout(self.current_card_grid)
        current_buttons = QHBoxLayout()
        current_buttons.addWidget(self.confirm_button)
        current_buttons.addWidget(self.save_current_button)
        current_buttons.addWidget(self.load_example_button)
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
        settings.addWidget(self.cancel_action_button)
        settings.addStretch(1)
        action_layout.addLayout(settings)
        action_layout.addWidget(self.horizon_note_label)
        action_layout.addWidget(self.progress_label)
        action_layout.addWidget(self.progress_detail_label)
        action_layout.addWidget(self.progress_bar)
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
        action_detail_layout.addWidget(self.action_table)
        self.result_tabs.addTab(action_detail_page, "Action EV 明细")

        loadout_page = QWidget()
        loadout_layout = QVBoxLayout(loadout_page)
        loadout_layout.addWidget(QLabel("当前最优搭配"))
        loadout_layout.addWidget(self.best_table)
        loadout_layout.addWidget(QLabel("推荐调律后代表搭配"))
        loadout_layout.addWidget(self.action_loadout_table)
        self.result_tabs.addTab(loadout_page, "代表搭配")

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
        self.game_combo.currentIndexChanged.connect(lambda _index: self._reload_game_context())
        self.character_combo.currentIndexChanged.connect(lambda _index: self._reload_character_context())
        self.probability_combo.currentIndexChanged.connect(lambda _index: self._probability_changed())
        self.current_table.changed.connect(self._current_changed)
        self.inventory_table.changed.connect(self._inventory_changed)
        self.position_filter.currentIndexChanged.connect(lambda _index: self._refresh_inventory_view())
        self.set_filter.currentIndexChanged.connect(lambda _index: self._refresh_inventory_view())
        self.main_filter.currentIndexChanged.connect(lambda _index: self._refresh_inventory_view())
        self.inventory_summary_table.itemSelectionChanged.connect(self._refresh_inventory_detail)
        self.log_toggle_button.toggled.connect(self._set_log_visible)
        self.confirm_button.clicked.connect(self.confirm_current)
        self.save_current_button.clicked.connect(self.save_current)
        self.load_example_button.clicked.connect(self.load_example_current)
        self.add_inventory_button.clicked.connect(self.add_inventory)
        self.delete_inventory_button.clicked.connect(self.delete_inventory)
        self.save_inventory_button.clicked.connect(self.save_inventory)
        self.best_button.clicked.connect(self.run_best_loadout)
        self.action_button.clicked.connect(self.run_action_ev)
        self.cancel_action_button.clicked.connect(self.cancel_action_ev)
        self.horizon_combo.currentIndexChanged.connect(lambda _index: self._update_horizon_note())

    def _load_games(self) -> None:
        self.game_combo.blockSignals(True)
        self.game_combo.clear()
        for game in self.games:
            self.game_combo.addItem(f"{game.name} ({game.id})", game.id)
        self.game_combo.blockSignals(False)
        self._reload_game_context()

    def _reload_game_context(self) -> None:
        game = self.selected_game()
        self.characters = load_characters(game.id)
        self.probabilities = load_probability_models(game.id)
        self.character_combo.blockSignals(True)
        self.character_combo.clear()
        for character in self.characters:
            self.character_combo.addItem(f"{character.name} ({character.id})", character.id)
        self.character_combo.blockSignals(False)
        self.probability_combo.blockSignals(True)
        self.probability_combo.clear()
        for model in self.probabilities:
            self.probability_combo.addItem(f"{model.name} ({model.id})", model.id)
        self.probability_combo.blockSignals(False)
        self._reload_character_context()

    def _reload_character_context(self) -> None:
        game = self.selected_game()
        character = self.selected_character()
        current_pieces = _initial_current_pieces(game, character)
        inventory_pieces = load_user_inventory(game.id, character.id)
        self.current_table.set_context(game, character, current_pieces)
        self.inventory_table.set_context(game, character, inventory_pieces)
        self.current_confirmed_digest = None
        self._last_weakest_label = "-"
        self._last_recommended_action_summary = "尚未计算"
        self._last_main_metric_summary = "-"
        self._has_calculated_once = False
        self._refresh_current_cards()
        self._refresh_inventory_filters()
        self._refresh_inventory_view()
        self._clear_results("已切换角色或游戏，请先确认当前装备。")
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

    def selected_probability_model(self) -> ProbabilityModel:
        model_id = self.probability_combo.currentData()
        for model in self.probabilities:
            if model.id == model_id:
                return model
        return self.probabilities[0]

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
        self.overview_game_label.setText(self.game_combo.currentText() or "-")
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
        guide = "没有结果。按顺序维护库存、确认当前装备，然后点击“计算当前最优搭配”或“计算调律建议”。"
        if self._results_stale and self._has_calculated_once:
            guide = "装备、库存或概率模型已变化，旧结果不可作为当前结论，请重新计算。"
        elif self._has_visible_results() and not self._results_stale:
            guide = "结果已更新，可在“计算结果”页查看 Action EV 明细、代表搭配和运行日志。"
        self.overview_guide_label.setText(guide)

    def _hidden_table_pieces(self, table: GearTable) -> list[GearPiece]:
        pieces, _warnings = table.collect_pieces()
        return pieces

    def _refresh_current_cards(self) -> None:
        if not hasattr(self, "current_card_grid") or not self.characters:
            return
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
                    continue
                card = PieceCard(source_row)
                card.update_piece(pieces[source_row], game, character)
                card.clicked.connect(self.edit_current_piece)
                self.current_cards.append(card)
                self.current_card_grid.addWidget(card, row_index, column_index)
        self._refresh_overview()

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
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.piece is None:
            return
        pieces[row] = dialog.piece
        self.current_table.set_context(self.selected_game(), self.selected_character(), pieces)
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
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.piece is None:
            return
        pieces[source_row] = dialog.piece
        self.inventory_table.set_context(self.selected_game(), self.selected_character(), pieces)
        self._inventory_changed()

    def _inventory_source_row_for_visible_row(self, visible_row: int) -> int | None:
        item = self.inventory_summary_table.item(visible_row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def _selected_inventory_source_row(self) -> int | None:
        selected = self.inventory_summary_table.selectionModel().selectedRows()
        if not selected:
            return None
        return self._inventory_source_row_for_visible_row(selected[0].row())

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

    def _inventory_piece_visible(self, piece: GearPiece) -> bool:
        position_filter = str(self.position_filter.currentData() or "")
        set_filter = str(self.set_filter.currentData() or "")
        main_filter = str(self.main_filter.currentData() or "")
        if position_filter and position_key(piece.position) != position_filter:
            return False
        if set_filter and piece.set_name != set_filter:
            return False
        if main_filter and piece.main_stat != main_filter:
            return False
        return True

    def _refresh_inventory_view(self) -> None:
        if not self.characters:
            return
        game = self.selected_game()
        character = self.selected_character()
        pieces = self._hidden_table_pieces(self.inventory_table)
        rows = [
            (source_row, piece)
            for source_row, piece in enumerate(pieces)
            if self._inventory_piece_visible(piece)
        ]
        columns = ["位置", "套装", "主属性", "等级", "有效", "质量", "锁定", "操作"]
        self.inventory_summary_table.clear()
        self.inventory_summary_table.setColumnCount(len(columns))
        self.inventory_summary_table.setHorizontalHeaderLabels(columns)
        self.inventory_summary_table.setRowCount(len(rows))
        for row_index, (source_row, piece) in enumerate(rows):
            effective, quality = _piece_metric_labels(piece, game, character)
            values = [
                game.position_name(piece.position),
                piece.set_name,
                piece.main_stat,
                f"+{piece.level}",
                effective,
                quality,
                "锁定" if piece.locked else "-",
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, source_row)
                if columns[column_index] == "套装":
                    icon = set_icon(game, piece.set_name, 24)
                    if icon is not None:
                        item.setIcon(icon)
                    item.setToolTip(set_effect_tooltip(game, piece.set_name))
                if columns[column_index] in SUMMARY_NUMERIC_COLUMNS:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.inventory_summary_table.setItem(row_index, column_index, item)
            button = QPushButton("编辑")
            button.clicked.connect(lambda _checked=False, r=source_row: self.edit_inventory_piece(r))
            self.inventory_summary_table.setCellWidget(row_index, len(columns) - 1, button)
        self.inventory_summary_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.inventory_summary_table.horizontalHeader().setStretchLastSection(True)
        self._refresh_inventory_detail()
        self._refresh_overview()

    def _refresh_inventory_detail(self) -> None:
        source_row = self._selected_inventory_source_row()
        pieces = self._hidden_table_pieces(self.inventory_table)
        if source_row is None or source_row < 0 or source_row >= len(pieces):
            self.inventory_detail_label.setText("选择一件库存查看副词条详情。")
            return
        piece = pieces[source_row]
        effective, quality = _piece_metric_labels(piece, self.selected_game(), self.selected_character())
        self.inventory_detail_label.setText(
            f"库存 #{source_row + 1} | {self.selected_game().position_name(piece.position)} | "
            f"{piece.set_name} | {piece.main_stat} +{piece.level} | "
            f"有效 {effective} / 质量 {quality} | 副词条：{_piece_substat_label(piece)}"
        )

    def _inventory_changed(self) -> None:
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

    def _current_changed(self) -> None:
        self.current_confirmed_digest = None
        self._clear_results("当前装备已变化，请重新确认。")
        self._update_action_buttons()
        self._refresh_current_cards()

    def _action_busy(self) -> bool:
        return self._worker is not None or self._action_process is not None

    def _clear_results(self, message: str = "") -> None:
        self._results_stale = True
        self.best_table.setRowCount(0)
        self.best_table.setColumnCount(0)
        self.action_table.setRowCount(0)
        self.action_table.setColumnCount(0)
        self.action_loadout_table.setRowCount(0)
        self.action_loadout_table.setColumnCount(0)
        if not self._action_busy():
            self._progress_timer.stop()
            self._action_progress_started_at = None
            self._action_progress_percent = 0
            self._last_action_progress_payload = {}
            self._last_action_progress_seen_at = None
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0%")
            self.progress_label.setText(message or "等待操作。")
            self.progress_detail_label.setText("")
            if self._has_calculated_once:
                self._last_recommended_action_summary = "结果已过期，请重新计算。"
                self._last_main_metric_summary = "-"
                self.result_recommend_title.setText("结果已过期")
                self.result_recommend_detail.setText(message or "输入已变化，请重新计算。")
                self._set_result_recommend_icon(None)
            else:
                self.result_recommend_title.setText("暂无推荐")
                self.result_recommend_detail.setText("计算调律建议后会在这里显示推荐 action 和主要收益。")
                self._set_result_recommend_icon(None)
            self._refresh_overview()

    def _start_action_progress(self) -> None:
        now = time.monotonic()
        self._action_progress_started_at = now
        self._last_action_progress_seen_at = now
        self._last_action_progress_payload = {}
        self._action_progress_percent = 0
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.progress_label.setText("正在计算 Action EV。")
        self.progress_detail_label.setText("后台线程已启动，等待第一个进度事件。")
        self._progress_timer.start()

    def _stop_action_progress(self) -> None:
        self._progress_timer.stop()
        self._last_action_progress_payload = {}
        self._last_action_progress_seen_at = None

    def _raw_action_progress_percent(self, payload: dict[str, Any]) -> int:
        event = str(payload.get("event") or "")
        if event == "complete":
            return 100
        total = float(payload.get("total") or 0)
        completed = float(payload.get("completed") or 0)
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
        return f"内部：{label}" + (f"（{'，'.join(suffixes)}）" if suffixes else "")

    def _render_action_progress(self, payload: dict[str, Any]) -> None:
        now = time.monotonic()
        raw_percent = self._raw_action_progress_percent(payload)
        stable_percent = max(self._action_progress_percent, raw_percent)
        self._action_progress_percent = stable_percent
        self.progress_bar.setValue(stable_percent)
        self.progress_bar.setFormat(f"{stable_percent}%")

        label = str(payload.get("label") or payload.get("event") or "计算中")
        label_parts = [label]
        spec_index = payload.get("spec_index")
        spec_total = payload.get("spec_total")
        if spec_index not in (None, "") and spec_total not in (None, ""):
            label_parts.append(f"action {spec_index}/{spec_total}")
        unit_label = payload.get("unit_label")
        if unit_label:
            label_parts.append(str(unit_label))
        self.progress_label.setText(" / ".join(label_parts))

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
        if "dp_steps" in payload:
            detail_parts.append(f"DP子步骤 {payload['dp_steps']}")
        if "dp_states" in payload:
            detail_parts.append(f"DP状态 {payload['dp_states']}")
        if "memo_hits" in payload:
            detail_parts.append(f"缓存命中 {payload['memo_hits']}")
        if "aggregated_outcome_cache_hits" in payload:
            detail_parts.append(f"outcome缓存命中 {payload['aggregated_outcome_cache_hits']}")
        if "aggregated_outcome_cache_misses" in payload:
            detail_parts.append(f"outcome缓存展开 {payload['aggregated_outcome_cache_misses']}")

        if self._action_progress_started_at is not None:
            elapsed = now - self._action_progress_started_at
            detail_parts.append(f"已耗时 {_format_duration(elapsed)}")
            if 0 < stable_percent < 99:
                remaining = elapsed * (100 - stable_percent) / stable_percent
                detail_parts.append(f"预计剩余约 {_format_duration(remaining)}")
            elif stable_percent >= 99 and str(payload.get("event") or "") != "complete":
                detail_parts.append("收尾中")
        if self._last_action_progress_seen_at is not None:
            stale_seconds = now - self._last_action_progress_seen_at
            if stale_seconds >= 30:
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
        self.cancel_action_button.setEnabled(self._action_process is not None)
        self.confirm_button.setEnabled(not busy)
        self.add_inventory_button.setEnabled(not busy)
        self.delete_inventory_button.setEnabled(not busy)
        self.save_inventory_button.setEnabled(not busy)

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

    def _collect_inventory_or_warn(self) -> list[GearPiece] | None:
        pieces, warnings = self.inventory_table.collect_pieces()
        if warnings:
            self._show_warning("库存里有不能计算的装备", warnings)
            return None
        return pieces

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

    def save_current(self) -> None:
        pieces = self._collect_current_or_warn()
        if pieces is None:
            return
        label, ok = QInputDialog.getText(self, "保存当前装备", "模板名称")
        if not ok:
            return
        saved = save_user_current_gear(
            self.selected_game().id,
            self.selected_character().id,
            pieces,
            label or "当前装备",
        )
        self.progress_label.setText(f"已保存当前装备：{saved['label']}")

    def load_example_current(self) -> None:
        game = self.selected_game()
        character = self.selected_character()
        examples = list_current_examples(game.id, character.id)
        if not examples:
            QMessageBox.information(self, "没有示例", "当前游戏/角色没有当前装备示例。")
            return
        pieces = _complete_position_pieces(game, character, load_current_example(examples[0]["path"]))
        self.current_table.set_context(game, character, pieces)
        self._current_changed()

    def add_inventory(self) -> None:
        game = self.selected_game()
        character = self.selected_character()
        piece = _default_piece(game, character, game.positions[0].id).model_copy(update={"locked": False})
        self.inventory_table.add_piece(piece)
        self.progress_label.setText("已添加一件库存；不会自动计算。")

    def delete_inventory(self) -> None:
        source_row = self._selected_inventory_source_row()
        if source_row is None:
            return
        pieces = self._hidden_table_pieces(self.inventory_table)
        if 0 <= source_row < len(pieces):
            pieces.pop(source_row)
            self.inventory_table.set_context(self.selected_game(), self.selected_character(), pieces)
            self._inventory_changed()
        self.progress_label.setText("已删除选中库存；不会自动计算。")

    def save_inventory(self) -> None:
        pieces = self._collect_inventory_or_warn()
        if pieces is None:
            return
        path = save_user_inventory(self.selected_game().id, self.selected_character().id, pieces)
        self.progress_label.setText(f"已保存 {len(pieces)} 件库存：{path}")

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

    def _start_action_ev_process(
        self,
        current_pieces: list[GearPiece],
        inventory_pieces: list[GearPiece],
        horizon: int,
    ) -> None:
        run_id = uuid.uuid4().hex
        run_dir = Path(tempfile.mkdtemp(prefix=f"gear-action-ev-{run_id[:8]}-"))
        input_path = run_dir / "input.json"
        output_path = run_dir / "result.json"
        progress_path = run_dir / "progress.jsonl"
        error_path = run_dir / "error.json"
        summary_path = run_dir / "summary.json"
        payload = {
            "run_id": run_id,
            "game_id": self.selected_game().id,
            "character_id": self.selected_character().id,
            "probability_model_id": self.selected_probability_model().id,
            "current_pieces": [_model_payload(piece) for piece in current_pieces],
            "inventory_pieces": [_model_payload(piece) for piece in inventory_pieces],
            "horizon": horizon,
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
        self._start_action_progress()
        self.progress_detail_label.setText(
            "horizon=2 正在子进程中精确计算；主窗口可继续切换 Tab，也可取消。"
        )
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
            self.progress_detail_label.setText("用户取消，未生成新推荐。")
            self.result_recommend_title.setText("计算已取消")
            self.result_recommend_detail.setText("用户取消，未生成新推荐；旧结果未被覆盖。")
            self.log.append("Action EV worker 已停止：用户取消，未生成新推荐。")
            self.log_toggle_button.setChecked(True)
            self.result_tabs.setCurrentIndex(2)
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
        self._has_calculated_once = True
        self._results_stale = False
        self._last_recommended_action_summary = "当前最优搭配已更新。"
        self._last_main_metric_summary = f"代表搭配 {len(rows)} 件；库存合计 {len(current_pieces) + len(inventory_pieces)} 件。"
        self.result_recommend_title.setText("当前最优搭配已更新")
        self.result_recommend_detail.setText(self._last_main_metric_summary)
        first_set = str(rows[0].get("set_name") or "") if rows else ""
        self._set_result_recommend_icon(first_set or None)
        self.tabs.setCurrentIndex(3)
        self.result_tabs.setCurrentIndex(1)
        self.progress_label.setText("当前最优搭配已计算完成。")
        self._refresh_overview()

    def run_action_ev(self) -> None:
        current_pieces = self._collect_current_or_warn()
        if current_pieces is None or not self._ensure_current_still_confirmed(current_pieces):
            return
        inventory_pieces = self._collect_inventory_or_warn()
        if inventory_pieces is None:
            return
        horizon = int(self.horizon_combo.currentData() or 1)
        if horizon == 2:
            self._start_action_ev_process(current_pieces, inventory_pieces, horizon)
            self.tabs.setCurrentIndex(3)
            return
        self._update_action_buttons(busy=True)
        self._start_action_progress()
        self._worker_thread = QThread(self)
        self._worker = ActionEvWorker(
            self.selected_game(),
            self.selected_character(),
            self.selected_probability_model(),
            current_pieces,
            inventory_pieces,
            horizon,
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

    def _on_action_finished(self, rows: list[dict]) -> None:
        self._stop_action_progress()
        self._worker = None
        self._worker_thread = None
        self._action_progress_percent = 100
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("100%")
        visible_columns = [
            "策略",
            "目标套装",
            "位置",
            "主属性",
            "固定副属性",
            "horizon",
            "期望提升",
            "代表路径",
            "预期搭配",
            "互补位",
            "套装约束",
            "质量/母盘",
            "有效/母盘",
            "排序向量/母盘",
            "相对随机",
        ]
        display_rows = [
            {column: row.get(column, "") for column in visible_columns}
            for row in rows
        ]
        self._fill_table(self.action_table, display_rows)
        recommended = recommended_action_ev_row(rows)
        loadout_rows = []
        if recommended:
            raw_loadout_rows = recommended.get("_representative_loadout_rows")
            if isinstance(raw_loadout_rows, list):
                loadout_rows = _loadout_display_rows(
                    raw_loadout_rows,
                    self.selected_game(),
                    self.current_table.rowCount(),
                )
        self._fill_table(self.action_loadout_table, loadout_rows)
        self.log.append(action_ev_brief(rows))
        if recommended:
            self.log.append(
                f"推荐：{recommended['策略']} / {recommended['目标套装']} / {recommended['位置']} / "
                f"{recommended.get('主属性', '-')}"
            )
            self._last_recommended_action_summary = (
                f"{recommended['策略']} / {recommended['目标套装']} / {recommended['位置']} / "
                f"{recommended.get('主属性', '-')}"
            )
            self._last_main_metric_summary = (
                f"期望提升：{recommended.get('期望提升', '-')}；"
                f"有效/母盘：{recommended.get('有效/母盘', '-')}；"
                f"质量/母盘：{recommended.get('质量/母盘', '-')}"
            )
            self.result_recommend_title.setText("推荐调律 action")
            self.result_recommend_detail.setText(
                f"{self._last_recommended_action_summary}\n{self._last_main_metric_summary}"
            )
            self._set_result_recommend_icon(str(recommended.get("目标套装") or ""))
        else:
            self._last_recommended_action_summary = "没有找到满足当前硬约束的推荐 action。"
            self._last_main_metric_summary = "-"
            self.result_recommend_title.setText("暂无可推荐 action")
            self.result_recommend_detail.setText(self._last_recommended_action_summary)
            self._set_result_recommend_icon(None)
        self._has_calculated_once = True
        self._results_stale = False
        self.progress_label.setText("调律建议已计算完成。")
        self.progress_detail_label.setText("整体 100/100 | 已完成")
        self.result_tabs.setCurrentIndex(0)
        self._refresh_overview()
        self._update_action_buttons()

    def _on_action_failed(self, traceback_text: str) -> None:
        self._stop_action_progress()
        self._worker = None
        self._worker_thread = None
        self.progress_label.setText("调律建议计算失败。")
        self.progress_detail_label.setText("后台计算已停止，错误详情已写入运行日志。")
        self.log.append(traceback_text)
        self.result_recommend_title.setText("调律建议计算失败")
        self.result_recommend_detail.setText("运行日志已展开，请查看错误详情。")
        self.log_toggle_button.setChecked(True)
        self.result_tabs.setCurrentIndex(2)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the native PySide6 desktop app.")
    parser.add_argument("--width", type=int, default=1500)
    parser.add_argument("--height", type=int, default=950)
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = OptimizerWindow(width=args.width, height=args.height)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
