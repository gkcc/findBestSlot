from gear_optimizer.game_rules import load_game
from gear_optimizer.layout import board_center_slot, board_layout_for_game


def test_zzz_uses_drive_disk_matrix_layout():
    game = load_game("zzz")
    assert game.board_layout == [
        [1, 2, 3],
        [4, 5, 6],
    ]
    assert board_layout_for_game(game) == [
        ["1", "2", "3"],
        ["4", "5", "6"],
    ]
    assert board_center_slot(board_layout_for_game(game)) is None


def test_hsr_uses_relic_and_planar_two_row_layout():
    game = load_game("hsr")
    assert game.board_layout == [
        ["head", "hands", "body"],
        ["feet", "sphere", "rope"],
    ]
    assert board_layout_for_game(game) == [
        ["head", "hands", "body"],
        ["feet", "sphere", "rope"],
    ]
    assert board_center_slot(board_layout_for_game(game)) is None


def test_layout_falls_back_to_rows_when_game_has_no_configured_layout():
    game = load_game("zzz").model_copy(update={"id": "custom", "board_layout": []})

    assert board_layout_for_game(game) == [["1", "2", "3"], ["4", "5", "6"]]
    assert board_center_slot(board_layout_for_game(game)) is None
