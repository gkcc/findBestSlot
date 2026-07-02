from __future__ import annotations

from collections import Counter

from gear_optimizer.models import (
    CharacterPreset,
    CurrentGearAnalysis,
    GameRules,
    GearPiece,
    PieceScore,
    SetRequirement,
    position_key,
)

MAIN_STAT_MISMATCH_PRIORITY_BONUS = 4.0
MAIN_STAT_MISMATCH_SET_PRESSURE_BONUS = 2.5


def effective_lines(piece: GearPiece, character: CharacterPreset) -> int:
    return sum(1 for line in piece.substats if character.is_effective(line.stat))


def effective_rolls(piece: GearPiece, character: CharacterPreset) -> float:
    total = 0.0
    for line in piece.substats:
        if character.is_effective(line.stat):
            total += 1 + line.rolls
    return total


def weighted_effective_score(piece: GearPiece, character: CharacterPreset) -> float:
    return effective_rolls(piece, character)


def substat_priority_label(character: CharacterPreset, stat: str) -> str:
    return character.priority_group_for(stat) or "无效"


def _roll_count_by_priority(piece: GearPiece, character: CharacterPreset) -> dict[str, float]:
    counts = {stat: 0.0 for stat in character.priority_stats()}
    for line in piece.substats:
        if line.stat in counts:
            counts[line.stat] += 1 + line.rolls
    return counts


def substat_quality_vector(piece: GearPiece, character: CharacterPreset) -> tuple[float, ...]:
    priority = character.substat_priority
    if priority is None:
        stats = character.priority_stats()
        counts = _roll_count_by_priority(piece, character)
        total = sum(counts.values())
        return (total, *[counts[stat] for stat in stats])
    counts = _roll_count_by_priority(piece, character)
    core_total = sum(counts[stat] for stat in priority.core)
    usable_total = sum(counts[stat] for stat in priority.usable)
    return (
        core_total,
        *[counts[stat] for stat in priority.core],
        usable_total,
        *[counts[stat] for stat in priority.usable],
    )


def score_quality_sort_key(score: PieceScore, character: CharacterPreset) -> tuple[float, ...]:
    counts = {stat: 0.0 for stat in character.priority_stats()}
    for detail in score.substat_details:
        stat = detail["stat"]
        if stat in counts:
            counts[stat] += float(detail["total_rolls"])
    priority = character.substat_priority
    if priority is None:
        total = sum(counts.values())
        return (total, *[counts[stat] for stat in character.priority_stats()])
    core_total = sum(counts[stat] for stat in priority.core)
    usable_total = sum(counts[stat] for stat in priority.usable)
    return (
        core_total,
        *[counts[stat] for stat in priority.core],
        usable_total,
        *[counts[stat] for stat in priority.usable],
    )


def substat_details(piece: GearPiece, character: CharacterPreset) -> list[dict]:
    details = []
    for line in piece.substats:
        is_effective = character.is_effective(line.stat)
        total_rolls = 1 + line.rolls
        details.append(
            {
                "stat": line.stat,
                "rolls": line.rolls,
                "total_rolls": total_rolls,
                "quality_score": total_rolls if is_effective else 0.0,
                "weighted_score": total_rolls if is_effective else 0.0,
                "priority": substat_priority_label(character, line.stat),
                "priority_rank": character.priority_rank_for(line.stat),
            }
        )
    return details


def _set_requirement_item(requirement: SetRequirement, counts: Counter[str], index: int) -> dict:
    current_by_set = {set_name: counts.get(set_name, 0) for set_name in requirement.set_names}
    selected_set = max(
        requirement.set_names,
        key=lambda set_name: (current_by_set[set_name], -requirement.set_names.index(set_name)),
    )
    current = current_by_set[selected_set]
    item = {
        "set_name": selected_set,
        "required": requirement.pieces,
        "current": current,
        "missing": max(requirement.pieces - current, 0),
    }
    if len(requirement.set_names) > 1:
        item["set_names"] = requirement.set_names
        item["label"] = " / ".join(requirement.set_names)
    if requirement.role:
        item["role"] = requirement.role
    if requirement.priority is not None:
        item["priority"] = requirement.priority
    return item


def _stage_priority_components(item: dict, order: int) -> dict:
    role = str(item.get("role", ""))
    required = item["required"]
    role_value = 18.0 if role.startswith("core") or required >= 4 else 10.0
    progress = item["current"] / required if required else 0.0
    missing_cost = item["missing"] * 3.0
    progress_bonus = progress * 6.0
    configured_priority = float(item.get("priority") or 0.0)
    configured_priority_bonus = configured_priority * 2.0
    replacement_pressure = float(item.get("stage_replacement_pressure") or 0.0)
    replacement_bonus = min(replacement_pressure * 0.8, 10.0)
    replacement_penalty = (
        4.0
        if item["missing"] > 0 and replacement_pressure <= 0
        else 0.0
    )
    order_penalty = order * 0.01
    score = (
        role_value
        + progress_bonus
        + configured_priority_bonus
        + replacement_bonus
        - missing_cost
        - replacement_penalty
        - order_penalty
    )
    stage_type = "核心 4 件" if role.startswith("core") or required >= 4 else f"{required} 件套"
    return {
        "stage_priority_score": round(score, 2),
        "stage_priority_basis": (
            f"算法排序：{stage_type} 基础 {role_value:g}，"
            f"进度 {item['current']}/{required} 加 {progress_bonus:.1f}，"
            f"缺口 {item['missing']} 件扣 {missing_cost:g}，"
            f"配置优先级加 {configured_priority_bonus:.1f}，"
            f"可让位压力 {replacement_pressure:.1f} 加 {replacement_bonus:.1f}"
            f"{'，无可让位盘扣 4.0' if replacement_penalty else ''}。"
        ),
    }


def _stage_priority_score(item: dict, order: int) -> float:
    if item["missing"] <= 0:
        return float("-inf")
    return _stage_priority_components(item, order)["stage_priority_score"]


def _add_stage_priority_details(requirements: list[dict]) -> None:
    for index, item in enumerate(requirements):
        if item["missing"] <= 0:
            item["stage_priority_score"] = 0.0
            item["stage_priority_basis"] = "该阶段已满足，不参与缺口排序。"
            continue
        item.update(_stage_priority_components(item, index))


def _surplus_for_requirement(item: dict, counts: Counter[str]) -> list[dict]:
    alternatives = item.get("set_names", [item["set_name"]])
    selected_set = item["set_name"]
    surplus_rows = []
    selected_surplus = max(item["current"] - item["required"], 0)
    if selected_surplus > 0:
        surplus_rows.append(
            {
                "set_name": selected_set,
                "required": item["required"],
                "current": item["current"],
                "surplus": selected_surplus,
            }
        )
    for set_name in alternatives:
        if set_name == selected_set:
            continue
        current = counts.get(set_name, 0)
        if current > 0:
            surplus_rows.append(
                {
                    "set_name": set_name,
                    "required": 0,
                    "current": current,
                    "surplus": current,
                }
            )
    return surplus_rows


def _missing_target_sets(missing: list[dict]) -> set[str]:
    values: set[str] = set()
    for item in missing:
        values.add(item["set_name"])
        values.update(item.get("set_names", []))
    return values


def _requirement_alternatives(item: dict) -> list[str]:
    return item.get("set_names", [item["set_name"]])


def _requirement_label(item: dict) -> str:
    return item.get("label") or " / ".join(_requirement_alternatives(item))


def _stage_label(item: dict) -> str:
    role = str(item.get("role", ""))
    required = int(item.get("required", 0))
    if role.startswith("core") or required >= 4:
        return "核心 4 件"
    return f"{required} 件套"


def _locked_set_plan_feasibility(
    pieces: list[GearPiece],
    requirements: list[dict],
    target_sets: list[str],
) -> dict:
    locked_pieces = [piece for piece in pieces if piece.locked]
    unlocked_positions = len(pieces) - len(locked_pieces)
    locked_counts = Counter(piece.set_name for piece in locked_pieces)
    minimum_needed = 0
    rows = []

    for item in requirements:
        alternatives = _requirement_alternatives(item)
        best_set = min(
            alternatives,
            key=lambda set_name: (
                max(item["required"] - locked_counts.get(set_name, 0), 0),
                alternatives.index(set_name),
            ),
        )
        locked_current = locked_counts.get(best_set, 0)
        needed = max(item["required"] - locked_current, 0)
        minimum_needed += needed
        rows.append(
            {
                "target": item.get("label") or item["set_name"],
                "selected_set": best_set,
                "required": item["required"],
                "locked_current": locked_current,
                "minimum_unlocked_needed": needed,
            }
        )

    off_plan_locked = [
        {
            "position": piece.position,
            "set_name": piece.set_name,
            "reason": "锁定套装不在当前方案候选内",
        }
        for piece in locked_pieces
        if piece.set_name not in target_sets
    ]
    capacity_gap = max(minimum_needed - unlocked_positions, 0)

    return {
        "feasible_with_locks": capacity_gap == 0,
        "locked_piece_count": len(locked_pieces),
        "unlocked_position_count": unlocked_positions,
        "minimum_unlocked_needed": minimum_needed,
        "locked_capacity_gap": capacity_gap,
        "locked_requirement_rows": rows,
        "locked_conflicts": off_plan_locked,
    }


def _replacement_pressure(
    piece: GearPiece,
    character: CharacterPreset,
    score_by_position: dict[str, PieceScore],
    current_set_is_surplus: bool,
    main_stat_preferred: bool,
) -> float:
    score = score_by_position.get(position_key(piece.position))
    weighted_score = (
        score.weighted_score
        if score is not None
        else weighted_effective_score(piece, character)
    )
    score_gap = max(character.weighted_target_score - weighted_score, 0.0)
    set_gap_bonus = 2.0 if current_set_is_surplus else 1.5
    main_stat_bonus = (
        MAIN_STAT_MISMATCH_SET_PRESSURE_BONUS
        if not main_stat_preferred
        else 0.0
    )
    return round(score_gap + set_gap_bonus + main_stat_bonus, 2)


def _stage_replacement_candidates(
    item: dict,
    pieces: list[GearPiece],
    character: CharacterPreset,
    target_sets: list[str],
    selected_target_sets: set[str],
    surplus_by_set: dict[str, int],
    score_by_position: dict[str, PieceScore],
) -> list[dict]:
    if item["missing"] <= 0:
        return []

    candidates = []
    alternatives = set(_requirement_alternatives(item))
    for piece in pieces:
        if piece.locked:
            continue

        key = position_key(piece.position)
        score = score_by_position.get(key)
        weighted_score = (
            score.weighted_score
            if score is not None
            else weighted_effective_score(piece, character)
        )
        preferred_mains = character.preferred_mains_for(piece.position)
        main_stat_preferred = not preferred_mains or piece.main_stat in preferred_mains
        current_set_is_surplus = surplus_by_set.get(piece.set_name, 0) > 0
        current_set_is_off_plan = piece.set_name not in target_sets
        current_set_is_unselected_alternative = (
            piece.set_name in alternatives and piece.set_name != item["set_name"]
        )
        current_set_is_unused_plan_set = (
            piece.set_name in target_sets and piece.set_name not in selected_target_sets
        )
        replaceable = (
            current_set_is_surplus
            or current_set_is_off_plan
            or current_set_is_unselected_alternative
            or current_set_is_unused_plan_set
        )
        if not replaceable:
            continue

        pressure = _replacement_pressure(
            piece,
            character,
            score_by_position,
            current_set_is_surplus,
            main_stat_preferred,
        )
        candidates.append(
            {
                "position": piece.position,
                "current_set": piece.set_name,
                "target_set": item["set_name"],
                "weighted_score": round(weighted_score, 2),
                "main_stat_preferred": main_stat_preferred,
                "replacement_pressure": pressure,
            }
        )

    return sorted(
        candidates,
        key=lambda row: row["replacement_pressure"],
        reverse=True,
    )


def _add_stage_replacement_details(
    requirements: list[dict],
    pieces: list[GearPiece],
    character: CharacterPreset,
    target_sets: list[str],
    selected_target_sets: set[str],
    surplus_by_set: dict[str, int],
    score_by_position: dict[str, PieceScore],
) -> None:
    for item in requirements:
        candidates = _stage_replacement_candidates(
            item,
            pieces,
            character,
            target_sets,
            selected_target_sets,
            surplus_by_set,
            score_by_position,
        )
        item["stage_replacement_candidates"] = candidates
        item["stage_replacement"] = candidates[0] if candidates else None
        item["stage_replacement_pressure"] = (
            candidates[0]["replacement_pressure"]
            if candidates
            else 0.0
        )


def evaluate_set_plan(
    pieces: list[GearPiece],
    character: CharacterPreset,
    scores: list[PieceScore] | None = None,
) -> dict | None:
    plan = character.active_set_plan()
    if plan is None:
        return None

    counts = Counter(piece.set_name for piece in pieces)
    requirements = [
        _set_requirement_item(requirement, counts, index)
        for index, requirement in enumerate(plan.requirements)
    ]
    target_sets = plan.target_sets
    selected_target_sets = {item["set_name"] for item in requirements}
    surplus = []
    for item in requirements:
        surplus.extend(_surplus_for_requirement(item, counts))
    score_by_position = {
        position_key(score.position): score
        for score in scores or []
    }
    surplus_by_set = {item["set_name"]: item["surplus"] for item in surplus}
    _add_stage_replacement_details(
        requirements,
        pieces,
        character,
        target_sets,
        selected_target_sets,
        surplus_by_set,
        score_by_position,
    )
    _add_stage_priority_details(requirements)
    locked_feasibility = _locked_set_plan_feasibility(
        pieces,
        requirements,
        target_sets,
    )
    missing = [
        item
        for _score, item in sorted(
            (
                (_stage_priority_score(item, index), item)
                for index, item in enumerate(requirements)
                if item["missing"] > 0
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
    ]
    missing_target = missing[0]["set_name"] if missing else None
    position_pressures: dict[str, dict] = {}

    for piece in pieces:
        key = position_key(piece.position)
        score = score_by_position.get(key)
        weighted_score = (
            score.weighted_score
            if score is not None
            else weighted_effective_score(piece, character)
        )
        preferred_mains = character.preferred_mains_for(piece.position)
        main_stat_preferred = not preferred_mains or piece.main_stat in preferred_mains
        current_set_is_surplus = surplus_by_set.get(piece.set_name, 0) > 0
        current_set_is_off_plan = piece.set_name not in target_sets
        current_set_is_unselected_alternative = (
            piece.set_name in target_sets and piece.set_name not in selected_target_sets
        )
        replaceable = (not piece.locked) and bool(missing) and (
            current_set_is_surplus
            or current_set_is_off_plan
            or current_set_is_unselected_alternative
        )
        pressure = 0.0
        if replaceable:
            score_gap = max(character.weighted_target_score - weighted_score, 0.0)
            set_gap_bonus = 2.0 if current_set_is_surplus else 1.5
            main_stat_bonus = (
                MAIN_STAT_MISMATCH_SET_PRESSURE_BONUS
                if not main_stat_preferred
                else 0.0
            )
            pressure = score_gap + set_gap_bonus + main_stat_bonus

        position_pressures[key] = {
            "position": piece.position,
            "current_set": piece.set_name,
            "target_set": missing_target,
            "weighted_score": round(weighted_score, 2),
            "main_stat_preferred": main_stat_preferred,
            "locked": piece.locked,
            "replaceable_for_set_plan": replaceable,
            "replacement_pressure": round(pressure, 2),
            "replacement_rank": None,
            "replacement_badge": "已锁定" if piece.locked else "可替换" if replaceable else "保留",
            "reason": (
                "用户标记保留，不参与套装让位"
                if piece.locked
                else "可替换为缺口套装"
                if replaceable
                else "保留当前套装以维持组合"
                if missing
                else "套装组合已满足"
            ),
        }

    suggested_replacements = sorted(
        (
            row
            for row in position_pressures.values()
            if row["replacement_pressure"] > 0
        ),
        key=lambda row: row["replacement_pressure"],
        reverse=True,
    )
    for rank, row in enumerate(suggested_replacements, start=1):
        key = position_key(row["position"])
        position_pressures[key]["replacement_rank"] = rank
        if rank == 1:
            position_pressures[key]["replacement_badge"] = "优先替换"
        row["replacement_rank"] = rank
        row["replacement_badge"] = position_pressures[key]["replacement_badge"]

    return {
        "id": plan.id,
        "name": plan.name,
        "is_unrestricted": plan.is_unrestricted,
        "target_sets": target_sets,
        "requirements": requirements,
        "missing": missing,
        "surplus": surplus,
        "position_pressures": position_pressures,
        "suggested_replacements": suggested_replacements,
        "position_targets": _build_position_target_plan(
            pieces,
            requirements,
            missing,
            target_sets,
            character,
            score_by_position,
        ),
        **locked_feasibility,
        "satisfied": plan.is_unrestricted or all(item["missing"] == 0 for item in requirements),
    }


def _score_for_position(
    piece: GearPiece,
    score_by_position: dict[str, PieceScore],
    character: CharacterPreset,
) -> tuple[float, bool]:
    score = score_by_position.get(position_key(piece.position))
    weighted_score = (
        score.weighted_score
        if score is not None
        else weighted_effective_score(piece, character)
    )
    preferred_mains = character.preferred_mains_for(piece.position)
    main_stat_preferred = not preferred_mains or piece.main_stat in preferred_mains
    return weighted_score, main_stat_preferred


def _set_slot_keep_value(
    piece: GearPiece,
    score_by_position: dict[str, PieceScore],
    character: CharacterPreset,
) -> tuple[float, float, int]:
    weighted_score, main_stat_preferred = _score_for_position(
        piece,
        score_by_position,
        character,
    )
    lock_bonus = 100.0 if piece.locked else 0.0
    main_bonus = 5.0 if main_stat_preferred else 0.0
    return (lock_bonus + weighted_score + main_bonus, weighted_score, -int(piece.locked))


def _target_assignment_row(
    piece: GearPiece,
    item: dict,
    character: CharacterPreset,
    score_by_position: dict[str, PieceScore],
    *,
    status: str,
    action: str,
    reason: str,
) -> dict:
    weighted_score, main_stat_preferred = _score_for_position(
        piece,
        score_by_position,
        character,
    )
    return {
        "position": piece.position,
        "current_set": piece.set_name,
        "target_set": item["set_name"],
        "target_options": _requirement_alternatives(item),
        "target_group": _requirement_label(item),
        "stage": _stage_label(item),
        "status": status,
        "action": action,
        "weighted_score": round(weighted_score, 2),
        "main_stat_preferred": main_stat_preferred,
        "locked": piece.locked,
        "reason": reason,
    }


def _build_position_target_plan(
    pieces: list[GearPiece],
    requirements: list[dict],
    missing: list[dict],
    target_sets: list[str],
    character: CharacterPreset,
    score_by_position: dict[str, PieceScore],
) -> list[dict]:
    assignments: dict[str, dict] = {}

    for item in sorted(
        requirements,
        key=lambda requirement: (
            0 if _stage_label(requirement) == "核心 4 件" else 1,
            -int(requirement.get("required", 0)),
        ),
    ):
        matching_pieces = [
            piece
            for piece in pieces
            if piece.set_name == item["set_name"]
            and position_key(piece.position) not in assignments
        ]
        matching_pieces.sort(
            key=lambda piece: _set_slot_keep_value(piece, score_by_position, character),
            reverse=True,
        )
        for piece in matching_pieces[: int(item["required"])]:
            weighted_score, main_stat_preferred = _score_for_position(
                piece,
                score_by_position,
                character,
            )
            status = "锁定保留" if piece.locked else "规划保留"
            reason = (
                f"当前已命中 {_requirement_label(item)}，"
                f"质量分 {weighted_score:g}，"
                f"主属性{'命中' if main_stat_preferred else '偏离'}。"
            )
            if piece.locked:
                reason += "锁定盘优先保留。"
            assignments[position_key(piece.position)] = _target_assignment_row(
                piece,
                item,
                character,
                score_by_position,
                status=status,
                action=f"保留为{_stage_label(item)}",
                reason=reason,
            )

    for item in missing:
        needed = int(item.get("missing", 0))
        selected = 0
        for candidate in item.get("stage_replacement_candidates", []):
            if selected >= needed:
                break
            key = position_key(candidate["position"])
            if key in assignments:
                continue
            piece = next(
                current_piece
                for current_piece in pieces
                if position_key(current_piece.position) == key
            )
            assignments[key] = _target_assignment_row(
                piece,
                item,
                character,
                score_by_position,
                status="建议让位",
                action=f"调律为{item['set_name']}",
                reason=(
                    f"{_stage_label(item)}缺口需要补 {_requirement_label(item)}；"
                    f"当前位置质量分 {candidate['weighted_score']:g}，"
                    f"让位压力 {candidate['replacement_pressure']:g}。"
                ),
            )
            selected += 1

    first_missing = missing[0] if missing else None
    for piece in pieces:
        key = position_key(piece.position)
        if key in assignments:
            continue
        weighted_score, main_stat_preferred = _score_for_position(
            piece,
            score_by_position,
            character,
        )
        if piece.locked:
            target_item = {
                "set_name": piece.set_name,
                "set_names": [piece.set_name],
                "required": 0,
                "role": "locked",
            }
            status = (
                "锁定保留"
                if not target_sets or piece.set_name in target_sets
                else "锁定冲突"
            )
            assignments[key] = _target_assignment_row(
                piece,
                target_item,
                character,
                score_by_position,
                status=status,
                action="锁定保留" if status == "锁定保留" else "改方案或解锁",
                reason=(
                    "用户标记保留，仍参与评分但不参与让位。"
                    if status == "锁定保留"
                    else "锁定盘不属于当前套装方案候选，可能导致方案不可完成。"
                ),
            )
        elif first_missing is not None:
            assignments[key] = _target_assignment_row(
                piece,
                first_missing,
                character,
                score_by_position,
                status="候补让位",
                action=f"必要时改为{first_missing['set_name']}",
                reason=(
                    f"当前还缺 {_requirement_label(first_missing)}，但该位置"
                    f"质量分 {weighted_score:g}，主属性"
                    f"{'命中' if main_stat_preferred else '偏离'}，优先级低于已推荐让位盘。"
                ),
            )
        else:
            target_item = {
                "set_name": piece.set_name,
                "set_names": [piece.set_name],
                "required": 0,
                "role": "free",
            }
            assignments[key] = _target_assignment_row(
                piece,
                target_item,
                character,
                score_by_position,
                status="质量优化",
                action="按主属性和副词条优化",
                reason="套装方案已满足，该位置不承担新增套装缺口。",
            )

    return sorted(
        assignments.values(),
        key=lambda row: (
            0,
            int(position_key(row["position"])),
        )
        if position_key(row["position"]).isdigit()
        else (1, position_key(row["position"])),
    )


def rating_for_score(score: float, character: CharacterPreset) -> str:
    thresholds = character.rating_thresholds
    if score >= thresholds.get("excellent", 6.0):
        return "excellent"
    if score >= thresholds.get("good", 4.0):
        return "good"
    if score >= thresholds.get("usable", 2.0):
        return "usable"
    return "weak"


def score_piece(piece: GearPiece, game: GameRules, character: CharacterPreset) -> PieceScore:
    effective = effective_rolls(piece, character)
    score = weighted_effective_score(piece, character)
    preferred_mains = character.preferred_mains_for(piece.position)
    active_set_plan = character.active_set_plan()
    target_sets = set(active_set_plan.target_sets) if active_set_plan else set()
    set_plan_preferred = (
        active_set_plan is None
        or active_set_plan.is_unrestricted
        or piece.set_name in target_sets
    )
    return PieceScore(
        position=piece.position,
        position_name=game.position_name(piece.position),
        set_name=piece.set_name,
        main_stat=piece.main_stat,
        level=piece.level,
        locked=piece.locked,
        effective_lines=effective_lines(piece, character),
        effective_rolls=effective,
        weighted_score=score,
        rating=rating_for_score(score, character),  # type: ignore[arg-type]
        main_stat_preferred=not preferred_mains or piece.main_stat in preferred_mains,
        set_plan_preferred=set_plan_preferred,
        substat_details=substat_details(piece, character),
    )


def analyse_current_gear(
    pieces: list[GearPiece],
    game: GameRules,
    character: CharacterPreset,
) -> CurrentGearAnalysis:
    scores = [score_piece(piece, game, character) for piece in pieces]
    weakest = min(scores, key=lambda item: score_quality_sort_key(item, character), default=None)
    set_plan = evaluate_set_plan(pieces, character, scores)

    priority = []
    for item in scores:
        gap = max(character.weighted_target_score - item.weighted_score, 0.0)
        if not item.main_stat_preferred:
            gap += MAIN_STAT_MISMATCH_PRIORITY_BONUS
        if not item.set_plan_preferred:
            gap += 1.0
        if set_plan and set_plan["missing"]:
            missing_sets = _missing_target_sets(set_plan["missing"])
            if item.set_name not in missing_sets:
                gap += 0.5
            pressure = set_plan["position_pressures"][position_key(item.position)][
                "replacement_pressure"
            ]
            gap += min(pressure * 0.35, 2.5)
        if weakest and position_key(item.position) == position_key(weakest.position):
            gap += 1.5
        if item.locked:
            gap = 0.0
        set_replacement_pressure = (
            set_plan["position_pressures"][position_key(item.position)]["replacement_pressure"]
            if set_plan
            else 0.0
        )
        set_replacement_badge = (
            set_plan["position_pressures"][position_key(item.position)]["replacement_badge"]
            if set_plan
            else "保留"
        )
        priority.append(
            {
                "position": item.position,
                "position_name": item.position_name,
                "current_effective_rolls": item.effective_rolls,
                "current_weighted_score": item.weighted_score,
                "current_score": item.weighted_score,
                "rating": item.rating,
                "main_stat": item.main_stat,
                "main_stat_target": "、".join(character.preferred_mains_for(item.position)) or "不限",
                "main_stat_issue": "偏离目标" if not item.main_stat_preferred else "命中/不限",
                "locked": item.locked,
                "main_stat_preferred": item.main_stat_preferred,
                "set_plan_preferred": item.set_plan_preferred,
                "set_replacement_pressure": set_replacement_pressure,
                "set_replacement_badge": set_replacement_badge,
                "priority_score": round(gap, 2),
            }
        )

    priority.sort(key=lambda row: row["priority_score"], reverse=True)
    return CurrentGearAnalysis(
        scores=scores,
        weakest_position=weakest.position if weakest else None,
        weakest_position_name=weakest.position_name if weakest else None,
        relative_priority=priority,
        set_plan=set_plan,
    )
