import json
from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TAURI_ROOT = PROJECT_ROOT / "desktop" / "src-tauri"
WINDOWS_BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_tauri_windows.ps1"
PACKAGED_BACKEND_SMOKE = PROJECT_ROOT / "scripts" / "smoke_packaged_backend.py"


def test_packaged_tauri_resources_keep_python_data_and_workers_together():
    config = json.loads((TAURI_ROOT / "tauri.bundle.conf.json").read_text(encoding="utf-8"))
    resources = config["bundle"]["resources"]

    assert resources["../../assets"] == "assets"
    assert resources["../../configs"] == "configs"
    assert resources["../../examples"] == "examples"
    assert resources[
        "../../build/tauri-sidecars/gear-optimizer-backend.exe"
    ] == "gear-optimizer-backend.exe"
    assert resources[
        "../../build/tauri-sidecars/gear-optimizer-action-worker.exe"
    ] == "gear-optimizer-action-worker.exe"


def test_base_tauri_config_enables_scoped_local_asset_protocol():
    config = json.loads((TAURI_ROOT / "tauri.conf.json").read_text(encoding="utf-8"))
    asset_protocol = config["app"]["security"]["assetProtocol"]

    assert asset_protocol["enable"] is True
    assert "$RESOURCE/**" in asset_protocol["scope"]
    assert "resources" not in config["bundle"]

    cargo = tomllib.loads((TAURI_ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    assert "protocol-asset" in cargo["dependencies"]["tauri"]["features"]


def test_windows_installer_embeds_the_offline_webview_runtime():
    config = json.loads((TAURI_ROOT / "tauri.conf.json").read_text(encoding="utf-8"))

    install_mode = config["bundle"]["windows"]["webviewInstallMode"]
    assert install_mode == {"type": "offlineInstaller", "silent": True}


def test_windows_application_icon_is_packaged():
    icon = TAURI_ROOT / "icons" / "icon.ico"

    assert icon.stat().st_size > 10_000
    assert icon.read_bytes()[:4] == b"\x00\x00\x01\x00"


def test_windows_build_finds_standard_user_toolchain_locations():
    script = WINDOWS_BUILD_SCRIPT.read_text(encoding="utf-8")

    assert 'nodejs\\node.exe' in script
    assert 'npm\\pnpm.cmd' in script
    assert '.cargo\\bin\\cargo.exe' in script
    assert str(PACKAGED_BACKEND_SMOKE.relative_to(PROJECT_ROOT)).replace("/", "\\") in script
