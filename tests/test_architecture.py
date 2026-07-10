import ast
from pathlib import Path

import gear_optimizer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "gear_optimizer"

PUBLIC_MODULES = {
    "acceptance",
    "action_ev_protocol",
    "action_types",
    "agents",
    "candidate_ev",
    "conclusions",
    "desktop_ui_smoke",
    "desktop_protocol",
    "desktop_service",
    "diagnostics",
    "exporting",
    "game_rules",
    "inventory_service",
    "launcher",
    "layout",
    "models",
    "piece_distribution",
    "portfolio_ev",
    "portfolio_models",
    "position_ev",
    "presets",
    "probability",
    "project_paths",
    "readiness",
    "recommendation",
    "release_manifest",
    "reporting",
    "runtime_logging",
    "scoring",
    "set_plan_solver",
    "storage_io",
    "strategy",
    "target_template_selection",
    "ui_assets",
    "user_current_gear",
    "user_inventory",
    "user_set_plans",
    "user_target_templates",
}

# Existing debt is frozen so it can only shrink while CS-P1-06/07 are resolved.
ALLOWED_PRIVATE_IMPORTS = {
    ("desktop_ui_smoke", "gear_optimizer.pyside6_app", "_default_piece"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_action_costs"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_action_main_label"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_action_position_items"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_action_position_label"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_action_progress_label"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_action_substat_label"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_action_type_label"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_advance_existing_roll_states"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_best_combo_rows"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_candidate_inventory_row"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_combo_value"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_dedupe_action_specs"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_expected_upgrade_loadout_row"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_fresh_piece_outcome_distribution"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_generation_action_specs"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_inventory_piece_id"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_is_loadout_candidate"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_normalise_inventory_rows"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_piece_contribution_key"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_positive_gain"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_roll_state_from_piece"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_set_distribution"),
    ("portfolio_ev", "gear_optimizer.position_ev", "_upgrade_action_specs"),
    ("profile_parallel_action_ev", "gear_optimizer.position_ev", "_generation_action_specs"),
    ("readiness", "gear_optimizer.release_manifest", "_manifest_exe_path"),
}


def _private_package_imports() -> set[tuple[str, str, str]]:
    imports: set[tuple[str, str, str]] = set()
    for path in PACKAGE_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if not module.startswith("gear_optimizer."):
                continue
            for alias in node.names:
                if alias.name.startswith("_"):
                    imports.add((path.stem, module, alias.name))
    return imports


def _base_exception_catches() -> list[tuple[str, int, str]]:
    catches: list[tuple[str, int, str]] = []
    for path in PACKAGE_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                catches.append((path.stem, node.lineno, "bare"))
            elif isinstance(node.type, ast.Name) and node.type.id == "BaseException":
                catches.append((path.stem, node.lineno, "BaseException"))
    return catches


def _direct_atomic_yaml_writers() -> list[tuple[str, int]]:
    calls: list[tuple[str, int]] = []
    for path in PACKAGE_ROOT.glob("*.py"):
        if path.stem == "storage_io":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "atomic_write_yaml"
            ):
                calls.append((path.stem, node.lineno))
    return calls


def test_public_package_module_boundary_is_explicit():
    assert set(gear_optimizer.__all__) == PUBLIC_MODULES
    assert not {
        "action_ev_worker",
        "profile_action_ev",
        "profile_parallel_action_ev",
        "pyside6_app",
    } & PUBLIC_MODULES


def test_cross_module_private_import_debt_does_not_grow():
    assert _private_package_imports() <= ALLOWED_PRIVATE_IMPORTS


def test_production_code_does_not_catch_base_exception_or_use_bare_except():
    assert _base_exception_catches() == []


def test_user_store_yaml_writes_use_the_concurrency_protocol():
    assert _direct_atomic_yaml_writers() == []
