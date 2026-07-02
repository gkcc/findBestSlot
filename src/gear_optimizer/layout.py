from __future__ import annotations

from gear_optimizer.models import GameRules, position_key


def _configured_layout(game: GameRules) -> list[list[str | None]]:
    keys = {position_key(rule.id) for rule in game.positions}
    layout: list[list[str | None]] = []
    for row in game.board_layout:
        layout_row: list[str | None] = []
        for value in row:
            if value is None:
                layout_row.append(None)
                continue
            key = position_key(value)
            if key not in keys:
                raise ValueError(f"Configured board layout references unknown position: {value}")
            layout_row.append(key)
        layout.append(layout_row)
    return layout


def board_layout_for_game(game: GameRules) -> list[list[str | None]]:
    keys = {position_key(rule.id): position_key(rule.id) for rule in game.positions}
    if game.board_layout:
        return _configured_layout(game)

    if game.id == "zzz" and all(str(index) in keys for index in range(1, 7)):
        return [["1", "2", "3"], ["4", "5", "6"]]

    hsr_layout = [
        ["head", "hands", "body"],
        ["feet", "sphere", "rope"],
    ]
    if game.id == "hsr" and all(slot in keys for row in hsr_layout for slot in row):
        return hsr_layout

    position_keys = [position_key(rule.id) for rule in game.positions]
    return [position_keys[index:index + 3] for index in range(0, len(position_keys), 3)]


def board_center_slot(layout: list[list[str | None]]) -> tuple[int, int] | None:
    empty_slots = [
        (row_index, column_index)
        for row_index, row in enumerate(layout)
        for column_index, value in enumerate(row)
        if value is None
    ]
    if not empty_slots:
        return None

    row_center = (len(layout) - 1) / 2
    max_columns = max((len(row) for row in layout), default=0)
    column_center = (max_columns - 1) / 2
    return min(
        empty_slots,
        key=lambda slot: (
            abs(slot[0] - row_center) + abs(slot[1] - column_center),
            abs(slot[0] - row_center),
            slot[0],
            slot[1],
        ),
    )
