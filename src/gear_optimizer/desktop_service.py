from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import sys
import time
from typing import Any
import uuid
import zipfile

from pydantic import ValidationError

from gear_optimizer.agents import (
    DEFAULT_LOADOUT_ID,
    AgentLoadout,
    AgentLoadoutStore,
    AgentMetadata,
    agent_metadata_with_fallbacks,
    load_agent_catalog,
    load_agent_user_state_store,
    load_global_inventory_store,
    load_inventory_items_compatible,
)
from gear_optimizer.desktop_protocol import (
    DesktopAgentSummary,
    DesktopCapability,
    DesktopError,
    DesktopGameSummary,
    DesktopInventoryItem,
    DesktopItemOwner,
    DesktopLoadout,
    DesktopLoadoutSlot,
    DesktopPositionOption,
    DesktopRequest,
    DesktopResponse,
    DesktopTargetTemplateSummary,
    DesktopWorkspace,
    UnsupportedDesktopProtocolVersionError,
    parse_desktop_request,
)
from gear_optimizer.desktop_jobs import DesktopActionJobManager
from gear_optimizer.action_ev_protocol import ActionEvWorkerRequest
from gear_optimizer.game_rules import (
    load_characters,
    load_game,
    load_games,
    load_probability_models,
    validate_character_against_game,
    validate_gear_piece_against_game,
)
from gear_optimizer.inventory_service import (
    activate_agent_loadout,
    add_inventory_piece,
    canonical_inventory_available,
    delete_agent_loadout_snapshot,
    delete_inventory_item,
    equip_inventory_item,
    load_agent_loadout_stores,
    unequip_inventory_position,
    update_inventory_piece,
)
from gear_optimizer.models import CharacterPreset, GearPiece, position_key
from gear_optimizer.runtime_logging import append_runtime_event
from gear_optimizer.storage_io import (
    StoreLockTimeoutError,
    StoreRevisionConflictError,
)
from gear_optimizer.target_template_selection import (
    clear_target_template_selection,
    load_target_template_selection_store,
    select_target_template,
)
from gear_optimizer.user_target_templates import (
    delete_user_target_template,
    hide_builtin_target_template,
    load_hidden_builtin_target_template_ids,
    load_user_target_template_source_agents,
    load_user_target_template_sources,
    load_user_target_templates,
    save_user_target_template,
)


DESKTOP_BACKEND_LOG_NAME = "desktop-backend.jsonl"


def _active_loadout(
    store: AgentLoadoutStore,
    requested_id: str,
) -> AgentLoadout | None:
    requested = next(
        (loadout for loadout in store.loadouts if loadout.loadout_id == requested_id),
        None,
    )
    if requested is not None:
        return requested
    default = next(
        (loadout for loadout in store.loadouts if loadout.loadout_id == DEFAULT_LOADOUT_ID),
        None,
    )
    return default or (store.loadouts[0] if store.loadouts else None)


def _target_templates_for_agent(
    game_id: str,
    agent: AgentMetadata,
    root: Path | None,
) -> tuple[list[CharacterPreset], dict[str, str], dict[str, str]]:
    hidden = load_hidden_builtin_target_template_ids(game_id, root)
    builtin = [
        character
        for character in load_characters(game_id)
        if character.id not in hidden
    ]
    user_templates = load_user_target_templates(game_id, root)
    source_characters = load_user_target_template_sources(game_id, root)
    source_agents = load_user_target_template_source_agents(game_id, root)

    def belongs(template: CharacterPreset) -> bool:
        if agent.character_preset_id and template.id == agent.character_preset_id:
            return True
        if source_agents.get(template.id) == agent.agent_id:
            return True
        source_character = source_characters.get(template.id, "")
        return bool(
            agent.character_preset_id
            and source_character == agent.character_preset_id
        )

    templates = [template for template in [*builtin, *user_templates] if belongs(template)]
    templates.sort(key=lambda item: (not item.id.startswith("user_"), item.name, item.id))
    return templates, source_characters, source_agents


def _find_agent(game_id: str, agent_id: str | None) -> tuple[list[AgentMetadata], AgentMetadata]:
    characters = load_characters(game_id)
    agents = agent_metadata_with_fallbacks(
        game_id,
        characters,
        load_agent_catalog(game_id),
    )
    if not agents:
        raise ValueError(f"game has no configured agents: {game_id}")
    if agent_id:
        selected = next((agent for agent in agents if agent.agent_id == agent_id), None)
        if selected is None:
            raise KeyError(f"unknown agent_id: {agent_id}")
    else:
        selected = agents[0]
    return agents, selected


def _inventory_and_loadouts(
    game_id: str,
    selected_agent: AgentMetadata,
    agent_names: dict[str, str],
    root: Path | None,
) -> tuple[
    list[DesktopInventoryItem],
    dict[str, DesktopInventoryItem],
    AgentLoadout | None,
    int,
    int,
    bool,
]:
    canonical = canonical_inventory_available(game_id, root)
    if canonical:
        inventory_store = load_global_inventory_store(game_id, root)
        inventory_items = inventory_store.items
        inventory_revision = inventory_store.revision
        loadout_stores = load_agent_loadout_stores(game_id, root)
    else:
        inventory_items = load_inventory_items_compatible(
            game_id,
            selected_agent.agent_id,
            root,
        )
        inventory_revision = 0
        loadout_stores = []

    user_states = load_agent_user_state_store(game_id, root)
    active_by_agent: dict[str, AgentLoadout] = {}
    selected_store = next(
        (store for store in loadout_stores if store.agent_id == selected_agent.agent_id),
        AgentLoadoutStore(game=game_id, agent_id=selected_agent.agent_id),
    )
    for store in loadout_stores:
        state = user_states.agents.get(store.agent_id)
        requested_id = state.active_loadout_id if state else DEFAULT_LOADOUT_ID
        active = _active_loadout(store, requested_id)
        if active is not None:
            active_by_agent[store.agent_id] = active

    owners: dict[str, DesktopItemOwner] = {}
    reference_counts: Counter[str] = Counter()
    for store in loadout_stores:
        for loadout in store.loadouts:
            for item_id in loadout.slot_items.values():
                if item_id:
                    reference_counts[item_id] += 1
        active = active_by_agent.get(store.agent_id)
        if active is None:
            continue
        for position, item_id in active.slot_items.items():
            if not item_id:
                continue
            if item_id in owners:
                previous = owners[item_id]
                raise ValueError(
                    "inventory item is equipped by multiple active loadouts: "
                    f"{item_id} ({previous.agent_id}, {store.agent_id})"
                )
            owners[item_id] = DesktopItemOwner(
                agent_id=store.agent_id,
                agent_name=agent_names.get(store.agent_id, store.agent_id),
                loadout_id=active.loadout_id,
                position=position_key(position),
            )

    inventory: list[DesktopInventoryItem] = []
    by_id: dict[str, DesktopInventoryItem] = {}
    for item in inventory_items:
        owner = owners.get(item.item_id)
        row = DesktopInventoryItem(
            item_id=item.item_id,
            piece=item.piece,
            status="equipped" if owner else "backpack",
            equipped_by=owner,
            referenced_by_snapshots=reference_counts[item.item_id],
        )
        inventory.append(row)
        by_id[item.item_id] = row
    inventory.sort(
        key=lambda row: (
            str(row.piece.position),
            row.piece.set_name,
            row.piece.main_stat,
            row.item_id,
        )
    )

    selected_state = user_states.agents.get(selected_agent.agent_id)
    selected_requested_id = (
        selected_state.active_loadout_id if selected_state else DEFAULT_LOADOUT_ID
    )
    selected_loadout = _active_loadout(selected_store, selected_requested_id)
    return (
        inventory,
        by_id,
        selected_loadout,
        inventory_revision,
        selected_store.revision,
        canonical,
    )


def load_desktop_workspace(
    game_id: str | None = None,
    agent_id: str | None = None,
    root: Path | None = None,
) -> DesktopWorkspace:
    games = load_games()
    if not games:
        raise ValueError("no game configurations are available")
    selected_game = (
        next((game for game in games if game.id == game_id), None)
        if game_id
        else games[0]
    )
    if selected_game is None:
        raise KeyError(f"unknown game_id: {game_id}")

    agents, selected_agent = _find_agent(selected_game.id, agent_id)
    agent_names = {agent.agent_id: agent.name for agent in agents}
    templates, _source_characters, source_agents = _target_templates_for_agent(
        selected_game.id,
        selected_agent,
        root,
    )
    selections = load_target_template_selection_store(selected_game.id, root)
    remembered_id = selections.selections.get(selected_agent.agent_id, "")
    active_template = next(
        (template for template in templates if template.id == remembered_id),
        None,
    )
    if active_template is None and selected_agent.character_preset_id:
        active_template = next(
            (
                template
                for template in templates
                if template.id == selected_agent.character_preset_id
            ),
            None,
        )
    if active_template is None and templates:
        active_template = templates[0]

    (
        inventory,
        inventory_by_id,
        active_loadout,
        inventory_revision,
        loadout_revision,
        canonical,
    ) = _inventory_and_loadouts(
        selected_game.id,
        selected_agent,
        agent_names,
        root,
    )

    slots: list[DesktopLoadoutSlot] = []
    for position in selected_game.positions:
        key = position_key(position.id)
        item_id = active_loadout.slot_items.get(key) if active_loadout else None
        slots.append(
            DesktopLoadoutSlot(
                position=key,
                position_name=position.name,
                item_id=item_id,
                item=inventory_by_id.get(item_id) if item_id else None,
            )
        )
    complete = bool(slots) and all(slot.item_id for slot in slots)
    current_loadout = DesktopLoadout(
        loadout_id=active_loadout.loadout_id if active_loadout else None,
        label=active_loadout.label if active_loadout else "当前装备",
        slots=slots,
        complete=complete,
    )

    has_target = active_template is not None
    if not has_target:
        compute_reason = "当前代理人没有目标模板，请先创建目标模板。"
    elif not complete:
        compute_reason = (
            f"当前装备只有 {sum(bool(slot.item_id) for slot in slots)}/{len(slots)} 件；"
            "补齐后可进行单代理计算。"
        )
    else:
        compute_reason = ""
    write_reason = "" if canonical else "旧格式库存只读，请先迁移为全局 item_id 库存。"
    capabilities = {
        "inventory_write": DesktopCapability(available=canonical, reason=write_reason),
        "loadout_write": DesktopCapability(available=canonical, reason=write_reason),
        "target_template_write": DesktopCapability(available=True),
        "best_loadout": DesktopCapability(
            available=has_target and complete,
            reason=compute_reason,
        ),
        "action_ev": DesktopCapability(
            available=has_target and complete,
            reason=compute_reason,
        ),
        "portfolio_ev": DesktopCapability(
            available=has_target,
            reason="" if has_target else "至少需要一个代理人目标模板。",
        ),
    }

    return DesktopWorkspace(
        games=[
            DesktopGameSummary(id=game.id, name=game.name, gear_name=game.gear_name)
            for game in games
        ],
        game_id=selected_game.id,
        game_name=selected_game.name,
        gear_name=selected_game.gear_name,
        sets=list(selected_game.sets),
        sub_stats=list(selected_game.sub_stats),
        max_level=selected_game.enhancement.max_level,
        level_step=selected_game.enhancement.step,
        positions=[
            DesktopPositionOption(
                id=position_key(position.id),
                name=position.name,
                main_stats=list(position.main_stats),
                set_names=selected_game.sets_for_position(position.id),
            )
            for position in selected_game.positions
        ],
        agents=[
            DesktopAgentSummary(
                agent_id=agent.agent_id,
                name=agent.name,
                rarity=agent.rarity,
                attribute=agent.attribute,
                specialty=agent.specialty,
                faction=agent.faction,
                portrait_path=agent.portrait_path,
                card_path=agent.card_path,
                configured_target_template_id=agent.character_preset_id,
            )
            for agent in agents
        ],
        agent_id=selected_agent.agent_id,
        target_templates=[
            DesktopTargetTemplateSummary(
                id=template.id,
                name=template.name,
                builtin=not template.id.startswith("user_"),
                source_agent_id=source_agents.get(template.id, ""),
                preferred_main_stats=template.preferred_main_stats,
                target_sets=(
                    template.active_set_plan().target_sets
                    if template.active_set_plan() is not None
                    else [template.target_set]
                ),
                priority_stats=template.priority_stats(),
            )
            for template in templates
        ],
        active_target_template_id=active_template.id if active_template else None,
        active_target_template=active_template,
        inventory=inventory,
        current_loadout=current_loadout,
        capabilities=capabilities,
        inventory_revision=inventory_revision,
        loadout_revision=loadout_revision,
        target_selection_revision=selections.revision,
        canonical_inventory=canonical,
    )


class DesktopService:
    def __init__(self, root: Path | None = None):
        self.root = root
        self.jobs = DesktopActionJobManager(root)

    @property
    def log_path(self) -> Path:
        if self.root is not None:
            return self.root / "logs" / DESKTOP_BACKEND_LOG_NAME
        from gear_optimizer.paths import app_data_root

        return app_data_root() / "logs" / DESKTOP_BACKEND_LOG_NAME

    def execute(self, request: DesktopRequest) -> DesktopResponse:
        started = time.perf_counter()
        params = dict(request.params)
        game_id = str(params.get("game_id") or "")
        agent_id = str(params.get("agent_id") or "")
        try:
            data = self._execute_method(request.method, params)
            response = DesktopResponse(request_id=request.request_id, ok=True, data=data)
            self._log(
                "desktop_request_completed",
                request=request,
                elapsed=time.perf_counter() - started,
                game_id=game_id,
                agent_id=agent_id,
                result="ok",
            )
            return response
        except Exception as exc:
            error = self._error_from_exception(exc)
            self._log(
                "desktop_request_failed",
                request=request,
                elapsed=time.perf_counter() - started,
                game_id=game_id,
                agent_id=agent_id,
                result="error",
                error_code=error.code,
                error_message=error.message,
            )
            return DesktopResponse(
                request_id=request.request_id,
                ok=False,
                error=error,
            )

    def execute_raw(self, value: Any) -> DesktopResponse:
        request_id = (
            str(value.get("request_id") or "invalid-request")
            if isinstance(value, dict)
            else "invalid-request"
        )
        try:
            request = parse_desktop_request(value)
        except Exception as exc:
            return DesktopResponse(
                request_id=request_id,
                ok=False,
                error=self._error_from_exception(exc),
            )
        return self.execute(request)

    def _execute_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method in {"system.ping", "system.shutdown"}:
            if method == "system.shutdown":
                self.jobs.shutdown()
            return {
                "service": "gear-optimizer-desktop-backend",
                "protocol_version": 1,
                "shutdown": method == "system.shutdown",
            }
        if method == "logs.tail":
            limit = min(max(int(params.get("limit") or 200), 1), 500)
            return {"events": self._tail_logs(limit)}
        if method == "diagnostics.export":
            game_id = str(params.get("game_id") or "") or None
            agent_id = str(params.get("agent_id") or "") or None
            return {"path": str(self._export_diagnostics(game_id, agent_id))}
        if method == "ui.event":
            event = str(params.get("event") or "").strip()
            if not event:
                raise ValueError("event is required")
            fields = params.get("fields") or {}
            if not isinstance(fields, dict):
                raise ValueError("event fields must be a JSON object")
            append_runtime_event(
                self.log_path,
                event,
                source="tauri_ui",
                **fields,
            )
            return {"recorded": True}
        if method == "workspace.get":
            workspace = load_desktop_workspace(
                str(params.get("game_id") or "") or None,
                str(params.get("agent_id") or "") or None,
                self.root,
            )
            return {"workspace": workspace.model_dump(mode="json")}

        game_id, agent_id = self._context(params)
        if method == "action_job.start":
            job = self.jobs.start(
                self._action_job_request(game_id, agent_id, params),
                agent_id=agent_id,
            )
            return {"job": job.model_dump(mode="json")}
        if method == "action_job.status":
            job = self.jobs.status(str(params.get("job_id") or ""))
            return {"job": job.model_dump(mode="json")}
        if method == "action_job.cancel":
            job = self.jobs.cancel(str(params.get("job_id") or ""))
            return {"job": job.model_dump(mode="json")}
        if method == "action_job.list":
            return {
                "jobs": [job.model_dump(mode="json") for job in self.jobs.list()]
            }
        if method == "target_template.select":
            template_id = str(params.get("template_id") or "")
            workspace = load_desktop_workspace(game_id, agent_id, self.root)
            allowed = {template.id for template in workspace.target_templates}
            if template_id not in allowed:
                raise ValueError(
                    f"target template {template_id!r} does not belong to agent {agent_id}"
                )
            select_target_template(game_id, agent_id, template_id, self.root)
        elif method == "target_template.save":
            game = load_game(game_id)
            _agents, agent = _find_agent(game_id, agent_id)
            template = CharacterPreset.model_validate(params.get("template"))
            validate_character_against_game(template, game)
            saved = save_user_target_template(
                game_id,
                template,
                str(params.get("label") or template.name),
                self.root,
                source_character_id=agent.character_preset_id or None,
                source_agent_id=agent_id,
            )
            select_target_template(game_id, agent_id, saved.id, self.root)
        elif method == "target_template.delete":
            template_id = str(params.get("template_id") or "")
            workspace = load_desktop_workspace(game_id, agent_id, self.root)
            allowed = {template.id: template for template in workspace.target_templates}
            template = allowed.get(template_id)
            if template is None:
                raise ValueError(
                    f"target template {template_id!r} does not belong to agent {agent_id}"
                )
            if template.builtin:
                hide_builtin_target_template(game_id, template_id, self.root)
            else:
                delete_user_target_template(game_id, template_id, self.root)
            selections = load_target_template_selection_store(game_id, self.root)
            if selections.selections.get(agent_id) == template_id:
                clear_target_template_selection(game_id, agent_id, self.root)
        elif method in {"inventory.create", "inventory.update"}:
            game = load_game(game_id)
            piece = GearPiece.model_validate(params.get("piece"))
            validate_gear_piece_against_game(piece, game)
            if method == "inventory.create":
                add_inventory_piece(game_id, piece, self.root)
            else:
                update_inventory_piece(
                    game_id,
                    str(params.get("item_id") or ""),
                    piece,
                    self.root,
                )
        elif method == "inventory.delete":
            delete_inventory_item(
                game_id,
                str(params.get("item_id") or ""),
                self.root,
            )
        elif method == "loadout.equip":
            equip_inventory_item(
                game_id,
                agent_id,
                str(params.get("item_id") or ""),
                self.root,
            )
        elif method == "loadout.unequip":
            unequip_inventory_position(
                game_id,
                agent_id,
                str(params.get("position") or ""),
                self.root,
            )
        elif method == "loadout.activate":
            activate_agent_loadout(
                game_id,
                agent_id,
                str(params.get("loadout_id") or ""),
                self.root,
            )
        elif method == "loadout.snapshot.delete":
            delete_agent_loadout_snapshot(
                game_id,
                agent_id,
                str(params.get("loadout_id") or ""),
                self.root,
            )
        else:
            raise LookupError(f"unknown desktop backend method: {method}")

        workspace = load_desktop_workspace(game_id, agent_id, self.root)
        return {"workspace": workspace.model_dump(mode="json")}

    def _action_job_request(
        self,
        game_id: str,
        agent_id: str,
        params: dict[str, Any],
    ) -> ActionEvWorkerRequest:
        workspace = load_desktop_workspace(game_id, agent_id, self.root)
        capability = workspace.capabilities["action_ev"]
        if not capability.available:
            raise ValueError(capability.reason)
        if workspace.active_target_template_id is None:
            raise ValueError("当前代理人没有目标模板。")
        probability_models = load_probability_models(game_id)
        if not probability_models:
            raise ValueError(f"game has no probability model: {game_id}")
        requested_model_id = str(params.get("probability_model_id") or "")
        probability_model = next(
            (model for model in probability_models if model.id == requested_model_id),
            probability_models[0],
        )
        horizon = int(params.get("horizon") or 1)
        run_id = f"desktop-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        current_pieces = [
            slot.item.piece.model_dump(mode="json")
            for slot in workspace.current_loadout.slots
            if slot.item is not None
        ]
        inventory_pieces = [
            item.piece.model_dump(mode="json")
            for item in workspace.inventory
            if item.status == "backpack"
        ]
        audit_lines = [
            f"游戏：{workspace.game_name} ({game_id})",
            f"代理人：{agent_id}",
            f"目标模板：{workspace.active_target_template_id}",
            f"当前装备：{len(current_pieces)}/{len(workspace.positions)}",
            f"可用背包库存：{len(inventory_pieces)}",
            (
                "revision："
                f"inventory={workspace.inventory_revision}, "
                f"loadout={workspace.loadout_revision}, "
                f"target={workspace.target_selection_revision}"
            ),
        ]
        return ActionEvWorkerRequest(
            run_id=run_id,
            game_id=game_id,
            character_id=workspace.active_target_template_id,
            probability_model_id=probability_model.id,
            current_pieces=current_pieces,
            inventory_pieces=inventory_pieces,
            horizon=horizon,
            engine=str(params.get("engine") or "inventory_recursive"),
            action_mode=str(params.get("action_mode") or "fast"),
            input_audit="\n".join(audit_lines),
            input_audit_lines=audit_lines,
        )

    def _tail_logs(self, limit: int) -> list[dict[str, Any]]:
        paths = [
            self.log_path.with_name(f"{self.log_path.name}.{index}")
            for index in range(3, 0, -1)
        ] + [self.log_path]
        events: list[dict[str, Any]] = []
        for path in paths:
            if not path.exists():
                continue
            try:
                lines = path.read_text(encoding="utf-8-sig").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    events.append(value)
        return events[-limit:]

    def _export_diagnostics(
        self,
        game_id: str | None,
        agent_id: str | None,
    ) -> Path:
        timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
        output = self.jobs.root / "diagnostics" / f"desktop-diagnostics-{timestamp}.zip"
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "platform": platform.platform(),
            "python": sys.version,
            "desktop_protocol_version": 1,
            "game_id": game_id,
            "agent_id": agent_id,
        }
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            if game_id:
                workspace = load_desktop_workspace(game_id, agent_id, self.root)
                archive.writestr(
                    "workspace.json",
                    workspace.model_dump_json(indent=2) + "\n",
                )
            for path in [
                self.log_path,
                self.log_path.with_name(f"{self.log_path.name}.1"),
                self.log_path.with_name(f"{self.log_path.name}.2"),
                self.log_path.with_name(f"{self.log_path.name}.3"),
            ]:
                if path.exists():
                    archive.write(path, f"logs/{path.name}")
            runs_root = self.jobs.root / "runs" / "desktop"
            if runs_root.exists():
                recent_runs = sorted(
                    (path for path in runs_root.iterdir() if path.is_dir()),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )[:3]
                for run_dir in recent_runs:
                    for artifact in run_dir.iterdir():
                        if artifact.is_file() and artifact.stat().st_size <= 10 * 1024 * 1024:
                            archive.write(
                                artifact,
                                f"runs/{run_dir.name}/{artifact.name}",
                            )
        append_runtime_event(
            self.log_path,
            "diagnostics_exported",
            source="desktop_backend",
            game_id=game_id,
            agent_id=agent_id,
            output_path=str(output),
        )
        return output

    @staticmethod
    def _context(params: dict[str, Any]) -> tuple[str, str]:
        game_id = str(params.get("game_id") or "").strip()
        agent_id = str(params.get("agent_id") or "").strip()
        if not game_id:
            raise ValueError("game_id is required")
        if not agent_id:
            raise ValueError("agent_id is required")
        return game_id, agent_id

    @staticmethod
    def _error_from_exception(exc: Exception) -> DesktopError:
        if isinstance(exc, UnsupportedDesktopProtocolVersionError):
            return DesktopError(code="unsupported_version", message=str(exc))
        if isinstance(exc, ValidationError):
            return DesktopError(
                code="validation_error",
                message="请求数据校验失败。",
                details={"errors": exc.errors(include_url=False)},
            )
        if isinstance(exc, (StoreRevisionConflictError, StoreLockTimeoutError)):
            return DesktopError(
                code="storage_conflict",
                message=str(exc),
                retryable=True,
            )
        if isinstance(exc, (KeyError, FileNotFoundError)):
            return DesktopError(code="not_found", message=str(exc))
        if isinstance(exc, LookupError):
            return DesktopError(code="unknown_method", message=str(exc))
        if isinstance(exc, ValueError):
            return DesktopError(code="invalid_operation", message=str(exc))
        return DesktopError(
            code="internal_error",
            message=f"{type(exc).__name__}: {exc}",
        )

    def _log(
        self,
        event: str,
        *,
        request: DesktopRequest,
        elapsed: float,
        **fields: Any,
    ) -> None:
        append_runtime_event(
            self.log_path,
            event,
            source="desktop_backend",
            request_id=request.request_id,
            method=request.method,
            elapsed_seconds=round(elapsed, 6),
            **fields,
        )
