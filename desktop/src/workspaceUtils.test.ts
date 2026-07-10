import { describe, expect, it } from "vitest";

import type { Workspace } from "./types";
import { filterInventory, newPieceDefaults } from "./workspaceUtils";

function fixture(): Workspace {
  return {
    games: [{ id: "zzz", name: "绝区零", gear_name: "驱动盘" }],
    game_id: "zzz",
    game_name: "绝区零",
    gear_name: "驱动盘",
    sets: ["套装甲", "套装乙"],
    sub_stats: ["暴击率"],
    max_level: 15,
    level_step: 3,
    positions: [
      { id: "1", name: "1号位", main_stats: ["生命值"], set_names: ["套装甲", "套装乙"] },
      {
        id: "5",
        name: "5号位",
        main_stats: ["攻击力百分比", "物理伤害加成"],
        set_names: ["套装甲", "套装乙"],
      },
    ],
    agents: [],
    agent_id: "agent",
    target_templates: [],
    active_target_template_id: "target",
    active_target_template: {
      id: "target",
      game: "zzz",
      name: "目标",
      target_set: "套装甲",
      effective_substats: {},
      preferred_main_stats: { "5": ["物理伤害加成"] },
      set_plans: [],
      target_effective_rolls: 6,
    },
    inventory: [
      {
        item_id: "a",
        status: "backpack",
        referenced_by_snapshots: 0,
        piece: {
          position: "5",
          set_name: "套装甲",
          main_stat: "物理伤害加成",
          level: 0,
          substats: [],
          locked: false,
          initial_substat_count: 4,
        },
      },
      {
        item_id: "b",
        status: "backpack",
        referenced_by_snapshots: 0,
        piece: {
          position: "5",
          set_name: "套装乙",
          main_stat: "攻击力百分比",
          level: 0,
          substats: [],
          locked: false,
          initial_substat_count: 4,
        },
      },
    ],
    current_loadout: { label: "当前装备", slots: [], complete: false },
    capabilities: {},
    inventory_revision: 1,
    loadout_revision: 1,
    target_selection_revision: 1,
    canonical_inventory: true,
  };
}

describe("inventory workspace utilities", () => {
  it("uses the first selected filter values when creating an item", () => {
    const piece = newPieceDefaults(fixture(), {
      sets: ["套装乙", "套装甲"],
      positions: ["5", "1"],
      mainStats: ["攻击力百分比", "物理伤害加成"],
      targetMainOnly: false,
      ownership: "all",
    });

    expect(piece.position).toBe("5");
    expect(piece.set_name).toBe("套装乙");
    expect(piece.main_stat).toBe("攻击力百分比");
  });

  it("defaults to the target main stat and filters non-target mains", () => {
    const workspace = fixture();
    const piece = newPieceDefaults(workspace, {
      sets: [],
      positions: ["5"],
      mainStats: [],
      targetMainOnly: true,
      ownership: "all",
    });
    const rows = filterInventory(workspace, {
      sets: [],
      positions: [],
      mainStats: [],
      targetMainOnly: true,
      ownership: "all",
    });

    expect(piece.main_stat).toBe("物理伤害加成");
    expect(rows.map((row) => row.item_id)).toEqual(["a"]);
  });
});
