# 当前装备调律计算逻辑说明（给 GPT 审核）

本文档总结当前项目的理论期望计算路径，目标是让外部 GPT 复核是否有进一步剪枝、缓存或数学化优化空间。

## 1. 核心目标

项目不是伤害模拟器，而是装备/驱动盘调律决策工具。当前重点回答：

- 当前身上 6 件里哪件最弱。
- 新胚子是否值得继续强化。
- 在当前套装方案约束下，随机位置、固定位置、固定主属性、固定副属性、强化库存胚子这些 action 的理论期望收益。
- horizon=2 时，本次 action 后再接一次最优 action 的期权价值。

所有 Action EV 当前都是完整概率分布枚举的理论期望，不使用 Monte Carlo 抽样。

## 2. 主要输入

代码入口主要在 `src/gear_optimizer/position_ev.py`、`src/gear_optimizer/scoring.py` 和 `src/gear_optimizer/models.py`。

### 游戏规则 `GameRules`

包含：

- 位置列表，例如 ZZZ 的 1-6 号位。
- 每个位置可出现的主属性。
- 副属性池和副属性抽取概率。
- 强化规则，例如最高等级、强化事件等级、初始 3 词条何时补第 4 条。
- 主属性概率。

### 角色目标 `CharacterPreset`

包含：

- 当前目标套装方案，例如 4+2、2+2+2 或不限套装。
- 各位置偏好的主属性。
- 副属性优先级向量：`core` 和 `usable` 是有序列表，不再要求用户维护小数权重。
- 评分线和评级线。

### 概率模型 `ProbabilityModel`

包含：

- 目标套装概率。ZZZ 默认按指定套装调律口径处理，目标套装概率为 100%。
- 初始 3/4 副属性概率。
- 资源成本：随机位置母盘、固定位置母盘、固定主属性校音器、固定副属性共鸣核。

### 库存

库存由两部分合并：

- “方案模板”工作区的身上 6 件。
- “库存”工作区“背包库存”里维护的未装备成品/胚子。

勾选“把当前候选胚子纳入库存 EV”时，候选胚子也会作为库存参与计算。

## 3. 单件装备评分

单件评分由 `score_piece`、`substat_quality_vector` 和 `score_quality_sort_key` 处理。

当前质量向量不是单一小数分，而是按优先级展开的元组。以配置了 `core` 和 `usable` 的角色为例，单件副属性向量大致为：

```text
(
  core_total,
  core_stat_1_count,
  core_stat_2_count,
  ...,
  usable_total,
  usable_stat_1_count,
  usable_stat_2_count,
  ...
)
```

套装组合最终比较时会再加上：

```text
(
  main_hits,
  *summed_quality_vector,
  effective_rolls,
  quality_score
)
```

其中：

- `main_hits` 是主属性命中角色目标的位置数量。
- `summed_quality_vector` 是 6 件装备的优先级向量逐位相加。
- `effective_rolls` 是有效词条总数。
- `quality_score` 是质量分总和。

比较方式是 Python 元组字典序比较，因此前面的维度优先级更高。也就是说，主属性命中、核心词条合计、核心词条内部顺位等，会按向量位置依次决定排序。

## 4. 当前最优配装 `best_loadout`

核心函数：

- `_normalise_inventory_rows`
- `_candidate_combos`
- `_set_plan_satisfied`
- `_best_combo_rows`
- `_cached_best_combo_value`

流程：

1. 把所有 `GearPiece` 转成库存 row，每个 row 包含位置、套装、主属性是否命中、有效词条、质量分、质量向量。
2. 库存归一化：未满级胚子默认只作为“强化库存胚子”action source，不进入 `Best(I)`；已满级成品按 `(位置, 套装)` 保留贡献最高的一件。
3. 如果某个位置有 locked 当前件，该位置的 loadout options 只保留 locked 件，背包/新 outcome 不能替换它。
4. best_loadout 现在用精确 DP，不再生成完整笛卡尔积。DP 每一步处理一个位置，每个状态记录套装 count-state 下的最优 value_vector。
5. 最终优先选择满足当前套装方案的状态，例如 4+2 或 2+2+2；如果没有任何状态满足套装方案，则退回所有状态中的最优值，保持旧 fallback 语义。
6. value-only 路径只保存 value，不回溯组合；`return_combo=True` 路径用 backpointer 回溯组合，供 `_set_plan_frontier_action_specs` 使用。
7. best_loadout 结果按库存 signature 缓存，signature 包含 locked、未满级 piece 状态和显式允许未满级参与 loadout 的标记。

当前复杂度主要来自 count-state 数量和每个位置候选数量。对于 4+2 / 2+2+2 这种小套装状态，DP 避免了完整位置笛卡尔积。

## 5. Action 空间

action 用 `ActionSpec` 表示，主要有：

- `随机位置`
- `固定位置`
- `固定位置 + 固定主属性`
- `固定位置 + 固定主属性 + 固定副属性`
- `强化库存胚子`

顶层策略表 `position_strategy_efficiency_rows` 当前使用 `_generation_action_specs` 枚举较完整的 action 空间，再附加 `_upgrade_action_specs`。

horizon 递归内部使用 `_lookahead_action_specs`。当前 hot path 使用 `_dominant_generation_action_specs`，因为它已覆盖现有 frontier 会生成的 requirement/position action；不再使用 frontier-only 排他剪枝，避免漏掉同 requirement 内部提质路径。

## 6. 已有套装可行性剪枝

核心函数是 `_set_plan_frontier_action_specs`。

当前思路：

1. 先求当前库存下的 `best_combo`。
2. 尝试把 best_combo 的每个位置分配到套装方案的 requirement 上，例如 4 件套 requirement 和 2 件套 requirement。
3. 如果当前 combo 已能分配：
   - 对库存中未被当前 best_combo 使用的装备，检查它属于哪个套装 requirement。
   - 如果这个库存件能把某个位置迁移到另一个 requirement，就针对被挤出的位置生成互补 requirement 的 action。
   - 例如当前 1/3 是 2 件套，2/4/5/6 是 4 件套，如果考虑新增 1 号位 4 件套，则后续更有意义的是去 2/4/5/6 中找 2 件套补位，而不是继续无差别找 4 件套。
4. 如果当前 combo 无法分配，就按当前缺口生成补缺 requirement 的 action，并跳过已经是目标套装的位置。
5. 对生成的 action 去重。

这是一种启发式 frontier 分析。它不再作为 horizon 递归的排他 action 空间，因为 frontier-only 会漏掉同 requirement 内部提质路径。

## 7. 新盘概率分布

核心函数：

- `_candidate_distribution_for_action`
- `_fresh_candidate_row_distribution`
- `_initial_roll_states`
- `_advance_roll_states`

一个新盘 action 的概率分布按以下维度枚举：

```text
位置概率
* 套装概率
* 主属性概率
* 初始 3/4 词条概率
* 初始副属性组合概率
* 强化事件分配概率
```

固定位置时位置概率为 1；随机位置时均分到所有位置。固定主属性时主属性概率为 1；不固定时使用游戏配置的主属性概率。固定副属性通过 `required_substats` 约束初始副属性状态。

新生成的盘当前按“最终满级成品”的质量向量聚合，也就是说候选分布聚合到：

```text
(quality_score, quality_vector)
```

然后生成库存 row。这样可以减少同分状态数量，因为 best_loadout 只关心位置、套装、主属性命中、质量向量、有效词条和质量分，不关心具体副属性名称之外的完整文本。

## 8. 强化库存胚子分布

核心函数：

- `_upgrade_action_specs`
- `_upgrade_candidate_row_distribution`
- `_advance_existing_roll_states`

如果库存里存在未满级 `GearPiece`，会生成“强化库存胚子”action。它从当前副属性 roll 状态出发，只枚举剩余强化事件。

与新盘不同，强化库存胚子会保留 `_inventory_id`，结果通过 `_replace_inventory_row` 替换原库存项，而不是新增一件。

## 9. Action EV 与 horizon DP

核心函数：

- `_expected_action_value`
- `lookahead_inventory_value`
- `position_strategy_efficiency_rows`

当前 DP 形式可以写成：

```text
Best(I) = 当前库存 I 下满足套装方案的最优 6 件组合向量

V_0(I) = Best(I)

EV_h(I, a) = Sum_{I'} P(I' | I, a) * V_{h-1}(I')

V_h(I) = max(Best(I), max_a EV_h(I, a))
```

其中 `I'` 是执行 action `a` 后的新库存。`_aggregate_inventory_outcomes` 会先把等价库存 signature 的结果合并概率，减少后续 DP 状态。

`lookahead_inventory_value` 使用 memo：

```text
(horizon, inventory_signature) -> value_vector
```

因此同一库存状态和同一剩余步数不会重复计算。

`position_strategy_efficiency_rows` 对每个顶层 action 计算：

- `immediate_EV`：horizon=1 的收益。
- `horizon_EV`：用户选择 horizon 的收益。
- `option_EV`：horizon 收益相对 immediate 收益的正向差。
- 质量/母盘、有效/母盘、排序向量/母盘。

固定位置类 action 会与同套装随机位置 action 的单位母盘效率比较；只有排序向量效率优于随机时，界面才提示“优于随机，才建议固定”。

## 10. 特殊资源边际 EV

核心函数：`resource_marginal_ev_rows`。

它用于审计校音器和共鸣核的边际收益，不直接作为普通攻略结论的必要输入。

计算方式：

- 校音器边际：比较 `固定位置 + 固定主属性` 与 `固定位置，不固定主属性`。
- 共鸣核边际：比较 `固定位置 + 固定主属性 + 固定副属性` 与 `固定位置 + 固定主属性`。
- 同时估算为了达到同等有效提升/质量提升能省多少母盘。

这张表较重，当前 UI 默认不自动计算，需要用户勾选。

## 11. 缓存与进度反馈

已有缓存：

- `_BEST_COMBO_VALUE_CACHE`：缓存 best_loadout value。
- `_ACTION_EV_ROWS_CACHE`：缓存 action EV 表。
- `_RESOURCE_MARGINAL_EV_ROWS_CACHE`：缓存特殊资源边际 EV 表。
- `lookahead_inventory_value` 内部 memo：缓存 DP 状态。
- `quality_cache`：缓存新盘在某个主属性和锁副属性条件下的质量分布。

进度反馈：

- `position_strategy_efficiency_rows` 和 `resource_marginal_ev_rows` 接收 `progress_callback`。
- 底层 `_expected_action_value` 和 `lookahead_inventory_value` 会发出 action、outcome、state、memo hit 等事件。
- PySide6 UI 用这些事件显示进度条、当前 action、DP 状态数和缓存命中数。

UI 为避免误以为卡死：

- 库存维护是静态台账，添加、删除、编辑库存不会自动开始 Action EV。
- 用户点击“计算当前最优搭配”后才从当前装备 + 背包库存中求 Best(I)。
- 用户点击“计算调律建议”后才运行 Action EV；horizon=1 和 horizon=2 都遵守这个显式按钮。
- 若勾选“计算特殊资源全局边际 EV 详情”，它会随下一次“计算调律建议”一起运行。

## 12. 当前可能的优化讨论点

以下问题适合让 GPT 重点审：

1. `best_loadout` 是否能从“按位置笛卡尔积 + 套装过滤”改成动态规划或分支定界。
2. `_set_plan_frontier_action_specs` 的 4+2 / 2+2+2 剪枝是否完备，是否会剪掉某些 horizon>2 下有价值的迁移路径。
3. 顶层 `position_strategy_efficiency_rows` 是否也应该使用 frontier action，而不是完整 `_generation_action_specs`。
4. 新盘分布按 `(quality_score, quality_vector)` 聚合是否足够安全；在什么情况下需要保留更多状态信息。
5. horizon DP 当前用 `V_h(I)=max(Best(I), max_a EV_h(I,a))`，是否符合“每一步都选择最优后续 action”的决策模型。
6. 对 `EV_h(I,a)` 是否可以在 action 层做上界估计，提前跳过必然不可能超过当前最优的 action。
7. 库存归一化按 `(位置, 套装)` 只保留满级成品最高贡献一件，是否在所有套装迁移场景下都安全。
8. 固定副属性 action 当前只锁前 1/2 个有效副属性，是否应根据角色优先级、主属性排除、资源预算动态生成更少/更多组合。
9. `target_set_probability * len(set_options)` 合并可接受套装概率并截断到 1.0 的方式是否合理，尤其是可选 2 件套组合很多时。
10. 是否能把 `horizon=2` 的递归期望改写成矩阵/状态转移或批量向量化，减少 Python 层循环。
11. 是否可以为 `_aggregate_inventory_outcomes` 设计更粗但安全的 dominance pruning，例如同位置同套装下被严格支配的库存状态直接删除。
12. 当前元组字典序排序是否符合玩家直觉；是否需要将主属性命中、核心词条、可用词条、质量分的优先级改成可解释的多目标 Pareto 比较。

## 13. 需要外部 GPT 重点判断的正确性问题

请重点检查：

- 当前 frontier 剪枝是否一定不漏掉有正期望的 horizon=2 最优路径。
- 库存归一化“同位置同套装只保留最高贡献成品”是否在 4+2 迁移中严格安全。
- 新盘分布聚合到质量向量是否会影响后续 action 选择。
- `option_EV` 用 horizon 收益减 immediate 收益的正向差，是否是最直观的展示口径。
- 特殊资源边际 EV 是否应该跟主表共用同一套 action frontier，还是单独全量审计更合理。
