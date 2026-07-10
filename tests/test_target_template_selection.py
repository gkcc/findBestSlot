from pathlib import Path

import pytest

from gear_optimizer.storage_io import StoreRevisionConflictError
from gear_optimizer.target_template_selection import (
    TargetTemplateSelectionStore,
    clear_target_template_selection,
    load_target_template_selection_store,
    save_target_template_selection_store,
    select_target_template,
    target_template_selection_store_path,
)


def test_target_template_selection_is_persisted_per_agent(tmp_path: Path):
    select_target_template("zzz", "agent_a", "template_a", tmp_path)
    select_target_template("zzz", "agent_b", "template_b", tmp_path)

    store = load_target_template_selection_store("zzz", tmp_path)

    assert store.selections == {
        "agent_a": "template_a",
        "agent_b": "template_b",
    }
    assert store.revision == 2
    assert target_template_selection_store_path("zzz", tmp_path).exists()


def test_clearing_one_target_selection_does_not_touch_other_agents(tmp_path: Path):
    select_target_template("zzz", "agent_a", "template_a", tmp_path)
    select_target_template("zzz", "agent_b", "template_b", tmp_path)

    clear_target_template_selection("zzz", "agent_a", tmp_path)

    assert load_target_template_selection_store("zzz", tmp_path).selections == {
        "agent_b": "template_b"
    }


def test_target_selection_store_uses_revision_conflict_protection(tmp_path: Path):
    first = TargetTemplateSelectionStore(game="zzz")
    save_target_template_selection_store(first, tmp_path)
    stale = TargetTemplateSelectionStore(game="zzz", revision=0)

    with pytest.raises(StoreRevisionConflictError):
        save_target_template_selection_store(stale, tmp_path)
