# 多代理人与全局库存数据层设计

## Summary

目标是在不改变 Action EV 计算公式、推荐排序、默认 engine、horizon 行为的前提下，新增“多代理人上下文 + 每代理人独立当前装备 + 游戏全局库存”的数据层。Agent 只负责展示与身份，CharacterPreset 继续负责计算模板、词条优先级和套装方案。

第一版只落数据结构、读写 helper、旧数据兼容和 dry-run/apply 迁移报告；不实现多代理人 UI，也不自动迁移或删除旧文件。

## Schema

### AgentMetadata

静态展示元数据，建议放在 `configs/agents/{game}.yaml`。

```yaml
game: zzz
agents:
  - agent_id: zzz_qingyi
    name: 青衣
    rarity: S
    attribute: 电
    specialty: 击破
    faction: 治安局·刑侦特勤组
    level_cap: 60
    portrait_path: assets/zzz/agents/zzz_qingyi/portrait.png
    card_path: assets/zzz/agents/zzz_qingyi/card.png
    character_preset_id: zzz_qingyi_default
```

规则：

- `agent_id` 是代理人身份主键。
- `character_preset_id` 只做“代理人 -> 计算模板”的引用，不把 Agent 与 CharacterPreset 合并。
- 图片只允许本地路径；不联网下载，不内置来源不明资源。
- metadata 缺失时生成 fallback agent：`agent_id=fallback_{character_preset_id}`，名称取 `CharacterPreset.name`，稀有度/属性/类型显示 `未知`，图片为空并由 UI 使用默认占位。

### AgentUserState

用户侧代理人状态，建议放在 `user_data/agents/{game}.yaml`。

```yaml
game: zzz
agents:
  zzz_qingyi:
    owned: true
    level: 60
    favorite: false
    active_loadout_id: default
    notes: ""
```

规则：

- 只存用户状态，不存计算规则。
- 没有 user state 时默认 `owned=false`、`level=null`、`active_loadout_id=default`。

### InventoryItem

游戏全局库存，建议放在 `user_data/inventory/{game}/global.yaml`。

```yaml
game: zzz
schema_version: 1
items:
  - item_id: inv_3f5a0c9e8d41
    piece:
      position: 1
      set_name: 云岿如我
      main_stat: 生命值
      level: 15
      initial_substat_count: 4
      substats:
        - stat: 暴击率
          rolls: 0
        - stat: 暴击伤害
          rolls: 0
    locked: false
    created_at: "2026-07-04T00:00:00+08:00"
    updated_at: "2026-07-04T00:00:00+08:00"
    migrated_from:
      kind: legacy_inventory
      path: user_data/inventory/zzz/zzz_starlight_billy.yaml
      row: 23
```

规则：

- `item_id` 必须稳定持久化；新建装备用 `inv_{uuid4hex[:12]}`。
- dry-run 迁移里的预览 id 用 `mig_{sha1(source_path + row_index + normalized_piece)[:12]}`，apply 时写入同一 id。
- 装备是否被代理人穿戴不写在 InventoryItem 内，统一由 AgentLoadout 引用推导，避免双写冲突。

### AgentLoadout

每代理人的当前装备，第一版只引用 `item_id`，不复制 GearPiece。建议放在 `user_data/loadouts/{game}/{agent_id}.yaml`。

```yaml
game: zzz
agent_id: zzz_qingyi
schema_version: 1
loadouts:
  - loadout_id: default
    label: 当前装备
    slot_items:
      "1": inv_3f5a0c9e8d41
      "2": inv_91b6e2a47c10
      "3": null
      "4": null
      "5": null
      "6": null
    updated_at: "2026-07-04T00:00:00+08:00"
```

规则：

- `slot_items` key 使用 `position_key`。
- 空槽位为 `null`。
- 运行 Action EV 前，将当前 agent 的 loadout item_id 展开为 `GearPiece`，库存读取 global items 中未被当前 loadout 使用的项；公式与排序不变。

## 旧数据兼容方案

旧文件不自动删除、不强迁移：

- 保留读取旧 `user_data/inventory/{game}/{character}.yaml`。
- 若 `user_data/inventory/{game}/global.yaml` 不存在，当前角色仍可用旧库存作为兼容视图。
- 若 global 已存在，旧库存不自动混入，必须通过 dry-run/apply 迁移。
- 旧 `user_data/current_gear/{game}/{character}.yaml` 继续可读；迁移到 AgentLoadout 时，为每件当前装备寻找或创建 InventoryItem，再写 loadout item_id 引用。
- 迁移 apply 前写备份到 `user_data/backups/multi_agent_migration/{timestamp}/`，但不删除旧文件。

## Dry-Run Migration 流程

新增只读报告入口，输出 Markdown/JSON，不改文件：

1. 扫描旧库存：`user_data/inventory/{game}/*.yaml`。
2. 扫描旧当前装备：`user_data/current_gear/{game}/*.yaml`。
3. 根据 `character_preset_id` 找 AgentMetadata；找不到则使用 fallback agent。
4. 标准化每件 GearPiece，计算 exact signature 和 unordered signature。
5. 生成迁移预览：将创建多少 InventoryItem、多少 AgentLoadout、完全重复组、疑似重复组、缺 metadata、缺图、缺 CharacterPreset、loadout 引用缺失或槽位冲突。
6. apply 只在用户显式触发时执行，写入 global inventory 和 loadouts，并保留旧文件。

## 冲突检测规则

- `item_id` 重复：阻断 apply。
- 同一 AgentLoadout 同槽位多件：阻断 apply。
- loadout 引用不存在的 `item_id`：阻断计算，UI 后续显示缺失项。
- 同一 `item_id` 被多个 agent loadout 引用：允许，但报告为“共享装备冲突”，UI 后续明确标记。
- exact signature 重复：dry-run 报告建议合并，apply 默认全部保留，除非用户选择去重。
- unordered signature 重复：只提示，不默认去重。
- metadata 缺失、图片缺失：不阻断，使用 fallback。
- CharacterPreset 缺失：该 Agent 可展示，但计算按钮禁用并提示缺模板。

## UI 阶段拆分

### Phase 1：数据层与迁移报告

- 新增 schemas、load/save helper、dry-run migration report。
- 不改主 UI，不改 Action EV。
- 提供测试覆盖和报告样例。

### Phase 2：最小代理人上下文

- 顶部增加当前代理人卡片和切换入口。
- 切换代理人后加载对应 AgentLoadout，库存读取 global inventory。
- 当前装备 6 槽显示引用的库存 item。
- 结果页切换代理人后清空，提示重新计算。

### Phase 3：代理人卡片选择器

- 卡片网格展示大图、稀有度、名称、等级、属性、类型、阵营。
- 支持搜索、稀有度/属性/类型/阵营筛选。
- 缺图使用默认卡片。

### Phase 4：库存归属可视化

- 库存卡片显示“未装备”或“已被某代理人使用”。
- 装备到当前代理人时更新 AgentLoadout 引用，不复制 GearPiece。
- 处理同一 item 被多个代理人引用的提示。

## 第一版不做的事项

- 不实现多代理人 UI。
- 不联网下载代理人图片。
- 不引入来源不明图片资源。
- 不改变 Action EV 公式、排序、默认 engine、horizon 行为。
- 不把 AgentMetadata 和 CharacterPreset 合并。
- 不自动删除旧库存/旧当前装备文件。
- 不默认去重。
- 不做云同步、多设备同步。
- 不做多套计算模板自动选择；一个 Agent 第一版只引用一个默认 CharacterPreset。
- 不做装备强化历史、来源追踪的复杂编辑。

## 测试清单

- Schema：AgentMetadata、AgentUserState、InventoryItem、AgentLoadout 可正常校验和序列化。
- Fallback：缺 metadata、缺图、缺 user state 不崩溃。
- Inventory：新建 item 自动生成稳定 item_id；保存再读取 item_id 不变。
- Loadout：只保存 item_id，不复制 GearPiece。
- Legacy：无 global inventory 时旧 `inventory/{game}/{character}.yaml` 仍可读取。
- Dry-run：运行后不改任何文件；输入文件 hash 不变。
- Migration apply：生成 global inventory、agent loadout、backup；旧文件仍存在。
- Conflict：重复 item_id、缺失 item_id、同槽位冲突能被报告。
- Duplicate：exact duplicate 和 unordered duplicate 分别被识别。
- EV invariance：同一当前装备和库存展开后，Action EV 数值、排序、推荐行与迁移前一致。
- UI 后续：切换代理人后当前装备、库存归属、计算上下文正确刷新。
