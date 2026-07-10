import json
from pathlib import Path

from scripts.generate_rust_best_loadout_fixtures import build_fixture


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "rust_best_loadout_golden.json"


def test_rust_best_loadout_golden_fixture_matches_python_reference():
    committed = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert committed == build_fixture()
    assert len(committed["cases"]) >= 6
    assert any(case["expected"] is None for case in committed["cases"])
    tie_case = next(
        case
        for case in committed["cases"]
        if case["name"] == "equal_value_preserves_python_input_order"
    )
    assert tie_case["expected"]["selected_item_ids"][0] == "a-first"
