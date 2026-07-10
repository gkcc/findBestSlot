import io

from gear_optimizer.action_ev_protocol import ActionEvWorkerRequest
from scripts import benchmark_action_ev
from scripts.benchmark_action_ev import (
    build_default_request,
    build_report,
    load_benchmark_fixture,
)


class ReconfigurableTextStream(io.StringIO):
    def __init__(self):
        super().__init__()
        self.configuration = None

    def reconfigure(self, **kwargs):
        self.configuration = kwargs


def test_benchmark_cli_forces_utf8_output(monkeypatch):
    stdout = ReconfigurableTextStream()
    stderr = ReconfigurableTextStream()
    monkeypatch.setattr(benchmark_action_ev.sys, "stdout", stdout)
    monkeypatch.setattr(benchmark_action_ev.sys, "stderr", stderr)

    benchmark_action_ev._configure_standard_streams()

    assert stdout.configuration == {"encoding": "utf-8", "errors": "strict"}
    assert stderr.configuration == {"encoding": "utf-8", "errors": "strict"}


def test_default_benchmark_is_fixed_horizon_two_request():
    request = build_default_request()

    assert isinstance(request, ActionEvWorkerRequest)
    assert request.game_id == "zzz"
    assert request.character_id == "user_zzz_ye_shunguang_叶瞬光"
    assert request.horizon == 2
    assert request.action_mode == "fast"
    assert len(request.current_pieces) == 6
    assert len(request.inventory_pieces) == 33


def test_benchmark_fixture_carries_its_non_product_target_template():
    request, target = load_benchmark_fixture()

    assert target.id == request.character_id
    assert target.name == "叶瞬光 H=2 性能基准"
    assert target.active_set_plan().requirements[0].set_names == ["沧浪行歌"]
    assert "不作为产品内置默认模板" in target.notes


def test_benchmark_report_requires_cold_and_warm_runs_to_pass():
    result = {
        "cold": {"elapsed_seconds": 59.0, "rows": 10, "performance_audit": {}},
        "warm": {"elapsed_seconds": 61.0, "rows": 10, "performance_audit": {}},
    }

    report = build_report(result, threshold_seconds=60.0)

    assert report["cold_pass"] is True
    assert report["warm_pass"] is False
    assert report["passed"] is False
