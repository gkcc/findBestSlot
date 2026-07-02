import importlib

import gear_optimizer


def test_public_package_modules_are_importable():
    for module_name in gear_optimizer.__all__:
        assert importlib.import_module(f"gear_optimizer.{module_name}")
