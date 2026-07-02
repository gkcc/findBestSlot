from gear_optimizer import paths


def test_app_data_root_uses_project_user_data_in_source_mode(monkeypatch):
    monkeypatch.delenv("GEAR_OPTIMIZER_USER_DATA_DIR", raising=False)
    monkeypatch.delenv("GEAR_OPTIMIZER_USER_DATA", raising=False)
    monkeypatch.setattr(paths, "is_frozen_app", lambda: False)

    assert paths.app_data_root() == paths.PROJECT_ROOT / "user_data"


def test_app_data_root_uses_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(paths, "is_frozen_app", lambda: True)

    assert paths.app_data_root() == tmp_path.resolve()


def test_app_data_root_uses_local_app_data_in_frozen_windows(monkeypatch, tmp_path):
    monkeypatch.delenv("GEAR_OPTIMIZER_USER_DATA_DIR", raising=False)
    monkeypatch.delenv("GEAR_OPTIMIZER_USER_DATA", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(paths, "is_frozen_app", lambda: True)
    monkeypatch.setattr(paths.sys, "platform", "win32")

    assert paths.app_data_root() == tmp_path / "gacha-gear-optimizer" / "user_data"


def test_app_data_root_falls_back_to_temp_when_frozen_data_dir_is_unwritable(
    monkeypatch,
    tmp_path,
):
    blocked = tmp_path / "blocked"
    temp_root = tmp_path / "temp"
    original_mkdir = paths.Path.mkdir

    def fake_mkdir(self, *args, **kwargs):
        if str(self).startswith(str(blocked)):
            raise PermissionError("blocked")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.delenv("GEAR_OPTIMIZER_USER_DATA_DIR", raising=False)
    monkeypatch.delenv("GEAR_OPTIMIZER_USER_DATA", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(blocked))
    monkeypatch.setattr(paths, "is_frozen_app", lambda: True)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setattr(paths.tempfile, "gettempdir", lambda: str(temp_root))
    monkeypatch.setattr(paths.Path, "mkdir", fake_mkdir)

    assert paths.app_data_root() == temp_root / "gacha-gear-optimizer" / "user_data"
