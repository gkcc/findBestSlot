import type {
  GearPiece,
  InventoryFilters,
  InventoryItem,
  Workspace,
} from "./types";

export const EMPTY_FILTERS: InventoryFilters = {
  sets: [],
  positions: [],
  mainStats: [],
  targetMainOnly: false,
  ownership: "all",
};

export function targetMainStats(workspace: Workspace, position: string | number): string[] {
  return workspace.active_target_template?.preferred_main_stats[String(position)] ?? [];
}

export function filterInventory(
  workspace: Workspace,
  filters: InventoryFilters,
): InventoryItem[] {
  return workspace.inventory.filter((item) => {
    const position = String(item.piece.position);
    if (filters.sets.length && !filters.sets.includes(item.piece.set_name)) return false;
    if (filters.positions.length && !filters.positions.includes(position)) return false;
    if (filters.mainStats.length && !filters.mainStats.includes(item.piece.main_stat)) return false;
    if (filters.ownership !== "all" && item.status !== filters.ownership) return false;
    if (
      filters.targetMainOnly &&
      !targetMainStats(workspace, position).includes(item.piece.main_stat)
    ) {
      return false;
    }
    return true;
  });
}

function firstValid(selected: string[], allowed: string[], fallback: string): string {
  return selected.find((value) => allowed.includes(value)) ?? fallback;
}

export function newPieceDefaults(
  workspace: Workspace,
  filters: InventoryFilters,
): GearPiece {
  const position =
    filters.positions
      .map((selected) => workspace.positions.find((candidate) => candidate.id === selected))
      .find((candidate) => candidate !== undefined) ?? workspace.positions[0];
  const setName = firstValid(filters.sets, position.set_names, position.set_names[0]);
  const preferredMain = targetMainStats(workspace, position.id).find((stat) =>
    position.main_stats.includes(stat),
  );
  const mainStat = firstValid(
    filters.mainStats,
    position.main_stats,
    preferredMain ?? position.main_stats[0],
  );
  return {
    position: position.id,
    set_name: setName,
    main_stat: mainStat,
    level: 0,
    substats: [],
    locked: false,
    initial_substat_count: 4,
    revealed_next_substat: null,
  };
}

export function positionLabel(workspace: Workspace, position: string | number): string {
  return (
    workspace.positions.find((candidate) => candidate.id === String(position))?.name ??
    String(position)
  );
}

export function pieceSummary(item: InventoryItem): string {
  const usefulRolls = item.piece.substats.reduce((total, line) => total + line.rolls, 0);
  return `${item.piece.set_name} · ${item.piece.main_stat} · +${item.piece.level} · ${usefulRolls} 次强化`;
}
