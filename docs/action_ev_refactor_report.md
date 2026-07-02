# Action EV 重构报告

## 变更摘要

本次重构集中在 `src/gear_optimizer/position_ev.py`：

- 用精确 DP 替换 `_candidate_combos` / `_best_combo_rows` 原先的按位置笛卡尔积枚举。
- value-only 路径只保存 count-state 下的最优 value，不回溯组合。
- `return_combo=True` 路径使用 DP backpointer 回溯组合，供 `_set_plan_frontier_action_specs` 使用。
- 拆分可装备 loadout candidates 与 upgrade sources：未满级胚子默认只作为“强化库存胚子”action source，不进入 `Best(I)`。
- 修复 locked 来源语义：只有当前装备来源的 locked 件会锁位置；背包件即便带 `locked=True`，也不会把该位置锁死。
- lookahead 不再使用 frontier-only 排他剪枝；当前 action space 显式取 `dominant_generation ∪ set_plan_frontier ∪ upgrade_sources`，避免漏同 requirement 内部提质路径。
- best_loadout 缓存键从 JSON 字符串改为 tuple，并纳入 locked、未满级 piece signature 等语义字段。
- 修复聚合 outcome 缓存：cache miss 调用 `_action_outcome_distribution` 后再 `_aggregate_inventory_outcomes`，`_expected_action_value` 复用该缓存。

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

如果某位置存在来源为当前装备的 locked row，则该位置的 loadout options 只取该 locked row。这样：

- 背包成品不能替换 locked 当前件；
- 新 outcome 不能替换 locked 当前件；
- 落在 locked 位置的候选胚子仍可生成强化 action，但强化后的 value 不会提升当前 loadout。
- 背包件自身的 `locked=True` 仅作为物品标记保留，不会锁住对应位置。

### frontier 与 dominant

旧逻辑在 lookahead 内部使用 `frontier_specs or dominant_generation_specs`，这会在 frontier 非空时排除同 requirement 内部提质路径。

当前逻辑不再排他使用 frontier。lookahead 明确返回 `dominant ∪ frontier ∪ upgrade`。当前 4+2 迁移测试还验证了典型 frontier 生成项是 dominant 的子集，但代码不依赖这个假设。

## 回归测试

新增/调整测试在 `tests/test_position_ev.py`：

- DP best_loadout 与旧笛卡尔积参考实现在小库存下结果一致。
- frontier-only 会漏掉同 requirement 内部提质路径；lookahead action space 保留 dominant 以覆盖该路径。
- 未满级胚子不进入 `Best(I)`，但仍会生成“强化库存胚子”action。
- locked 位置不可被背包成品或强化后的候选替换。
- 背包件 `locked=True` 不会锁位置，只有当前装备来源会锁。
- 聚合 outcome 缓存不递归，二次调用命中缓存，结果与手动 `_aggregate_inventory_outcomes(_action_outcome_distribution(...))` 一致。

验证命令：

```powershell
python -m pytest tests\test_position_ev.py -q
python -m pytest -q
```

结果：

```text
20 passed
225 passed, 16 deselected
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
2.552s
最佳：固定位置 / 折枝剑歌 / 6号位
质量提升 0.183，有效提升 0.183，质量/母盘 0.0306
```

结论未大幅变化。

### horizon=2 ablation

同一示例盘面，horizon=2 对比：

| 口径 | 时间 | DP states | 推荐 action | 质量提升 | 质量/母盘 |
| --- | ---: | ---: | --- | ---: | ---: |
| 旧实现 frontier-only | 57.412s | 1397 | 固定位置 / 折枝剑歌 / 6号位 | 2.509 | 0.4182 |
| 新 best_loadout + frontier-only | 42.478s | 1397 | 固定位置 / 折枝剑歌 / 6号位 | 2.509 | 0.4182 |
| 新 best_loadout + dominant-only | 62.341s | 1397 | 随机位置 / 折枝剑歌 / 1-6 随机 | 0.168 | 0.0561 |
| 新 best_loadout + dominant∪frontier | 61.978s | 1397 | 随机位置 / 折枝剑歌 / 1-6 随机 | 0.168 | 0.0561 |

当前 shipping 口径是 `dominant∪frontier`。该口径下，固定 6 号位并非没有收益：

```text
固定位置 / 折枝剑歌 / 6号位
质量提升 0.331，有效提升 0.331，质量/母盘 0.0551

随机位置 / 折枝剑歌 / 1-6随机
质量提升 0.168，有效提升 0.168，质量/母盘 0.0561
```

结论变化原因：

- `2.509 -> 0.168` 的主因是旧 lookahead 的 `frontier or dominant` 排他策略。新 best_loadout 但保留 frontier-only 时仍得到 2.509，说明这不是 DP 替换、未满级胚子拆分或 locked 修复导致的主变化。
- frontier-only 在 frontier 非空时排除了 dominant action，未来策略空间被切成一条很窄的迁移路径，固定 6 号位的 option value 被抬高。
- `dominant∪frontier` 后，后续状态会在完整主导 action 空间中按现有 `_combo_value` 的 value_vector 规则重新取最优；固定 6 号位仍有 horizon 收益，但按母盘效率略低于随机位置，因此推荐行切换为随机。

性能说明：

- 相比旧的 frontier-only 错误口径，完整 action 空间会多算一批后续 action，因此示例 horizon=2 总时间未下降。
- 在修复 frontier 语义后的未优化版本中，horizon=2 曾测得约 130.320s；加入 tuple cache key、row value cache、outcome 聚合缓存和 DP 快路径后降至约 62s。
- 因此，本次性能优化主要抵消了正确性修复带来的额外 action 空间成本；没有对旧错误口径形成净加速。

## 后续优化建议

- 给 lookahead action 增加可证明安全的 dominance pruning，而不是 frontier-only 排他剪枝。
- 对 `Best(I)` 的 count-state DP 增加 Pareto frontier 压缩，减少同 count-state 内被严格支配的 value。
- 将 action outcome 分布缓存设为 LRU，避免长时间交互时内存增长。
- 为 `_expected_action_value` 增加可证明上界，在不可能超过当前最优 action 时提前停止。
