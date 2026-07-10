from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
import time


def _wait_for(predicate, app, qtest, timeout_seconds: float, interval_ms: int = 50) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < timeout_seconds:
        app.processEvents()
        if predicate():
            return True
        qtest.qWait(interval_ms)
    app.processEvents()
    return predicate()


def _sample_unique_colors(widget) -> int:
    pixmap = widget.grab()
    image = pixmap.toImage()
    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        return 0
    colors: set[int] = set()
    step_x = max(1, image.width() // 24)
    step_y = max(1, image.height() // 12)
    for y in range(0, image.height(), step_y):
        for x in range(0, image.width(), step_x):
            colors.add(image.pixelColor(x, y).rgba())
    return len(colors)


def _visible_combo_popup(app, combo):
    popup = app.activePopupWidget()
    if popup is not None and popup.isVisible():
        return popup
    view = combo.view()
    if view is not None:
        view_window = view.window()
        if view_window is not None and view_window is not combo.window() and view_window.isVisible():
            return view_window
    return None


def _assert_combo_popup_rendered(app, window, combo, qtest, timeout_seconds: float) -> None:
    from PySide6.QtCore import Qt as _Qt

    qtest.mouseClick(combo, _Qt.MouseButton.LeftButton)
    if not _wait_for(
        lambda: _visible_combo_popup(app, combo) is not None,
        app,
        qtest,
        timeout_seconds,
    ):
        raise AssertionError("game selector popup did not become visible")

    view = combo.view()
    popup = _visible_combo_popup(app, combo)
    if popup is None:
        raise AssertionError("game selector popup disappeared before inspection")
    if not view.isVisible() or not view.viewport().isVisible():
        raise AssertionError(
            "game selector popup container is visible but its item view is hidden"
        )

    popup_geometry = popup.frameGeometry()
    screen = popup.screen() or window.screen()
    if screen is not None and not popup_geometry.intersects(screen.geometry()):
        raise AssertionError(
            f"game selector popup is off screen: popup={popup_geometry}, screen={screen.geometry()}"
        )

    row_count = view.model().rowCount()
    if row_count < 2:
        raise AssertionError(f"game selector popup has too few rows: {row_count}")
    for row in range(row_count):
        rect = view.visualRect(view.model().index(row, 0))
        if not rect.isValid() or rect.height() <= 0 or rect.width() <= 0:
            raise AssertionError(f"game selector popup row {row} has invalid visual rect: {rect}")

    if _sample_unique_colors(popup) <= 1:
        raise AssertionError("game selector popup rendered as a blank single-color surface")


def run_smoke(
    *,
    visible: bool = True,
    timeout_seconds: float = 30.0,
    user_data_dir: Path | None = None,
) -> list[str]:
    if user_data_dir is not None:
        return _run_smoke(
            visible=visible,
            timeout_seconds=timeout_seconds,
            user_data_dir=user_data_dir,
        )
    with tempfile.TemporaryDirectory(prefix="gear-ui-smoke-user-data-") as temporary_dir:
        return _run_smoke(
            visible=visible,
            timeout_seconds=timeout_seconds,
            user_data_dir=Path(temporary_dir),
        )


def _run_smoke(*, visible: bool, timeout_seconds: float, user_data_dir: Path) -> list[str]:
    os.environ["GEAR_OPTIMIZER_USER_DATA_DIR"] = str(user_data_dir)
    if visible:
        os.environ.pop("QT_QPA_PLATFORM", None)
    else:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QPushButton,
    )

    from gear_optimizer.agents import GlobalInventoryStore, save_global_inventory_store
    from gear_optimizer.inventory_service import add_inventory_piece, equip_inventory_item
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_piece, ui_runtime_log_path

    app = QApplication.instance() or QApplication(sys.argv[:1])
    save_global_inventory_store(GlobalInventoryStore(game="zzz"), user_data_dir)
    window = OptimizerWindow(width=1200, height=760)
    messages: list[str] = []
    window.show()
    app.processEvents()
    if visible:
        QTest.qWaitForWindowExposed(window, 3000)

    try:
        if not window.isVisible():
            raise AssertionError("main window did not become visible")
        messages.append("main window visible")

        if type(window.game_combo) is not QComboBox:
            raise AssertionError("game selector is not native QComboBox")
        zzz_index = window.game_combo.findData("zzz")
        if zzz_index < 0:
            raise AssertionError("game selector does not contain zzz")
        _assert_combo_popup_rendered(app, window, window.game_combo, QTest, timeout_seconds)
        popup_rows = window.game_combo.view().model().rowCount()
        window.game_combo.hidePopup()
        if popup_rows < 2:
            raise AssertionError(f"game selector popup has too few rows: {popup_rows}")
        if not any("绝区零" in window.game_combo.itemText(index) for index in range(window.game_combo.count())):
            raise AssertionError("game selector does not show 绝区零")
        messages.append(f"game selector popup rendered with {popup_rows} rows and includes 绝区零")

        window.game_combo.setCurrentIndex(zzz_index)
        QTest.qWait(200)
        app.processEvents()
        if window.game_combo.currentData() != "zzz":
            raise AssertionError("failed to switch game to zzz")
        if "多代理人调律可直接使用空或部分当前盘面" not in window.progress_label.text():
            raise AssertionError("game-switch guidance still implies current gear confirmation is mandatory")
        messages.append("switched to zzz without mandatory current confirmation guidance")

        game = window.selected_game()
        character = window.selected_character()
        current_piece = _default_piece(game, character, game.positions[0].id)
        current_item = add_inventory_piece(game.id, current_piece, user_data_dir)
        equip_inventory_item(
            game.id,
            window.selected_storage_character_id(),
            current_item.item_id,
            user_data_dir,
        )
        window._reload_character_context()
        app.processEvents()
        unequip_buttons = [
            button
            for button in window.current_cards[0].findChildren(QPushButton)
            if button.text() == "卸下"
        ]
        if not unequip_buttons:
            raise AssertionError("current gear card has no unequip button")
        QTest.mouseClick(unequip_buttons[0], Qt.MouseButton.LeftButton)
        QTest.qWait(200)
        app.processEvents()
        if window.current_table.rowCount() != 0 or window.inventory_table.rowCount() != 1:
            raise AssertionError("unequip did not move current piece back to inventory")
        messages.append("unequipped current piece back to inventory")

        def accept_portfolio_dialog() -> None:
            for widget in QApplication.topLevelWidgets():
                if (
                    isinstance(widget, QDialog)
                    and "多代理人调律" in widget.windowTitle()
                    and widget.isVisible()
                ):
                    enabled_checks = [
                        check for check in widget.findChildren(QCheckBox) if check.isEnabled()
                    ]
                    for check in enabled_checks[:2]:
                        check.setChecked(True)
                    buttons = widget.findChild(QDialogButtonBox)
                    if buttons is None:
                        raise AssertionError("multi-agent tuning dialog has no button box")
                    ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
                    if ok_button is None:
                        raise AssertionError("multi-agent tuning dialog has no OK button")
                    ok_button.click()
                    return
            QTimer.singleShot(50, accept_portfolio_dialog)

        QTimer.singleShot(100, accept_portfolio_dialog)
        QTest.mouseClick(window.portfolio_button, Qt.MouseButton.LeftButton)
        if not _wait_for(
            lambda: (not window._action_busy()) and window.portfolio_table.rowCount() > 0,
            app,
            QTest,
            timeout_seconds,
        ):
            raise AssertionError(
                f"BOX audit did not finish within {timeout_seconds:.0f}s; "
                f"busy={window._action_busy()} rows={window.portfolio_table.rowCount()}"
            )
        if "多代理人调律建议已计算完成" not in window.progress_label.text():
            raise AssertionError("multi-agent tuning finished without success status")
        portfolio_headers = {
            window.portfolio_table.horizontalHeaderItem(index).text()
            for index in range(window.portfolio_table.columnCount())
        }
        if not {"盘池成型", "直装成型"}.issubset(portfolio_headers):
            raise AssertionError(
                "multi-agent tuning table does not distinguish pool and direct completion"
            )
        messages.append(f"multi-agent tuning completed with {window.portfolio_table.rowCount()} rows")

        log_path = ui_runtime_log_path()
        log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        for marker in ("current_piece_unequipped", "portfolio_compute_start", "portfolio_compute_finished"):
            if marker not in log_text:
                raise AssertionError(f"runtime log missing {marker}")
        if "direct_completion_probability" not in log_text:
            raise AssertionError("runtime log does not record direct completion probability")
        messages.append(f"runtime log captured operations: {log_path}")
        return messages
    finally:
        window.close()
        app.processEvents()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a real PySide6 desktop UI smoke path.")
    parser.add_argument("--offscreen", action="store_true", help="Run with QT_QPA_PLATFORM=offscreen.")
    parser.add_argument("--timeout", type=float, default=30.0, help="BOX audit timeout in seconds.")
    parser.add_argument("--user-data-dir", default="", help="Optional isolated user data directory.")
    args = parser.parse_args(argv)

    try:
        messages = run_smoke(
            visible=not args.offscreen,
            timeout_seconds=args.timeout,
            user_data_dir=Path(args.user_data_dir).resolve() if args.user_data_dir else None,
        )
    except Exception as exc:
        print(f"UI_SMOKE_ERROR: {type(exc).__name__}: {exc}")
        return 1
    for message in messages:
        print(f"ok - {message}")
    print("UI_SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
