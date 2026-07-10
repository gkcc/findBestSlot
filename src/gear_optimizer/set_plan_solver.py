from __future__ import annotations

from collections.abc import Mapping

from gear_optimizer.models import SetPlan


def set_plan_satisfied_by_counts(
    plan: SetPlan | None,
    counts: Mapping[str, int],
) -> bool:
    if plan is None or plan.is_unrestricted:
        return True

    remaining = {str(set_name): max(int(count), 0) for set_name, count in counts.items()}
    requirements = tuple(plan.requirements)

    def can_satisfy(index: int) -> bool:
        if index >= len(requirements):
            return True
        requirement = requirements[index]
        for set_name in requirement.set_names:
            available = remaining.get(set_name, 0)
            if available < requirement.pieces:
                continue
            remaining[set_name] = available - requirement.pieces
            if can_satisfy(index + 1):
                remaining[set_name] = available
                return True
            remaining[set_name] = available
        return False

    return can_satisfy(0)
