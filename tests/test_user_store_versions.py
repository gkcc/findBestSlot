import pytest
import yaml
from pydantic import ValidationError

from gear_optimizer.agents import GlobalInventoryStore
from gear_optimizer.storage_io import UnsupportedStoreVersionError
from gear_optimizer.user_current_gear import current_gear_store_path, load_user_current_gears
from gear_optimizer.user_inventory import load_user_inventory, user_inventory_store_path
from gear_optimizer.user_set_plans import load_user_set_plans, set_plan_store_path
from gear_optimizer.user_target_templates import load_user_target_templates, target_template_store_path


@pytest.mark.parametrize(
    ("path_factory", "loader"),
    [
        (
            lambda root: current_gear_store_path("zzz", "agent", root),
            lambda root: load_user_current_gears("zzz", "agent", root),
        ),
        (
            lambda root: user_inventory_store_path("zzz", "agent", root),
            lambda root: load_user_inventory("zzz", "agent", root),
        ),
        (
            lambda root: set_plan_store_path("zzz", "agent", root),
            lambda root: load_user_set_plans("zzz", "agent", root),
        ),
        (
            lambda root: target_template_store_path("zzz", root),
            lambda root: load_user_target_templates("zzz", root),
        ),
    ],
)
def test_user_store_loaders_reject_future_schema_versions(tmp_path, path_factory, loader):
    path = path_factory(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"schema_version": 2}, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(UnsupportedStoreVersionError, match="schema_version 2"):
        loader(tmp_path)


def test_multi_agent_models_reject_future_schema_versions():
    with pytest.raises(ValidationError, match="less than or equal to 1"):
        GlobalInventoryStore(game="zzz", schema_version=2)
