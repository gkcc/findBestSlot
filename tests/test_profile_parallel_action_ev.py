from gear_optimizer.profile_parallel_action_ev import main as parallel_profile_main


def test_profile_parallel_action_ev_writes_report(tmp_path):
    output = tmp_path / "parallel_profile.md"

    assert (
        parallel_profile_main(
            [
                "--horizon",
                "1",
                "--action-limit",
                "2",
                "--workers",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    text = output.read_text(encoding="utf-8")
    assert "# Action EV Parallel Profile" in text
    assert "workers=1" in text
    assert "process-pool" in text
