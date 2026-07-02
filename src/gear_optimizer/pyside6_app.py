from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gear_optimizer.game_rules import (
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
        self.games = load_games()
        self.characters: list[CharacterPreset] = []
        self.probabilities: list[ProbabilityModel] = []
        self.current_confirmed_digest: str | None = None
        self._worker_thread: QThread | None = None
        self._worker: ActionEvWorker | None = None

        self.game_combo = QComboBox()
        self.character_combo = QComboBox()
        self.probability_combo = QComboBox()
        self.current_table = GearTable(editable_positions=False, row_label_prefix="当前")
        self.inventory_table = GearTable(editable_positions=True, row_label_prefix="库存")
        self.confirm_button = QPushButton("确认当前装备")
        self.save_current_button = QPushButton("保存当前装备到本机")
        self.load_example_button = QPushButton("载入示例当前装备")
        self.add_inventory_button = QPushButton("添加库存件")
        self.delete_inventory_button = QPushButton("删除选中库存件")
        self.save_inventory_button = QPushButton("保存库存到本机")
        self.best_button = QPushButton("计算当前最优搭配")
        self.action_button = QPushButton("计算调律建议")
        self.horizon_combo = QComboBox()
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumHeight(24)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: 1px solid #5f6368;
                border-radius: 6px;
                background: #202124;
                color: #f1f3f4;
                text-align: center;
                font-weight: 700;
            }
            QProgressBar::chunk {
                border-radius: 5px;
                background-color: #4c8bf5;
            }
            """
        )
        self.progress_label = QLabel("当前装备未确认。")
        self.tabs = QTabWidget()
        self.best_table = QTableWidget()
        self.action_table = QTableWidget()
        self.action_loadout_table = QTableWidget()
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        self._build_ui()
        self._connect_signals()
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

        inventory_page = QWidget()
        inventory_page_layout = QVBoxLayout(inventory_page)
        inventory_group = QGroupBox("背包库存（未装备盘）")
        inventory_layout = QVBoxLayout(inventory_group)
        inventory_layout.addWidget(self.inventory_table)
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
        current_layout.addWidget(self.current_table)
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
        settings.addStretch(1)
        action_layout.addLayout(settings)
        action_layout.addWidget(self.progress_label)
        action_layout.addWidget(self.progress_bar)
        result_page_layout.addWidget(action_group)

        result_group = QGroupBox("结果")
        result_layout = QVBoxLayout(result_group)
        result_layout.addWidget(QLabel("当前最优搭配"))
        result_layout.addWidget(self.best_table)
        result_layout.addWidget(QLabel("调律建议 Action EV"))
        result_layout.addWidget(self.action_table)
        result_layout.addWidget(QLabel("推荐调律后代表搭配"))
        result_layout.addWidget(self.action_loadout_table)
        result_layout.addWidget(QLabel("运行日志"))
        result_layout.addWidget(self.log)
        result_page_layout.addWidget(result_group)
        self.tabs.addTab(result_page, "计算结果")
        layout.addWidget(self.tabs, 1)

        self.setCentralWidget(root)

    def _connect_signals(self) -> None:
        self.game_combo.currentIndexChanged.connect(lambda _index: self._reload_game_context())
        self.character_combo.currentIndexChanged.connect(lambda _index: self._reload_character_context())
        self.probability_combo.currentIndexChanged.connect(lambda _index: self._clear_results("概率模型已变化。"))
        self.current_table.changed.connect(self._current_changed)
        self.inventory_table.changed.connect(lambda: self._clear_results("库存已变化。"))
        self.confirm_button.clicked.connect(self.confirm_current)
        self.save_current_button.clicked.connect(self.save_current)
        self.load_example_button.clicked.connect(self.load_example_current)
        self.add_inventory_button.clicked.connect(self.add_inventory)
        self.delete_inventory_button.clicked.connect(self.delete_inventory)
        self.save_inventory_button.clicked.connect(self.save_inventory)
        self.best_button.clicked.connect(self.run_best_loadout)
        self.action_button.clicked.connect(self.run_action_ev)

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

    def _current_changed(self) -> None:
        self.current_confirmed_digest = None
        self._clear_results("当前装备已变化，请重新确认。")
        self._update_action_buttons()

    def _clear_results(self, message: str = "") -> None:
        self.best_table.setRowCount(0)
        self.best_table.setColumnCount(0)
        self.action_table.setRowCount(0)
        self.action_table.setColumnCount(0)
        self.action_loadout_table.setRowCount(0)
        self.action_loadout_table.setColumnCount(0)
        self.progress_bar.setValue(0)
        self.progress_label.setText(message or "等待操作。")

    def _update_action_buttons(self, busy: bool = False) -> None:
        enabled = self.current_confirmed_digest is not None and not busy
        self.best_button.setEnabled(enabled)
        self.action_button.setEnabled(enabled)
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
        self.progress_label.setText(
            f"当前装备已确认。最弱位置：{analysis.weakest_position_name or '-'}。"
        )
        self._update_action_buttons()

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
        self.inventory_table.remove_selected()
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
        self.tabs.setCurrentIndex(2)
        self.progress_label.setText("当前最优搭配已计算完成。")

    def run_action_ev(self) -> None:
        current_pieces = self._collect_current_or_warn()
        if current_pieces is None or not self._ensure_current_still_confirmed(current_pieces):
            return
        inventory_pieces = self._collect_inventory_or_warn()
        if inventory_pieces is None:
            return
        self._update_action_buttons(busy=True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("正在计算 Action EV。")
        self._worker_thread = QThread(self)
        self._worker = ActionEvWorker(
            self.selected_game(),
            self.selected_character(),
            self.selected_probability_model(),
            current_pieces,
            inventory_pieces,
            int(self.horizon_combo.currentData()),
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
        self.tabs.setCurrentIndex(2)

    def _on_action_progress(self, payload: dict) -> None:
        total = float(payload.get("total") or 0)
        completed = float(payload.get("completed") or 0)
        if total > 0:
            self.progress_bar.setValue(max(0, min(100, int(completed / total * 100))))
        label = str(payload.get("label") or payload.get("event") or "计算中")
        extra = []
        for key in ["dp_states", "memo_hits"]:
            if key in payload:
                extra.append(f"{key}={payload[key]}")
        self.progress_label.setText(label + (f" ({', '.join(extra)})" if extra else ""))

    def _on_action_finished(self, rows: list[dict]) -> None:
        self._worker = None
        self._worker_thread = None
        self.progress_bar.setValue(100)
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
        self.progress_label.setText("调律建议已计算完成。")
        self._update_action_buttons()

    def _on_action_failed(self, traceback_text: str) -> None:
        self._worker = None
        self._worker_thread = None
        self.progress_label.setText("调律建议计算失败。")
        self.log.append(traceback_text)
        QMessageBox.critical(self, "计算失败", traceback_text)
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
