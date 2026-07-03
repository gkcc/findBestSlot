import pytest

from gear_optimizer.game_rules import load_game


def test_set_icon_pixmap_loads_drive_disc_icon(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from gear_optimizer.ui_assets import set_effect_tooltip, set_icon, set_icon_pixmap

    app = QApplication.instance() or QApplication([])
    game = load_game("zzz")

    pixmap = set_icon_pixmap(game, "云岿如我", 32)
    icon = set_icon(game, "云岿如我", 32)
    assert pixmap is not None
    assert not pixmap.isNull()
    assert icon is not None
    assert not icon.isNull()
    assert "2件套" in set_effect_tooltip(game, "云岿如我")
    app.processEvents()


def test_set_icon_pixmap_missing_asset_returns_none(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from gear_optimizer.ui_assets import set_icon, set_icon_pixmap

    app = QApplication.instance() or QApplication([])
    game = load_game("zzz")

    assert set_icon_pixmap(game, "不存在套装", 32) is None
    assert set_icon(game, "不存在套装", 32) is None
    app.processEvents()
