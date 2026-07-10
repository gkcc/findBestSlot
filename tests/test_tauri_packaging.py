import json
from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TAURI_ROOT = PROJECT_ROOT / "desktop" / "src-tauri"


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
