import json

from gear_optimizer.profile_action_ev import main as profile_main


def test_profile_action_ev_writes_json_and_summary(tmp_path):
    output = tmp_path / "action_ev_profile.json"
    summary = tmp_path / "action_ev_profile_summary.md"

    assert (
        profile_main(
            [
                "--horizon",
                "1",
                "--output",
                str(output),
                "--summary",
                str(summary),
            ]
        )
        == 0
    )

    profile = json.loads(output.read_text(encoding="utf-8"))
    summary_text = summary.read_text(encoding="utf-8")
    assert profile["horizon"] == 1
    assert profile["action_count"] > 0
    assert "outcome_count" in profile
    assert "dp_state_count" in profile
    assert "aggregated_outcome_cache_misses" in profile
    assert "state_transition_cache_misses" in profile
    assert "top_slow_actions" in profile
    assert "# Action EV Profile Summary" in summary_text


def test_profile_action_ev_can_profile_state_dp(tmp_path):
    output = tmp_path / "action_ev_profile_state_dp.json"
    summary = tmp_path / "action_ev_profile_state_dp_summary.md"

    assert (
        profile_main(
            [
                "--horizon",
                "1",
                "--state-dp",
                "--output",
                str(output),
                "--summary",
                str(summary),
            ]
        )
        == 0
    )

    profile = json.loads(output.read_text(encoding="utf-8"))
    summary_text = summary.read_text(encoding="utf-8")
    assert profile["engine"] == "state_dp"
    assert profile["state_transition_cache_misses"] > 0
    assert "engine: state_dp" in summary_text
