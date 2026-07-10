from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gear_optimizer.models import CharacterPreset, GearPiece


DESKTOP_PROTOCOL_SCHEMA_VERSION = 1


class UnsupportedDesktopProtocolVersionError(ValueError):
    pass


class _DesktopProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = DESKTOP_PROTOCOL_SCHEMA_VERSION


class DesktopRequest(_DesktopProtocolModel):
    request_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class DesktopError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class DesktopResponse(_DesktopProtocolModel):
    request_id: str = Field(min_length=1)
    ok: bool
    data: dict[str, Any] | None = None
    error: DesktopError | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> "DesktopResponse":
        if self.ok and self.error is not None:
            raise ValueError("successful desktop response cannot contain an error")
        if not self.ok and self.error is None:
            raise ValueError("failed desktop response must contain an error")
        return self


class DesktopEvent(_DesktopProtocolModel):
    request_id: str | None = None
    run_id: str | None = None
    event: str = Field(min_length=1)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    payload: dict[str, Any] = Field(default_factory=dict)


class DesktopGameSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    gear_name: str


class DesktopPositionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    main_stats: list[str]
    set_names: list[str]


class DesktopAgentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    name: str
    rarity: str
    attribute: str
    specialty: str
    faction: str
    portrait_path: str | None = None
    card_path: str | None = None
    configured_target_template_id: str = ""


class DesktopTargetTemplateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    builtin: bool
    source_agent_id: str = ""
    preferred_main_stats: dict[str, list[str]] = Field(default_factory=dict)
    target_sets: list[str] = Field(default_factory=list)
    priority_stats: list[str] = Field(default_factory=list)


class DesktopItemOwner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    agent_name: str
    loadout_id: str
    position: str


class DesktopInventoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    piece: GearPiece
    status: Literal["backpack", "equipped"]
    equipped_by: DesktopItemOwner | None = None
    referenced_by_snapshots: int = Field(default=0, ge=0)


class DesktopLoadoutSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: str
    position_name: str
    item_id: str | None = None
    item: DesktopInventoryItem | None = None


class DesktopLoadout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loadout_id: str | None = None
    label: str = "当前装备"
    slots: list[DesktopLoadoutSlot] = Field(default_factory=list)
    complete: bool = False


class DesktopCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    reason: str = ""


class DesktopWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    games: list[DesktopGameSummary]
    game_id: str
    game_name: str
    gear_name: str
    sets: list[str]
    sub_stats: list[str]
    max_level: int
    level_step: int
    positions: list[DesktopPositionOption]
    agents: list[DesktopAgentSummary]
    agent_id: str
    target_templates: list[DesktopTargetTemplateSummary]
    active_target_template_id: str | None = None
    active_target_template: CharacterPreset | None = None
    inventory: list[DesktopInventoryItem]
    current_loadout: DesktopLoadout
    capabilities: dict[str, DesktopCapability]
    inventory_revision: int = 0
    loadout_revision: int = 0
    target_selection_revision: int = 0
    canonical_inventory: bool = False


def parse_desktop_request(value: Any) -> DesktopRequest:
    if not isinstance(value, dict):
        raise ValueError("desktop request must be a JSON object")
    version = value.get("schema_version", DESKTOP_PROTOCOL_SCHEMA_VERSION)
    if version != DESKTOP_PROTOCOL_SCHEMA_VERSION:
        raise UnsupportedDesktopProtocolVersionError(
            f"unsupported desktop protocol schema_version: {version}"
        )
    return DesktopRequest.model_validate(value)


def desktop_protocol_json_schema() -> dict[str, Any]:
    return {
        "schema_version": DESKTOP_PROTOCOL_SCHEMA_VERSION,
        "request": DesktopRequest.model_json_schema(),
        "response": DesktopResponse.model_json_schema(),
        "event": DesktopEvent.model_json_schema(),
        "workspace": DesktopWorkspace.model_json_schema(),
    }
