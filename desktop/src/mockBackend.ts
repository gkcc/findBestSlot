import type {
  CharacterPreset,
  DesktopResponse,
  GearPiece,
  InventoryItem,
  Workspace,
} from "./types";

interface RawRequest {
  schema_version: 1;
  request_id: string;
  method: string;
  params: Record<string, unknown>;
}

const billyTemplate: CharacterPreset = {
  id: "zzz_starlight_billy",
  game: "zzz",
  name: "星徽·比利目标",
  target_set: "沧浪行歌",
  effective_substats: { 攻击力百分比: 1, 暴击率: 1, 暴击伤害: 1 },
  substat_priority: {
    core: ["攻击力百分比", "暴击率", "暴击伤害"],
    usable: ["穿透值"],
  },
  preferred_main_stats: {
    "4": ["暴击率", "暴击伤害"],
    "5": ["物理伤害加成", "攻击力百分比"],
    "6": ["攻击力百分比"],
  },
  set_plans: [
    {
      id: "four_plus_two",
      name: "4+2",
      requirements: [
        { set_name: "沧浪行歌", pieces: 4 },
        { set_name: "折枝剑歌", pieces: 2 },
      ],
    },
  ],
  default_set_plan: "four_plus_two",
  target_effective_rolls: 6,
};

const positions = Array.from({ length: 6 }, (_, index) => {
  const id = String(index + 1);
  const variable = index >= 3;
  return {
    id,
    name: `${id} 号位`,
    main_stats: variable
      ? ["攻击力百分比", "生命值百分比", "防御力百分比", "暴击率", "暴击伤害"]
      : [index === 0 ? "生命值" : index === 1 ? "攻击力" : "防御力"],
    set_names: ["沧浪行歌", "折枝剑歌", "啄木鸟电音"],
  };
});

const item = (id: string, position: number, setName: string, mainStat: string): InventoryItem => ({
  item_id: id,
  status: "backpack",
  referenced_by_snapshots: 0,
  piece: {
    position,
    set_name: setName,
    main_stat: mainStat,
    level: 15,
    locked: false,
    initial_substat_count: 4,
    substats: [
      { stat: "攻击力百分比", rolls: 2 },
      { stat: "暴击率", rolls: 2 },
    ],
  },
});

const initialInventory: InventoryItem[] = [
  item("inv_demo_001", 1, "沧浪行歌", "生命值"),
  item("inv_demo_002", 2, "折枝剑歌", "攻击力"),
  item("inv_demo_003", 5, "沧浪行歌", "攻击力百分比"),
];
let inventory: InventoryItem[] = structuredClone(initialInventory);

const agents = [
  {
    agent_id: "zzz_ye_shunguang",
    name: "叶瞬光",
    rarity: "S",
    attribute: "物理",
    specialty: "命破",
    faction: "云岿山",
    portrait_path: "assets/zzz/agents/icons/zzz_ye_shunguang.png",
    card_path: "assets/zzz/agents/cards/zzz_ye_shunguang.png",
    configured_target_template_id: "",
  },
  {
    agent_id: "zzz_starlight_billy",
    name: "星徽·比利",
    rarity: "S",
    attribute: "物理",
    specialty: "命破",
    faction: "狡兔屋",
    portrait_path: "assets/zzz/agents/icons/zzz_starlight_billy.png",
    card_path: "assets/zzz/agents/cards/zzz_starlight_billy.png",
    configured_target_template_id: "zzz_starlight_billy",
  },
];

let activeTemplateByAgent: Record<string, CharacterPreset | null> = {
  zzz_ye_shunguang: null,
  zzz_starlight_billy: billyTemplate,
};

const defaultAgentId = "zzz_ye_shunguang";

export function resetMockBackend(): void {
  inventory = structuredClone(initialInventory);
  activeTemplateByAgent = {
    zzz_ye_shunguang: null,
    zzz_starlight_billy: structuredClone(billyTemplate),
  };
}

function workspace(agentId = defaultAgentId): Workspace {
  const template = activeTemplateByAgent[agentId] ?? null;
  const slots = positions.map((position) => {
    const equipped = inventory.find(
      (row) => row.equipped_by?.agent_id === agentId && String(row.piece.position) === position.id,
    );
    return {
      position: position.id,
      position_name: position.name,
      item_id: equipped?.item_id ?? null,
      item: equipped ?? null,
    };
  });
  const complete = slots.every((slot) => Boolean(slot.item_id));
  const computeReason = !template
    ? "当前代理人没有目标模板，请先创建目标模板。"
    : !complete
      ? `当前装备只有 ${slots.filter((slot) => slot.item_id).length}/6 件；补齐后可进行单代理计算。`
      : "";
  return {
    games: [
      { id: "zzz", name: "绝区零", gear_name: "驱动盘" },
      { id: "hsr", name: "崩坏：星穹铁道", gear_name: "遗器" },
    ],
    game_id: "zzz",
    game_name: "绝区零",
    gear_name: "驱动盘",
    sets: ["沧浪行歌", "折枝剑歌", "啄木鸟电音"],
    sub_stats: ["攻击力百分比", "生命值百分比", "防御力百分比", "暴击率", "暴击伤害", "穿透值"],
    max_level: 15,
    level_step: 3,
    positions,
    agents,
    agent_id: agentId,
    target_templates: template
      ? [
          {
            id: template.id,
            name: template.name,
            builtin: !template.id.startsWith("user_"),
            source_agent_id: agentId,
            preferred_main_stats: template.preferred_main_stats,
            target_sets: ["沧浪行歌", "折枝剑歌"],
            priority_stats: template.substat_priority?.core ?? [],
          },
        ]
      : [],
    active_target_template_id: template?.id ?? null,
    active_target_template: template,
    inventory: structuredClone(inventory),
    current_loadout: { loadout_id: "default", label: "当前装备", slots, complete },
    capabilities: {
      inventory_write: { available: true, reason: "" },
      loadout_write: { available: true, reason: "" },
      target_template_write: { available: true, reason: "" },
      best_loadout: { available: Boolean(template && complete), reason: computeReason },
      action_ev: { available: Boolean(template && complete), reason: computeReason },
      portfolio_ev: {
        available: Boolean(template),
        reason: template ? "" : "至少需要一个代理人目标模板。",
      },
    },
    inventory_revision: 1,
    loadout_revision: 1,
    target_selection_revision: 1,
    canonical_inventory: true,
  };
}

function ok<T extends Record<string, unknown>>(requestId: string, data: T): DesktopResponse<T> {
  return { schema_version: 1, request_id: requestId, ok: true, data };
}

export async function mockBackendRequest<T extends Record<string, unknown>>(
  request: RawRequest,
): Promise<DesktopResponse<T>> {
  await new Promise((resolve) => window.setTimeout(resolve, 20));
  const agentId = String(request.params.agent_id || defaultAgentId);
  if (request.method === "workspace.get") {
    return ok(request.request_id, { workspace: workspace(agentId) } as unknown as T);
  }
  if (request.method === "target_template.save") {
    const template = structuredClone(request.params.template) as CharacterPreset;
    template.id = template.id.startsWith("user_") ? template.id : `user_${agentId}_target`;
    activeTemplateByAgent[agentId] = template;
  } else if (request.method === "target_template.delete") {
    activeTemplateByAgent[agentId] = null;
  } else if (request.method === "inventory.create") {
    inventory.push({
      item_id: `inv_demo_${String(inventory.length + 1).padStart(3, "0")}`,
      piece: structuredClone(request.params.piece) as GearPiece,
      status: "backpack",
      referenced_by_snapshots: 0,
    });
  } else if (request.method === "inventory.update") {
    const row = inventory.find((candidate) => candidate.item_id === request.params.item_id);
    if (row) row.piece = structuredClone(request.params.piece) as GearPiece;
  } else if (request.method === "inventory.delete") {
    const index = inventory.findIndex((candidate) => candidate.item_id === request.params.item_id);
    if (index >= 0) inventory.splice(index, 1);
  } else if (request.method === "loadout.equip") {
    const row = inventory.find((candidate) => candidate.item_id === request.params.item_id);
    if (row) {
      const position = String(row.piece.position);
      for (const candidate of inventory) {
        if (
          candidate.equipped_by?.agent_id === agentId &&
          String(candidate.piece.position) === position
        ) {
          candidate.status = "backpack";
          candidate.equipped_by = null;
        }
      }
      row.status = "equipped";
      row.equipped_by = {
        agent_id: agentId,
        agent_name: agents.find((agent) => agent.agent_id === agentId)?.name ?? agentId,
        loadout_id: "default",
        position,
      };
    }
  } else if (request.method === "loadout.unequip") {
    const row = inventory.find(
      (candidate) =>
        candidate.equipped_by?.agent_id === agentId &&
        candidate.equipped_by.position === String(request.params.position),
    );
    if (row) {
      row.status = "backpack";
      row.equipped_by = null;
    }
  }
  return ok(request.request_id, { workspace: workspace(agentId) } as unknown as T);
}
