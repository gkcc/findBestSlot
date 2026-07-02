from gear_optimizer.diagnostics import (
    format_resource_check,
    has_resource_errors,
    _dependency_row,
    resource_check_rows,
)


def test_resource_check_rows_cover_required_local_assets():
    rows = resource_check_rows()
    by_item = {row["item"]: row for row in rows}

    assert by_item["project root"]["status"] == "ok"
    assert by_item["python version"]["status"] == "ok"
    assert by_item["dependency pydantic"]["status"] == "ok"
    assert by_item["dependency PyYAML"]["status"] == "ok"
    assert by_item["desktop app entry"]["status"] == "ok"
    assert by_item["native PySide6 UI"]["status"] == "ok"
    assert by_item["game configs"]["status"] == "ok"
    assert by_item["examples"]["status"] == "ok"
    assert by_item["zzz drive disc icons"]["status"] == "ok"
    assert by_item["console scripts"]["status"] == "ok"
    assert "6 configured" in by_item["console scripts"]["detail"]
    assert by_item["release helper modules"]["status"] == "ok"
    assert "3 importable" in by_item["release helper modules"]["detail"]
    assert by_item["start desktop script"]["status"] == "ok"
    assert by_item["acceptance report script"]["status"] == "ok"
    assert by_item["Windows packaging script"]["status"] == "ok"
    assert by_item["release gate script"]["status"] == "ok"
    assert by_item["zzz set icon files"]["status"] == "ok"
    assert "configured" in by_item["zzz set icon files"]["detail"]
    assert "files ok" in by_item["zzz set icon files"]["detail"]
    assert by_item["hsr set icon files"]["status"] == "ok"
    assert by_item["hsr set icon files"]["detail"] == "no set icons configured"
    assert by_item["PySide6 desktop runtime"]["status"] in {"ok", "notice"}
    assert by_item["games"]["detail"].endswith("loaded")
    assert not has_resource_errors(rows)


def test_optional_desktop_notices_do_not_fail_doctor():
    rows = [
        {"item": "PySide6 desktop runtime", "status": "notice", "detail": "optional"},
    ]

    assert not has_resource_errors(rows)


def test_missing_runtime_dependency_fails_doctor(monkeypatch):
    monkeypatch.setattr(
        "gear_optimizer.diagnostics.importlib.util.find_spec",
        lambda name: None,
    )

    row = _dependency_row("pydantic", "pydantic", "configuration models")

    assert row["status"] == "missing"
    assert "pip install -e ." in row["detail"]
    assert has_resource_errors([row])


def test_format_resource_check_is_human_readable():
    text = format_resource_check(
        [
            {"item": "desktop app entry", "status": "ok", "detail": "desktop_app.py"},
            {"item": "examples", "status": "missing", "detail": "examples"},
        ]
    )

    assert "desktop app entry" in text
    assert "missing" in text
