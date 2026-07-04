from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import TypeVar

import yaml
from pydantic import BaseModel

from gear_optimizer.models import (
    CandidatePiece,
    CharacterPreset,
    GameRules,
    GearPiece,
    ProbabilityModel,
    position_key,
)

def _looks_like_project_root(path: Path) -> bool:
    return (
        (path / "pyproject.toml").exists()
        and (path / "desktop_app.py").exists()
        and (path / "configs" / "games").exists()
        and (path / "examples").exists()
    )


def project_root() -> Path:
    override = os.environ.get("GEAR_OPTIMIZER_PROJECT_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    package_source_root = Path(__file__).resolve().parents[2]
    bundle_root = getattr(sys, "_MEIPASS", None)
    candidates = []
    if bundle_root:
        candidates.append(Path(bundle_root).resolve())
    candidates.extend(
        [
            Path.cwd().resolve(),
            package_source_root,
        ]
    )
    for parent in Path.cwd().resolve().parents:
        candidates.append(parent)

    for candidate in candidates:
        if _looks_like_project_root(candidate):
            return candidate
    return package_source_root


PROJECT_ROOT = project_root()

T = TypeVar("T", bound=BaseModel)


def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return data


def _load_model(path: Path, model: type[T]) -> T:
    return model.model_validate(read_yaml(path))


def config_dir(kind: str) -> Path:
    return PROJECT_ROOT / "configs" / kind


def list_config_files(kind: str) -> list[Path]:
    folder = config_dir(kind)
    if not folder.exists():
        return []
    return sorted(folder.glob("*.yaml"))


def load_games() -> list[GameRules]:
    return [_load_model(path, GameRules) for path in list_config_files("games")]


def load_game(game_id: str) -> GameRules:
    for game in load_games():
        if game.id == game_id:
            return game
    raise KeyError(f"No game config found for {game_id}")


def validate_character_against_game(character: CharacterPreset, game: GameRules) -> None:
    if character.game != game.id:
        raise ValueError(f"Character {character.id} belongs to {character.game}, not {game.id}")
    if character.target_set not in game.sets:
        raise ValueError(f"Character {character.id} target_set is not in game sets: {character.target_set}")

    unknown_effective = set(character.effective_substats) - set(game.sub_stats)
    if unknown_effective:
        raise ValueError(
            f"Character {character.id} effective_substats reference unknown stats: "
            f"{sorted(unknown_effective)}"
        )

    position_by_key = {str(position.id): position for position in game.positions}
    for position_id, preferred_stats in character.preferred_main_stats.items():
        if position_id not in position_by_key:
            raise ValueError(
                f"Character {character.id} preferred_main_stats references unknown position: {position_id}"
            )
        allowed = set(position_by_key[position_id].main_stats)
        unknown_mains = set(preferred_stats) - allowed
        if unknown_mains:
            raise ValueError(
                f"Character {character.id} preferred_main_stats for {position_id} "
                f"reference unknown main stats: {sorted(unknown_mains)}"
            )

    game_sets = set(game.sets)
    position_count = len(game.positions)
    for plan in character.set_plans:
        required_pieces = sum(requirement.pieces for requirement in plan.requirements)
        if required_pieces > position_count:
            raise ValueError(
                f"Character {character.id} set plan {plan.id} requires {required_pieces} pieces, "
                f"but {game.id} only has {position_count} positions"
            )
        for requirement in plan.requirements:
            unknown_sets = set(requirement.set_names) - game_sets
            if unknown_sets:
                raise ValueError(
                    f"Character {character.id} set plan {plan.id} references unknown sets: "
                    f"{sorted(unknown_sets)}"
                )


def _upgrade_events_at_level(game: GameRules, level: int) -> int:
    return sum(1 for event_level in game.enhancement.event_levels if event_level <= level)


def _max_rolls_for_piece(game: GameRules, piece: GearPiece) -> int:
    events = _upgrade_events_at_level(game, piece.level)
    if (
        piece.initial_substat_count == 3
        and piece.level >= game.enhancement.initial_add_level
    ):
        events -= 1
    return max(events, 0)


def _max_visible_substats(game: GameRules, piece: GearPiece) -> int:
    if (
        piece.initial_substat_count == 4
        or piece.level >= game.enhancement.initial_add_level
    ):
        return 4
    return 3


def validate_gear_piece_against_game(piece: GearPiece, game: GameRules) -> None:
    position_keys = {position_key(position.id) for position in game.positions}
    key = position_key(piece.position)
    if key not in position_keys:
        raise ValueError(f"Gear position is not valid for {game.id}: {piece.position}")
    if game.sets and piece.set_name not in game.sets:
        raise ValueError(f"Gear set is not valid for {game.id}: {piece.set_name}")
    if game.sets and not game.set_available_for_position(piece.set_name, piece.position):
        raise ValueError(
            f"Gear set {piece.set_name} is not available for position {piece.position}"
        )
    allowed_mains = set(game.main_stats_for(piece.position))
    if piece.main_stat not in allowed_mains:
        raise ValueError(
            f"Gear main_stat {piece.main_stat} is not valid for position {piece.position}"
        )
    if (
        piece.level < 0
        or piece.level > game.enhancement.max_level
        or piece.level % game.enhancement.step != 0
    ):
        raise ValueError(
            f"Gear level must be 0..{game.enhancement.max_level} "
            f"in +{game.enhancement.step} steps, got {piece.level}"
        )
    max_substats = _max_visible_substats(game, piece)
    if len(piece.substats) > max_substats:
        raise ValueError(
            f"Gear at +{piece.level} can show at most {max_substats} substats, "
            f"got {len(piece.substats)}"
        )
    allowed_substats = set(game.sub_stats)
    unknown_substats = {line.stat for line in piece.substats} - allowed_substats
    if unknown_substats:
        raise ValueError(f"Gear substats reference unknown stats: {sorted(unknown_substats)}")
    if any(line.stat == piece.main_stat for line in piece.substats):
        raise ValueError("Gear substats cannot repeat the main stat")
    total_rolls = sum(line.rolls for line in piece.substats)
    max_rolls = _max_rolls_for_piece(game, piece)
    if total_rolls > max_rolls:
        raise ValueError(
            f"Gear roll total exceeds +{piece.level} limit: {total_rolls} > {max_rolls}"
        )


def validate_current_gear_against_game(
    pieces: list[GearPiece],
    game: GameRules,
    require_complete: bool = False,
) -> None:
    seen_positions: set[str] = set()
    for piece in pieces:
        key = position_key(piece.position)
        if key in seen_positions:
            raise ValueError(f"Current gear contains duplicate position: {piece.position}")
        seen_positions.add(key)
        validate_gear_piece_against_game(piece, game)
    if require_complete:
        expected_positions = {position_key(position.id) for position in game.positions}
        missing = expected_positions - seen_positions
        if missing:
            raise ValueError(f"Current gear is missing positions: {sorted(missing)}")


def validate_candidate_against_game(candidate: CandidatePiece, game: GameRules) -> None:
    validate_gear_piece_against_game(candidate, game)


def load_characters(game_id: str | None = None) -> list[CharacterPreset]:
    games_by_id = {game.id: game for game in load_games()}
    characters = []
    for path in list_config_files("characters"):
        character = _load_model(path, CharacterPreset)
        if character.game not in games_by_id:
            raise ValueError(f"Character {character.id} references unknown game: {character.game}")
        validate_character_against_game(character, games_by_id[character.game])
        characters.append(character)
    if game_id is not None:
        characters = [character for character in characters if character.game == game_id]
    return characters


def load_probability_models(game_id: str | None = None) -> list[ProbabilityModel]:
    games_by_id = {game.id: game for game in load_games()}
    models = []
    for path in list_config_files("probabilities"):
        model = _load_model(path, ProbabilityModel)
        if model.game not in games_by_id:
            raise ValueError(f"Probability model {model.id} references unknown game: {model.game}")
        models.append(model)
    if game_id is not None:
        models = [model for model in models if model.game == game_id]
    return models
