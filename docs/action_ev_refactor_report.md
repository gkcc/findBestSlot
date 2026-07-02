# Action EV 重构报告

## 变更摘要

本次重构集中在 `src/gear_optimizer/position_ev.py`：

- 用精确 DP 替换 `_candidate_combos` / `_best_combo_rows` 原先的按位置笛卡尔积枚举。
- value-only 路径只保存 count-state 下的最优 value，不回溯组合。
- `return_combo=True` 路径使用 DP backpointer 回溯组合，供 `_set_plan_frontier_action_specs` 使用。
- 拆分可装备 loadout candidates 与 upgrade sources：未满级胚子默认只作为“强化库存胚子”action source，不进入 `Best(I)`。
- 修复 locked 语义：locked 位置只允许 locked 当前件作为该位置 loadout 候选，背包件和新 outcome 不能替换它。
- lookahead 不再使用 frontier-only 排他剪枝。当前 `dominant_generation` 已覆盖 frontier 生成的 requirement/position action，因此 hot path 直接使用 dominant action 空间，避免漏同 requirement 内部提质路径。
- best_loadout 缓存键从 JSON 字符串改为 tuple，并纳入 locked、未满级 piece signature 等语义字段。
- 增加聚合 outcome 缓存，复用同一库存 + 同一 action 的 outcome 分布。

## 正确性说明

### best_loadout DP

DP 状态：

```text
(position_index, set_count_state) -> best value_vector
```

每个位置必须选择 1 件。每选一件：

- 将该件 `_row_value` 加到 value_vector；
- 若该件套装在当前方案相关套装里，则更新 count-state；
- count-state 用于判断 4+2 / 2+2+2 等方案是否满足。

最终优先选择满足套装方案的状态；若无满足状态，保留旧语义，回退到所有状态中 value 最大者。

### 未满级胚子

未满级 `GearPiece` 仍保留在 inventory 中，但默认只会被 `_upgrade_action_specs` 作为“强化库存胚子”来源使用。除非显式设置 `_allow_unfinished_loadout=True`，否则不会进入 `Best(I)`。

### locked 位置

如果某位置存在 locked row，则该位置的 loadout options 只取 locked row。这样：

- 背包成品不能替换 locked 当前件；
- 新 outcome 不能替换 locked 当前件；
- 落在 locked 位置的候选胚子仍可生成强化 action，但强化后的 value 不会提升当前 loadout。

### frontier 与 dominant

旧逻辑在 lookahead 内部使用 `frontier_specs or dominant_generation_specs`，这会在 frontier 非空时排除同 requirement 内部提质路径。

当前逻辑不再排他使用 frontier。现阶段 `dominant_generation` 已枚举每个 requirement 下每个位置的主导 action，因此覆盖 frontier 生成的 action；hot path 使用 dominant，frontier 函数保留用于审计和测试。

## 回归测试

新增/调整测试在 `tests/test_position_ev.py`：

- DP best_loadout 与旧笛卡尔积参考实现在小库存下结果一致。
- frontier-only 会漏掉同 requirement 内部提质路径；lookahead action space 保留 dominant 以覆盖该路径。
- 未满级胚子不进入 `Best(I)`，但仍会生成“强化库存胚子”action。
- locked 位置不可被背包成品或强化后的候选替换。

验证命令：

```powershell
python -m pytest tests\test_position_ev.py -q
python -m pytest -q
```

结果：

```text
18 passed
223 passed, 16 deselected
```

## 示例盘面对比

测试对象：`examples/zzz_billy_current.yaml`，角色 `zzz_starlight_billy`，概率模型 `zzz_default`。

### horizon=1

重构前：

```text
2.667s
最佳：固定位置 / 折枝剑歌 / 6号位
质量提升 0.183，有效提升 0.183，质量/母盘 0.0306
```

重构后：

```text
2.496s
最佳：固定位置 / 折枝剑歌 / 6号位
质量提升 0.183，有效提升 0.183，质量/母盘 0.0306
```

结论未大幅变化。

### horizon=2

重构前 frontier-only 口径：

```text
57.412s
DP states: 1397
最佳：固定位置 / 折枝剑歌 / 6号位
质量提升 2.509，有效提升 2.509，质量/母盘 0.4182
```

重构后完整 dominant 口径：

```text
62.551s
DP states: 1397
最佳：随机位置 / 折枝剑歌 / 1-6随机
质量提升 0.168，有效提升 0.168，质量/母盘 0.0561
```

结论变化原因：

- 旧 horizon=2 内部使用 frontier-only 排他剪枝，会漏掉同 requirement 内部提质路径。
- 新逻辑使用完整 dominant action 空间后，期权价值计算口径更保守，固定 6 号位不再被旧剪枝路径高估。
- 同时未满级胚子不再污染 `Best(I)`，locked 位置也不会被新 outcome 替换。

性能说明：

- 相比旧的 frontier-only 错误口径，完整 action 空间会多算一批后续 action，因此示例 horizon=2 总时间未下降。
- 在修复 frontier 语义后的未优化版本中，horizon=2 曾测得约 130.320s；加入 tuple cache key、row value cache、outcome 聚合缓存和 DP 快路径后降至约 62.551s。
- 因此，本次性能优化主要抵消了正确性修复带来的额外 action 空间成本；没有对旧错误口径形成净加速。

## 后续优化建议

- 给 lookahead action 增加可证明安全的 dominance pruning，而不是 frontier-only 排他剪枝。
- 对 `Best(I)` 的 count-state DP 增加 Pareto frontier 压缩，减少同 count-state 内被严格支配的 value。
- 将 action outcome 分布缓存设为 LRU，避免长时间交互时内存增长。
- 为 `_expected_action_value` 增加可证明上界，在不可能超过当前最优 action 时提前停止。
