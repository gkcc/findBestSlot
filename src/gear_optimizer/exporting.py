from __future__ import annotations

from collections.abc import Sequence

import yaml

from gear_optimizer.models import CandidatePiece, CharacterPreset, GearPiece, ProbabilityModel


def _gear_piece_export_data(piece: GearPiece) -> dict:
    data = piece.model_dump(mode="json", exclude_none=True)
    if not piece.locked:
        data.pop("locked", None)
    return data


def current_gear_export_data(
    game_id: str,
    character_id: str,
    pieces: Sequence[GearPiece],
    label: str | None = None,
) -> dict:
    return {
        "game": game_id,
        "character": character_id,
        "label": label or f"{character_id} current gear",
        "pieces": [
            _gear_piece_export_data(piece)
            for piece in pieces
        ],
    }


def character_target_export_data(character: CharacterPreset) -> dict:
    data = character.model_dump(mode="json", exclude_none=True)
    if data.get("substat_priority"):
        data.pop("effective_substats", None)
    return data


def candidate_export_data(
    game_id: str,
    candidate: CandidatePiece,
    label: str | None = None,
) -> dict:
    data = candidate.model_dump(mode="json", exclude_none=True)
    data.pop("locked", None)
    return {
        "game": game_id,
        "label": label or f"{game_id} candidate gear",
        **data,
    }


def probability_model_export_data(model: ProbabilityModel) -> dict:
    return model.model_dump(mode="json", exclude_none=True)


def to_yaml(data: dict) -> str:
    return yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
    )


def current_gear_yaml(
    game_id: str,
    character_id: str,
    pieces: Sequence[GearPiece],
    label: str | None = None,
) -> str:
    return to_yaml(
        current_gear_export_data(
            game_id,
            character_id,
            pieces,
            label,
        )
    )


def character_target_yaml(character: CharacterPreset) -> str:
    return to_yaml(character_target_export_data(character))


def candidate_yaml(
    game_id: str,
    candidate: CandidatePiece,
    label: str | None = None,
) -> str:
    return to_yaml(candidate_export_data(game_id, candidate, label))


def probability_model_yaml(model: ProbabilityModel) -> str:
    return to_yaml(probability_model_export_data(model))
