from __future__ import annotations

from pathlib import Path

import yaml

from gear_optimizer.game_rules import PROJECT_ROOT
from gear_optimizer.models import CandidatePiece, CharacterPreset, GearPiece, ProbabilityModel


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


def current_gear_data_to_pieces(data: dict) -> list[GearPiece]:
    pieces = data.get("pieces", [])
    if not isinstance(pieces, list):
        raise ValueError("Current gear YAML must contain a pieces list")
    return [GearPiece.model_validate(item) for item in pieces]


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


def candidate_data_to_piece(data: dict) -> CandidatePiece:
    if not isinstance(data, dict):
        raise ValueError("Candidate YAML must be a mapping")
    return CandidatePiece.model_validate(data)


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
