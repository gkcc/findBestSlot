from pathlib import Path

import pytest

import gear_optimizer.inventory_migration as inventory_migration
from gear_optimizer.agents import MigrationIssue, MigrationReport


def test_inventory_migration_cli_defaults_to_read_only_dry_run(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_dry_run(game_id, root=None):
        calls.append(("dry", game_id, root))
        return MigrationReport(game=game_id, dry_run=True)

    monkeypatch.setattr(inventory_migration, "dry_run_multi_agent_migration", fake_dry_run)
    monkeypatch.setattr(
        inventory_migration,
        "apply_multi_agent_migration",
        lambda *_args, **_kwargs: pytest.fail("apply must not run without --apply"),
    )

    result = inventory_migration.main(["--game", "zzz", "--root", str(tmp_path)])

    assert result == 0
    assert calls == [("dry", "zzz", Path(tmp_path))]
    assert "模式：dry-run" in capsys.readouterr().out


def test_inventory_migration_cli_requires_explicit_apply_and_can_write_json_report(
    monkeypatch,
    tmp_path,
):
    report = MigrationReport(game="zzz", dry_run=False, backup_path="backups/run")
    calls = []

    def fake_apply(game_id, root=None):
        calls.append((game_id, root))
        return report

    monkeypatch.setattr(inventory_migration, "apply_multi_agent_migration", fake_apply)
    output = tmp_path / "migration.json"

    result = inventory_migration.main(
        ["--game", "zzz", "--root", str(tmp_path), "--apply", "--json", "--output", str(output)]
    )

    assert result == 0
    assert calls == [("zzz", Path(tmp_path))]
    assert '"dry_run": false' in output.read_text(encoding="utf-8")


def test_inventory_migration_cli_returns_nonzero_for_blocking_dry_run(monkeypatch):
    report = MigrationReport(
        game="zzz",
        dry_run=True,
        issues=[MigrationIssue(severity="error", code="broken", message="broken reference")],
    )
    monkeypatch.setattr(
        inventory_migration,
        "dry_run_multi_agent_migration",
        lambda *_args, **_kwargs: report,
    )

    assert inventory_migration.main(["--game", "zzz"]) == 2
