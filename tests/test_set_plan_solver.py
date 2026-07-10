import pytest

from gear_optimizer.models import SetPlan, SetRequirement
from gear_optimizer.set_plan_solver import set_plan_satisfied_by_counts


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ({"A": 4, "B": 2}, True),
        ({"A": 4, "C": 2}, True),
        ({"A": 4, "B": 1, "C": 1}, False),
        ({"A": 3, "B": 2}, False),
    ],
)
def test_set_plan_solver_handles_flexible_four_plus_two(counts, expected):
    plan = SetPlan(
        id="four_plus_two",
        name="4+2",
        requirements=[
            SetRequirement(set_name="A", pieces=4),
            SetRequirement(set_names=["B", "C"], pieces=2),
        ],
    )

    assert set_plan_satisfied_by_counts(plan, counts) is expected


def test_set_plan_solver_does_not_reuse_same_set_count_for_two_requirements():
    plan = SetPlan(
        id="flexible_pairs",
        name="flexible pairs",
        requirements=[
            SetRequirement(set_names=["A", "B"], pieces=2),
            SetRequirement(set_name="A", pieces=2),
        ],
    )

    assert not set_plan_satisfied_by_counts(plan, {"A": 2})
    assert set_plan_satisfied_by_counts(plan, {"A": 4})
    assert set_plan_satisfied_by_counts(plan, {"A": 2, "B": 2})


def test_set_plan_solver_accepts_missing_or_unrestricted_plan():
    unrestricted = SetPlan(id="free", name="free", requirements=[])

    assert set_plan_satisfied_by_counts(None, {})
    assert set_plan_satisfied_by_counts(unrestricted, {})
