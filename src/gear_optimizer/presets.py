from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from gear_optimizer.game_rules import load_game
from gear_optimizer.models import CandidatePiece, CharacterPreset, GearPiece, ProbabilityModel
from gear_optimizer.project_paths import PROJECT_ROOT


def _example_metadata(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    game = str(data.get("game") or (path.name.split("_", 1)[0] if "_" in path.name else ""))
    return {
        "label": str(data.get("label") or path.stem),
        "path": str(path.relative_to(PROJECT_ROOT)),
        "game": game,
        "character": str(data.get("character") or ""),
    }


def load_current_example(path: str | Path) -> list[GearPiece]:
    full_path = PROJECT_ROOT / path
    with full_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return current_gear_data_to_pieces(data)


def _game_supports_revealed_next_substat(game_id: str | None) -> bool:
    if not game_id:
        return True
    try:
        return load_game(game_id).enhancement.revealed_next_substat_supported
    except (FileNotFoundError, KeyError):
        return True


def _revealed_next_substat_repeats_known_stat(item: dict[str, Any]) -> bool:
    revealed = item.get("revealed_next_substat")
    if not revealed:
        return False
    if revealed == item.get("main_stat"):
        return True
    substats = item.get("substats") or []
    if not isinstance(substats, list):
        return False
    for line in substats:
        if isinstance(line, dict) and line.get("stat") == revealed:
            return True
    return False


def sanitize_piece_data_for_game(item: Any, game_id: str | None) -> Any:
    if not isinstance(item, dict):
        return item
    if "revealed_next_substat" not in item:
        return item
    if _revealed_next_substat_repeats_known_stat(item):
        sanitized = dict(item)
        sanitized.pop("revealed_next_substat", None)
        return sanitized
    if _game_supports_revealed_next_substat(game_id):
        return item
    sanitized = dict(item)
    sanitized.pop("revealed_next_substat", None)
    return sanitized


def current_gear_data_to_pieces(data: dict, game_id: str | None = None) -> list[GearPiece]:
    pieces = data.get("pieces", [])
    if not isinstance(pieces, list):
        raise ValueError("Current gear YAML must contain a pieces list")
    source_game_id = game_id or str(data.get("game") or "")
    return [
        GearPiece.model_validate(sanitize_piece_data_for_game(item, source_game_id))
        for item in pieces
    ]


def load_current_yaml_text(text: str) -> tuple[dict, list[GearPiece]]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("Current gear YAML must be a mapping")
    return data, current_gear_data_to_pieces(data)


def load_candidate_example(path: str | Path) -> CandidatePiece:
    full_path = PROJECT_ROOT / path
    with full_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return candidate_data_to_piece(data)


def candidate_data_to_piece(data: dict, game_id: str | None = None) -> CandidatePiece:
    if not isinstance(data, dict):
        raise ValueError("Candidate YAML must be a mapping")
    source_game_id = game_id or str(data.get("game") or "")
    return CandidatePiece.model_validate(sanitize_piece_data_for_game(data, source_game_id))


def load_candidate_yaml_text(text: str) -> tuple[dict, CandidatePiece]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("Candidate YAML must be a mapping")
    return data, candidate_data_to_piece(data)


def character_target_data_to_preset(data: dict) -> CharacterPreset:
    if not isinstance(data, dict):
        raise ValueError("Character target YAML must be a mapping")
    return CharacterPreset.model_validate(data)


def load_character_target_yaml_text(text: str) -> tuple[dict, CharacterPreset]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("Character target YAML must be a mapping")
    return data, character_target_data_to_preset(data)


def probability_model_data_to_model(data: dict) -> ProbabilityModel:
    if not isinstance(data, dict):
        raise ValueError("Probability model YAML must be a mapping")
    return ProbabilityModel.model_validate(data)


def load_probability_model_yaml_text(text: str) -> tuple[dict, ProbabilityModel]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("Probability model YAML must be a mapping")
    return data, probability_model_data_to_model(data)


def list_candidate_examples(game_id: str | None = None) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    for path in sorted((PROJECT_ROOT / "examples").glob("*candidate*.yaml")):
        item = _example_metadata(path)
        example_game = item["game"]
        if game_id and example_game and example_game != game_id:
            continue
        if game_id and not example_game and not path.name.startswith(f"{game_id}_"):
            continue
        examples.append(item)
    return examples


def list_current_examples(
    game_id: str | None = None,
    character_id: str | None = None,
) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    for path in sorted((PROJECT_ROOT / "examples").glob("*current*.yaml")):
        item = _example_metadata(path)
        example_game = item["game"]
        example_character = item["character"]
        if game_id and example_game and example_game != game_id:
            continue
        if game_id and not example_game and not path.name.startswith(f"{game_id}_"):
            continue
        if character_id and example_character and example_character != character_id:
            continue
        examples.append(item)
    return examples
