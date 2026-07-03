# gacha-gear-optimizer 无人值守连续执行目标

你现在负责继续推进 findBestSlot / gacha-gear-optimizer 的 PySide6 桌面版、Action EV 算法和 horizon=2 可用性。请按下面目标连续执行任务，不要中途停下来等我确认；除非遇到无法恢复的环境错误，否则持续完成下一项、验证、提交。不要自动点击 ChatGPT 页面，不要需要我手动介入。

## 总体目标

把当前 PySide6 桌面版从“能用但 horizon=2 容易像卡死”的工程工具，推进到“精确计算、不假死、可取消、能使用多核、算法状态压缩、界面能体现绝区零驱动盘元素”的可交付版本。

## 最高原则

1. 不做快速预览模式。
2. 不做近似推荐。
3. 不做 Monte Carlo。
4. 不做 top-N action 近似。
5. 不做 partial 推荐。
6. 只保留：
   - horizon=1 精确；
   - horizon=2 精确。
7. horizon=2 可以慢，但不能拖死 UI。
8. horizon=2 必须可取消；取消后不能展示未完成结果作为推荐。
9. 所有性能优化必须严格等价，或者有测试证明结果与旧精确口径完全一致。
10. 每完成一个小阶段就本地运行对应测试，能修就继续修。
11. 每个阶段提交一个 commit，commit message 写清楚做了什么。
12. 不要删除现有核心算法和已有回归测试。
13. 如果某项做不完，写入 `docs/next_steps.md`，然后继续做下一项。
14. 不要为了测试方便污染业务代码；UI/工程层可加 helper，核心算法只加必要参数、缓存、节流、诊断、进程隔离或严格等价优化。
15. 长时间任务优先保证软件不假死、可取消、可恢复，而不是追求一次性算完。

## 背景判断

当前实现已经把 PySide6 UI 和 Action EV 计算放到 QThread，但这只是 UI 线程和计算线程分离，不是真正的 CPU 多核并行。horizon=2 仍然主要是单核 Python 串行计算，并且 progress signal 可能过于频繁。算法层面当前仍偏“库存 list/dict 状态递归枚举”，单盘概率分布和 action transition 没有充分表格化、状态压缩化。

---

## 阶段 A：当前实现复核与残留清理

目标：确认换成 PySide6 后仓库没有旧 app 残留，当前入口清晰。

任务：

1. 搜索并清理旧 Web UI / Streamlit / pywebview 残留：
   - `.streamlit/`
   - `streamlit*.log`
   - `start_app`
   - `serve-streamlit`
   - `webview`
   - Streamlit / pandas / plotly 旧依赖。
2. `.gitignore` 中如果仍有 `.streamlit/` 和 `streamlit*.log`，删除。
3. README 中主推 `gacha-gear-optimizer`、`python desktop_app.py`、`scripts/start_desktop.ps1`。
4. 如果保留 `gacha-gear-optimizer-desktop`，明确标为兼容别名；不要把它作为主入口。
5. `desktop_app.py` 尽量瘦身，只保留启动入口；测试直接覆盖 `gear_optimizer.launcher`。
6. 将 `first_version_*` 这类阶段性命名收敛：
   - 可以先不大改模块名；
   - 但报告文件优先改成 `acceptance_*` / `readiness_*`；
   - README 里不要再把“第一版”作为当前正式产品形态。
7. 复核当前 horizon=2 是否只是 QThread 后台线程，不是真正多进程/多核并行；在报告中写清楚当前并发状态。

验收：

```powershell
python -m gear_optimizer.diagnostics
python desktop_app.py --app-check
python -m pytest tests/test_desktop_app.py -q
```

输出：

- README、pyproject、脚本中不再出现旧 Web UI 入口。
- 生成 `reports/current_concurrency_audit.md`，说明当前线程/进程/并发状态。

---

## 阶段 B：horizon=2 精确计算进程隔离

目标：horizon=2 仍然是完整概率分布精确计算，但不能让 PySide6 主窗口假死。

任务：

1. 新增独立计算进程入口，例如：
   - `python -m gear_optimizer.action_ev_worker`
2. worker 输入使用 JSON 文件或临时 YAML，包含：
   - game_id
   - character_id
   - probability_model_id
   - current_pieces
   - inventory_pieces
   - horizon
   - run_id
   - output_path
   - progress_path
   - error_path
3. worker 输出：
   - 结果 JSON；
   - 进度 JSONL；
   - 错误 traceback JSON；
   - 运行摘要 JSON。
4. PySide6 中 horizon=2 必须用 QProcess 或 subprocess 子进程执行，不再用同进程 QThread 跑精确计算。
5. horizon=1 可以保留当前方式，但如果重构成本不高，也可以统一走 worker。
6. UI 增加“取消计算”按钮：
   - 可以 terminate/kill 子进程；
   - 取消后主窗口保持可操作；
   - 取消后不更新旧推荐；
   - 取消后不展示 partial 推荐；
   - 日志写明“用户取消，未生成新推荐”。
7. 子进程异常时：
   - 主窗口不崩；
   - 结果区不污染；
   - 日志自动展开；
   - 显示 traceback 摘要。
8. 用户选择 horizon=2 时，按钮旁显示说明：
   “horizon=2 为完整概率分布精确计算，可能耗时较长；计算期间可取消。”
   不要弹阻塞确认框，除非当前装备未确认。
9. 子进程 worker 必须支持命令行 smoke：
   - horizon=1 示例输入能输出结果；
   - 故意传错输入能输出错误 JSON 并非 0 退出；
   - progress JSONL 可解析。

验收：

- horizon=2 点下去后主窗口仍可拖动、切 tab、取消。
- 取消后结果区保持旧结果或清空，但不能显示 partial 推荐。
- worker 输入输出测试通过。
- worker 错误路径测试通过。

```powershell
python -m pytest -q
```

README 明确：本工具不做 Monte Carlo，不做近似快速预览，horizon=2 是精确计算。

---

## 阶段 C：progress 节流与可诊断性

目标：减少 UI 被 progress event 淹没，提升“看起来没卡死”的可信度。

任务：

1. worker 进度输出节流：
   - 普通进度最多每 200ms 输出一次；
   - start / done / fail / cancel 事件必须立即输出；
   - action 切换事件必须输出；
   - 不允许因为节流跳过任何 action/outcome 计算。
2. UI 侧进度刷新节流：
   - UI 每 250~500ms 刷一次控件；
   - 收到 progress 后只更新缓存；
   - 定时器统一渲染。
3. 进度信息至少包含：
   - 当前 action；
   - 当前 horizon；
   - 当前 depth；
   - 顶层 action 完成数；
   - 当前 action outcome 完成数；
   - DP states；
   - memo hits；
   - aggregated outcome cache hits/misses；
   - 已用时；
   - 若能估算，再显示预计剩余。
4. 如果 30 秒没有新进度，不要弹框，状态区显示：
   “仍在精确计算，可取消；这不代表程序卡死。”
5. 日志默认折叠，失败/取消时自动展开。
6. 进度条不得回退；如果动态发现总任务增加，展示“计划已扩展，进度条保持不回退”。

验收：

- 新增 progress throttle 单元测试。
- horizon=2 运行时 UI 不被高频 signal 打爆。
- 取消、失败、完成三类状态显示清晰。

```powershell
python -m pytest tests/test_desktop_app.py -q
```

---

## 阶段 D：单盘分布数学化预计算

目标：把新盘最终质量分布从 action 递归中剥离出来，做成可复用的确定性分布表。

任务：

1. 新增单盘分布预计算模块，例如：
   - `gear_optimizer.piece_distribution`
2. 对每个角色目标预计算：
   - `position`
   - `main_stat`
   - `required_substats`

   到：

   - `{quality_vector: probability}`
   - 或 `{candidate_contribution_key: probability}`
3. 需要覆盖：
   - 初始 3 词条；
   - 初始 4 词条；
   - 初始 3 词条补第 4 条；
   - 强化 4 次 / 5 次；
   - 主属性排除副属性；
   - 固定副属性 required_substats；
   - core / usable 优先级向量。
4. 4/5/6 号位不固定主属性时，由主属性概率混合已有主属性分布；固定主属性时主属性概率为 1。
5. 1/2/3 号位主属性固定，仍通过同一个表查分布。
6. 随机位置 action 应实现为固定位置分布的概率混合；ZZZ 下每个位置权重 1/6。
7. 不要在 horizon=2 递归里重复枚举初始词条和强化事件。
8. 保留旧实现作为测试参考，至少在测试中对比分布一致。

验收：

- 新增测试：
   - 预计算分布与旧 `_fresh_candidate_row_distribution` 在多个 position/main/required_substats 下完全一致；
   - 概率质量和为 1；
   - 1/2/3 固定主属性正确；
   - 4/5/6 主属性概率混合正确；
   - required_substats 不合法时分布为空或概率为 0。

```powershell
python -m pytest tests/test_position_ev.py -q
```

---

## 阶段 E：压缩库存状态 EvState

目标：把 Action EV 递归状态从完整 inventory list/dict 压缩成最小充分状态。

任务：

1. 新增 `EvState` 或等价 tuple 状态。
2. 状态至少包含：
   - 每个 `(position, set_name)` 当前最高 contribution；
   - 当前装备 locked position 约束；
   - 未满级胚子 upgrade sources；
   - 必要的 source/current_count 信息；
   - active set plan 相关信息。
3. 满级成品压缩规则：
   - 同位置同套装只保留 contribution 最高的成品；
   - 必须保留 locked 当前装备约束；
   - 背包 locked 不得锁位置；
   - 未满级胚子默认不进入 Best(I)，只作为 upgrade action source。
4. 新盘 outcome 转移：
   - 若 candidate 不优于当前 `(position,set)`，直接转移到 same_state；
   - 若 candidate 优于当前 `(position,set)`，生成替换后的 next_state；
   - 大量 outcome 必须合并到相同 next_state。
5. 强化库存胚子转移：
   - 仍基于该胚子的剩余强化分布；
   - 强化完成后替换该 upgrade source；
   - 如果满级结果不优于当前 best_by_position_set，则合并到 same_state；
   - 如果落在 locked 当前位置，不应提升 Best(I)。
6. `best_loadout` 基于 EvState 做 count-state DP：
   - 每个位置选 1 件；
   - 套装方案用 count-state 判断 4+2 / 2+2+2；
   - 无满足方案时保留旧 fallback 语义；
   - value-only 路径不回溯组合；
   - 需要展示时可以回溯代表组合。

验收：

- 新增测试：
   - EvState 压缩后 `best_loadout_value` 与旧 inventory 实现一致；
   - 4+2 / 2+2+2 一致；
   - locked 当前装备一致；
   - 背包 locked 不锁位置；
   - 未满级胚子不进入 Best(I)；
   - 新盘不优于当前时 next_state=same_state；
   - 新盘优于当前时 next_state 正确替换。
- 旧接口不破坏 UI。

```powershell
python -m pytest -q
```

---

## 阶段 F：Action EV 状态转移 DP

目标：把 horizon=2 从“递归库存列表枚举”改成“压缩状态转移 DP”，保持结果完全一致。

任务：

1. 新增 transition cache：
   - key: `(state_signature, action_spec, probability_model_key, character_key, game_key)`
   - value: `{next_state_signature: probability}`
2. Action transition 不构造完整库存 list 作为递归状态。
3. Horizon 公式保持：
   - `V0(state) = Best(state)`
   - `Vh(state) = max(Best(state), max_a Σ p * V(h-1, next_state))`
4. memo key 使用：
   - `(horizon, state_signature)`
5. 随机位置 action：
   - 必须实现为固定位置 action 的概率混合；
   - ZZZ 下每个位置权重 1/6；
   - 不允许重复展开相同分布。
6. 固定位置、固定主属性、固定副属性、强化库存胚子都要覆盖。
7. lookahead action space 保持当前精确口径：
   - `dominant_generation ∪ set_plan_frontier ∪ upgrade_sources`
   - 不允许 top-N 近似；
   - 不允许跳过固定副属性；
   - 不允许跳过强化库存胚子。
8. 保留旧 Action EV 路径作为测试参考或 debug fallback，直到新路径测试完全覆盖。
9. 新路径可以通过参数开关启用，例如：
   - `use_state_dp=True`
   - 默认启用前先对示例盘面做一致性报告。
10. 生成对比报告：
   - `reports/action_ev_state_dp_equivalence.md`

验收：

- horizon=1 新旧结果完全一致。
- horizon=2 示例盘面新旧结果完全一致。
- 随机/固定位置/固定主属性/固定副属性/强化库存胚子均覆盖。
- 4+2 / 2+2+2 套装约束覆盖。
- locked 当前装备覆盖。
- 未满级胚子不进入 Best(I) 覆盖。

```powershell
python -m pytest -q
```

生成 `reports/action_ev_state_dp_equivalence.md`，写清楚对比结果。

---

## 阶段 G：严格等价性能优化与 profiling

目标：知道慢在哪里，并只做不改变结果的优化。

允许的优化：

1. 缓存：
   - best_loadout cache；
   - aggregated outcome cache；
   - action distribution cache；
   - quality distribution cache；
   - state transition cache；
   - inventory/state signature cache。
2. LRU：
   - outcome/transition cache 增加最大容量；
   - 避免长时间交互内存无限增长。
3. 减少重复 signature 构造：
   - row/state 内缓存必须带 game/character/plan/probability 语义 key；
   - 不允许跨角色/跨配置复用脏 cache。
4. 减少 progress 事件成本。
5. 对 `Best(state)` 的 count-state DP 做严格 dominance pruning：
   - 只有在同 count-state 下 value_vector 被严格支配时才可删；
   - 必须有单元测试证明与未剪枝结果一致。
6. 对 action 做可证明上界剪枝：
   - 只有在数学上证明该 action 不可能超过当前最优时才可提前跳过；
   - 否则不要做。
7. 不允许：
   - top-N action 近似；
   - 固定时间预算提前停止并返回推荐；
   - 跳过固定副属性 action；
   - 跳过库存强化 action；
   - Monte Carlo；
   - partial 推荐；
   - 快速预览模式。

任务：

1. 新增 profile 工具：

```powershell
python -m gear_optimizer.profile_action_ev --horizon 2 --output reports/action_ev_profile.json
```

2. profile 至少记录：
   - action 数；
   - outcome 数；
   - state 数；
   - transition cache hit/miss；
   - best_loadout cache hit/miss；
   - aggregated outcome cache hit/miss；
   - 每类 action 耗时；
   - top 20 慢 action；
   - 总耗时；
   - 最大缓存规模。
3. 对示例盘面跑 horizon=1 profile。
4. horizon=2 profile 可以标为手动重型命令，不强制 CI 跑。
5. 将 profile 摘要写入 `reports/action_ev_profile_summary.md`。
6. 如果新 state DP 明显快于旧实现，记录速度提升。
7. 如果不明显快，继续定位瓶颈，不要假装完成。

验收：

- profile 命令可跑通。
- horizon=1 profile 不超过合理时间。
- 所有算法回归测试通过。
- 若做了任何剪枝，必须有“剪枝前后结果完全一致”的测试。
- 生成 `reports/action_ev_profile_summary.md`。

---

## 阶段 H：多进程并行计算

目标：在算法状态压缩之后，进一步利用多核 CPU，但不改变精确口径。

前置条件：

- 阶段 B 的子进程隔离已完成；
- 阶段 F 的 state transition DP 已完成或至少 transition cache 结构稳定；
- profile 已确认顶层 action 或 transition 计算适合并行。

任务：

1. 新增可配置并行度：
   - 默认 `workers = max(1, cpu_count - 1)`；
   - UI 可显示当前 workers 数；
   - 环境变量可覆盖，例如 `GEAR_OPTIMIZER_WORKERS=4`。
2. 并行粒度优先选顶层 action：
   - 每个 action 的 EV 可分发到 worker process；
   - worker 返回 action value、耗时、状态统计；
   - 主进程合并结果并排序。
3. 共享数据策略：
   - game/character/probability_model/action/state 使用可序列化结构；
   - 只读预计算分布可在每个 worker 初始化；
   - 不强行共享 Python 对象；
   - 不用线程池做 CPU-bound 计算，使用进程池。
4. 缓存策略：
   - 每个 worker 可有本地 memo；
   - 主进程保留全局 transition/profile 汇总；
   - 如果跨进程共享缓存复杂，先不做共享，避免错。
5. 正确性：
   - 并行结果必须与单进程 state DP 完全一致；
   - 排序和推荐结果一致；
   - 异常 worker 不得污染最终结果。
6. UI：
   - 显示“并行 worker 数”；
   - 支持取消全部 worker；
   - 某个 worker 崩溃时整体失败并保留错误日志；
   - 不展示 partial 推荐。
7. Windows 兼容：
   - 注意 multiprocessing spawn；
   - 所有 worker 入口必须在 `if __name__ == "__main__"` 安全路径下；
   - PyInstaller 打包后仍可运行或至少能给出明确错误。

验收：

- 新增测试：
   - 并行 Action EV 与单进程结果一致；
   - worker 数为 1 时结果一致；
   - worker 数为 2 时结果一致；
   - worker 异常时返回错误，不污染结果。

```powershell
python -m pytest -q
```

生成 `reports/action_ev_parallel_profile.md` 记录单进程与多进程耗时对比。

如果多进程在当前规模下不如单进程，保留开关但默认关闭，并在报告解释。

---

## 阶段 I：绝区零驱动盘素材接入

目标：使用游戏相关图片和元素，让 UI 更像绝区零驱动盘工具，但保持清晰克制。

任务：

1. 新增 asset loader，例如 `src/gear_optimizer/ui_assets.py`：
   - 根据 `game.set_icon_path(set_name)` 读取套装图标；
   - 缓存 QPixmap/QIcon；
   - 文件缺失时回退文字 badge；
   - 打包环境下能正确读取 PyInstaller 内资源。
2. PieceCard 显示 32x32 套装图标。
3. 当前装备 2x3 卡片中：
   - 套装图标；
   - 套装名；
   - 主属性；
   - 副词条；
   - 有效/质量；
   - 锁定状态。
4. 库存摘要表的“套装”列加 icon。
5. 推荐卡显示目标套装 icon。
6. 2/4 件套效果放 tooltip 或详情区：
   - 鼠标悬停套装图标显示 2件套/4件套效果；
   - 或在推荐卡/详情区展示。
7. 不使用大背景图，不做花哨动效，不影响启动速度。
8. diagnostics 保留 set icon 文件检查。

验收：

- 没有图标文件时 UI 不崩。
- 有图标文件时 PieceCard 显示图标。
- PyInstaller add-data 继续包含 assets。

```powershell
python desktop_app.py --app-check
python -m pytest -q
```

---

## 阶段 J：当前装备与库存 UI 继续优化

目标：降低录入和查看成本。

任务：

1. 当前装备页：
   - 保留 2x3 盘位卡片；
   - 点击卡片打开编辑弹窗；
   - 编辑弹窗可以继续使用 GearTable，但要保证不丑、不截断；
   - 卡片上主属性命中与否高亮；
   - 有效/质量按档位上色。
2. 背包库存页：
   - 默认摘要列只显示：
     位置、套装、主属性、等级、有效、质量、锁定、备注/操作；
   - 副词条详情放在详情面板；
   - 增加快捷筛选：
     - 只看目标套装；
     - 只看当前弱位；
     - 只看未满级胚子；
     - 只看可替换当前装备。
3. 录入体验：
   - 添加库存件时默认按当前角色目标生成；
   - 可以一键复制当前选中件；
   - 可以一键清空副词条；
   - 非法副词条及时提示，但不要频繁弹阻塞框。
4. 表格体验：
   - 数值列右对齐；
   - 质量/母盘、有效/母盘固定小数位；
   - 内部字段默认隐藏；
   - 允许导出完整明细。

验收：

- UI smoke 测试通过。
- 不增加核心算法依赖 UI。

```powershell
python -m pytest tests/test_desktop_app.py -q
```

---

## 阶段 K：结果页和推荐卡优化

目标：用户先看结论，再看明细。

任务：

1. 结果页顶部推荐卡展示：
   - 推荐动作；
   - 目标套装；
   - 目标位置；
   - 主属性；
   - 固定副属性；
   - horizon；
   - 质量/母盘；
   - 有效/母盘；
   - 相对随机；
   - 计算口径：精确。
2. Action EV 明细默认只显示前 10 或前 20 条。
3. 提供“显示全部”按钮。
4. 推荐调律后代表搭配单独一个子 Tab。
5. 运行日志单独一个可折叠区域或子 Tab。
6. 内部字段例如 `_sort_vector`、`_representative_loadout_rows` 不直接展示。
7. 对固定位置类 action，解释为什么“优于随机/不如随机”。
8. 对库存强化 action，解释其不消耗母盘，但消耗强化资源，此工具暂不折算强化材料。

验收：

- 推荐卡字段完整。
- 明细表仍能审计完整结果。
- 日志默认不干扰主流程。

```powershell
python -m pytest -q
```

---

## 阶段 L：报告和文档收尾

目标：无人值守后我回来能快速知道做了什么。

任务：

1. 更新 README：
   - 当前是 PySide6 桌面应用；
   - horizon=1/2 都是精确计算；
   - horizon=2 可能慢，但可取消，不会卡死主窗口；
   - 不做 Monte Carlo；
   - 不做快速预览/近似推荐；
   - 如何使用驱动盘图标；
   - 如何运行 worker/profile/smoke；
   - 是否支持多进程并行，默认开关是什么。
2. 生成 `reports/unattended_work_summary.md`，包含：
   - 完成项；
   - 未完成项；
   - 测试命令和结果；
   - 当前并发模型；
   - horizon=2 防卡死方案；
   - 算法状态压缩方案；
   - 性能 profile 摘要；
   - 多进程并行结果；
   - UI 改动摘要；
   - 下一次建议我重点审查的文件。
3. 生成 `docs/next_steps.md`：
   - 只记录确实未完成或需要人决策的事项；
   - 不要把已完成任务堆进去。
4. 最后运行：

```powershell
python -m gear_optimizer.diagnostics
python desktop_app.py --app-check
python -m pytest -q
python -m gear_optimizer.acceptance --output reports/acceptance.md --check
```

5. 若全部通过，提交最终 commit：

```text
Finalize exact EV process isolation, state DP, parallelism, and UI polish
```

---

## 最终交付要求

1. 每个阶段至少一个 commit。
2. 不要停下来等我确认。
3. 不要引入快速预览模式。
4. 不要引入近似推荐。
5. 不要让 horizon=2 卡死主窗口。
6. 不要把取消后的 partial 结果当推荐。
7. 不要只做 QThread；horizon=2 必须至少做到子进程隔离。
8. 多核并行必须使用进程池或独立 worker 进程，不要用线程池假装 CPU 并行。
9. 最终 summary 必须清楚写明：
   - 当前是否仍有旧 app 残留；
   - horizon=2 是否已经子进程化；
   - 是否支持取消；
   - 是否做了 state DP；
   - horizon=1/horizon=2 新旧结果是否一致；
   - 是否支持多进程并行；
   - 是否接入驱动盘图标；
   - 测试是否通过；
   - 还有哪些风险。
