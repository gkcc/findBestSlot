# 代码坏味道审计与修复待办

更新时间：2026-07-10

## 审计范围

- `src/gear_optimizer`、`tests`、`scripts` 下共 63 个 Python 文件。
- `pyproject.toml`、打包/发布脚本、配置加载路径、用户数据持久化路径。
- Action EV、BOX/Portfolio EV、装备/库存/代理人数据流、PySide6 交互和运行日志。
- 不审计第三方依赖源码；`reports` 中生成内容不逐字审计，但审计其生成、跟踪和发布方式。

## 当前基线

- 全量测试：`396 passed in 219.53s`。
- 源码最大文件：`position_ev.py` 6234 行，`pyside6_app.py` 7453 行。
- 最大类：`OptimizerWindow` 4197 行、165 个方法。
- 超过 80 行的函数 55 个，超过 150 行的函数 13 个，高分支函数（静态分支节点 > 20）25 个。
- 跨模块导入私有符号 34 处，其中 `portfolio_ev.py` 从 `position_ev.py` 导入 20 多个私有 helper。
- 测试直接导入私有符号 65 处。
- `pyside6_app.py` 有 245 次字典 `.get()`，`position_ev.py` 有 149 次；显示列名同时承担内部协议键。
- Ruff 只有配置但未安装；无类型检查、覆盖率门禁、CI 配置和依赖锁文件。
- `git diff --check` 通过，但工作区存在 LF/CRLF 自动转换警告。

状态说明：`TODO` 未开始，`DOING` 正在处理，`DONE` 已有代码和验证证据，`BLOCKED` 需要外部决策。

## P0：正确性与用户数据安全

### CS-P0-01 双轨库存模型尚未统一 - DONE

证据：UI 通过 `user_inventory.py` 读写 `inventory/<game>/_shared.yaml` 的 `GearPiece` 列表；`agents.py` 另有 `GlobalInventoryStore`、`InventoryItem.item_id` 和 `inventory/<game>/global.yaml`。`AgentLoadout` 只认识后者，但当前 UI 主流程仍使用前者。

风险：同一游戏可能出现两份都自称“全局库存”的真相；装备归属、卸下、跨代理人切换和 BOX 输入可能不一致，稳定 `item_id` 也没有贯穿 UI 与算法。

完成标准：确定 `GlobalInventoryStore` 为唯一写入模型；提供只读兼容和 dry-run 迁移；UI 装备/卸下/删除均按 `item_id` 更新库存与代理人 loadout；覆盖跨代理人库存不变、装备归属隔离和缺失引用测试。

完成证据：迁移/兼容层覆盖 `_shared.yaml` dry-run、跨代理人稳定 ID、已有 `global.yaml` 幂等和旧文件备份。`inventory_service.py` 成为 canonical 领域入口：背包由所有代理人的 active loadout 共同扣除；新增、复制、编辑、清空、装备、卸下和删除均保留稳定 `item_id` 并即时写入；任意 active/inactive loadout 引用都会阻止物品删除。当前装备快照使用 `AgentLoadout.slot_items`，载入、保存、改名和删除不复制 `GearPiece`；删除最后一个快照后代理人保持真正空 loadout。BOX 为每个 target 读取各自 active loadout，并使用完整 global pool。未迁移旧格式在 UI 中只读，`pyside6_app.py` 已不再导入 legacy 保存/删除 API；显式迁移先 dry-run，确认后备份并 apply，旧文件不删除。真实 PySide6 smoke 覆盖原生游戏下拉、切换绝区零、装备卸下、BOX 计算和运行日志。

### CS-P0-02 持久化读取失败被静默伪装成空数据 - DONE

证据：`pyside6_app._initial_current_pieces()` 和 `_initial_inventory_with_source()` 捕获所有异常后返回空列表；模板重载也会在异常时退化为空集合。

风险：损坏 YAML、权限错误或 schema 不兼容看起来像“用户没有装备/库存”，后续保存可能覆盖原数据。

完成标准：加载结果显式携带错误；UI 保留上次有效状态并展示可操作提示；日志包含路径、异常类型和操作；读取失败时禁止以空数据覆盖源文件。

完成证据：当前装备/共享库存 helper 不再吞异常；上下文切换先完整读取再提交，失败时保留上一盘面、禁用计算和所有存储修改，并记录 `context_load_failed`；用户目标模板读取失败时禁用覆盖。真实窗口测试覆盖损坏库存、损坏当前装备、保留盘面和拦截保存。

### CS-P0-03 用户数据文件采用原地覆盖写入 - DONE

证据：`agents.py`、`user_current_gear.py`、`user_inventory.py`、`user_set_plans.py`、`user_target_templates.py` 均直接 `open("w") + yaml.safe_dump()`。

风险：进程崩溃、磁盘写满或系统关机可能留下截断 YAML。

完成标准：所有用户数据写入先在同目录临时文件完成并 flush，再用原子替换提交；失败时旧文件保持可读；有故障注入测试。

完成证据：新增 `storage_io.atomic_write_yaml()`，当前装备、共享/旧库存、set plan、目标模板、代理人状态、全局库存和 loadout store 均已接入；故障注入证明 `os.replace` 失败时旧文件不变且临时文件被清理。

### CS-P0-04 读改写没有并发冲突保护 - DONE

证据：模板、当前装备和库存保存均为“读取整个文件 -> 修改列表 -> 覆盖整个文件”，没有版本号、文件锁或 compare-and-swap。

风险：两个窗口或残留进程同时保存时会丢更新。

完成标准：写入协议带 revision 或跨进程锁；冲突时明确提示，不静默覆盖；增加双写冲突测试。

完成证据：canonical 代理人状态、全局库存和 loadout store 均携带严格递增的 `revision`，保存通过文件锁内 compare-and-swap 提交；陈旧副本抛出用户可读的 `StoreRevisionConflictError`，不会覆盖较新数据。当前装备、set plan、目标模板和 legacy 库存的列表更新通过 `update_yaml_mapping_locked()` 在同一把操作系统文件锁内重新读取并提交，崩溃后锁由操作系统释放。库存领域操作另由游戏级事务锁串行化，防止两个进程同时把同一 `item_id` 装给不同代理人。双进程测试覆盖锁超时、并发列表更新不丢失、陈旧写拒绝和装备归属竞争；桌面端冲突会记录结构化日志并显示明确警告。

### CS-P0-05 推荐规则存在两个权威实现 - DONE

证据：核心使用 `position_ev.recommended_action_ev_row()` / `_row_sort_vector()`；桌面端另有 `_desktop_recommended_action_row()` / `_action_display_sort_key()`，候选过滤和排序维度不同。

风险：CLI/报告与 UI 可能对同一批 rows 推荐不同动作，测试只能分别固化两套行为，无法证明业务口径一致。

完成标准：领域层提供唯一推荐决策对象和排序原因；UI 只能做展示排序，不能重新决定主推荐；增加跨入口一致性黄金测试。

完成证据：领域层现提供 `recommended_action_ev_row()`、`sorted_action_ev_rows()` 和统一 gating/sort key；桌面端重复的 recommend group/sort/recommend 实现已删除。原审计向量第一名明确改名 `top_action_ev_audit_row()`，保留解释用途但不冒充主推荐；报告、engine compare 和 UI 使用同一主推荐函数，黄金测试覆盖有效收益优先与 fixed action 门控。

### CS-P0-06 内部协议使用可变字典和中文显示列名 - TODO

证据：Action EV、报告、worker 和 UI 大量传递 `dict[str, Any]`，并以“策略”“有效/母盘”“套装约束”等显示文字作为程序键；缺失/类型错误常被 `0` 或空字符串吞掉。

风险：重命名列即可悄悄改变排序，worker JSON 也没有 schema 版本和强校验。

完成标准：建立带版本的 typed result/request 模型；内部字段使用稳定英文标识；中文列只在展示适配层生成；旧 JSON 有兼容解析测试。

## P1：高维护成本与回归放大器

### CS-P1-01 `position_ev.py` 算法单体过大 - TODO

证据：6234 行，混合概率分布、best-loadout DP、H=1/H=2、action space、缓存、性能打点、解释字段、推荐和并行执行。

完成标准：按稳定边界拆为 loadout、distribution、action_space、horizon、recommendation、cache/audit 模块；每次搬迁均以现有等价测试证明数值和排序不变。

### CS-P1-02 `OptimizerWindow` 是 God Object - TODO

证据：4197 行、165 个方法，同时管理存储、代理人选择、编辑器、库存筛选、进程协议、进度状态、推荐解释和表格渲染。

完成标准：抽出库存/当前装备 controller、计算 run controller、结果 presenter；窗口只组合组件和转发用户事件；关键 controller 可无窗口单测。

### CS-P1-03 超长和高分支函数过多 - TODO

证据：`position_strategy_efficiency_rows()` 736 行/73 个分支节点；`portfolio_action_rows()` 272 行/49；`evaluate_candidate()` 205 行/39；另有 52 个超过 80 行函数。

完成标准：为每个函数先补行为特征测试，再按阶段对象或纯 helper 拆分；单个函数原则上不再同时负责枚举、计算、排序、解释和进度上报。

### CS-P1-04 roll-state 概率逻辑重复 - DONE

证据：`piece_distribution.py` 与 `position_ev.py` 中 `_initial_roll_states`、`_advance_roll_states`、quality 计算存在逐 AST 相同实现。

风险：修概率 bug 时可能只改一份，BOX、Action EV 和分布测试随后漂移。

完成标准：`piece_distribution.py` 成为唯一实现；Action EV/BOX 通过公开 API 调用；保留等价黄金测试。

完成证据：唯一实现已公开为 `initial_roll_states()` / `advance_roll_states()` / `quality_from_roll_state()`；Action EV 保留兼容别名，BOX 改用公开 API；AST 重复函数体复扫为 0。

### CS-P1-05 set-plan 满足判定重复 - DONE

证据：`portfolio_ev._combo_satisfies_target_plan()` 与 `position_ev._count_state_satisfies_plan()` 各自实现相同回溯分配。

完成标准：抽出基于 `SetPlan + counts` 的唯一纯函数；4+2、2+2+2、可选套装和同套装不可重复占用均由同组参数化测试覆盖。

完成证据：新增 `set_plan_solver.set_plan_satisfied_by_counts()`，Action EV DP、组合校验和 BOX 严格成型判断共用；新增 flexible 4+2 与不可重复消费计数测试。

### CS-P1-06 BOX 依赖 Action EV 私有实现细节 - TODO

证据：`portfolio_ev.py` 从 `position_ev.py` 导入 20 多个下划线 helper，并直接依赖 inventory row 的隐含字段。

完成标准：建立最小公开领域 API（action specs、outcomes、loadout frontier、cost）；禁止生产模块跨模块导入下划线符号；私有实现可独立重构。

### CS-P1-07 全局可变缓存缺少明确生命周期 - DONE

证据：`position_ev.py` 维护 5 组模块级 `OrderedDict`；profile 直接导入私有缓存清空；缓存值含可变 list/dict。

风险：测试顺序、线程并发和返回值误修改会污染后续计算；性能报告难区分冷/热缓存。

完成标准：提供公开 cache context/facade、集中清理和统计；返回不可变值或防御性复制；明确线程策略；profile 不再导入私有全局变量。

完成证据：`action_ev_cache_sizes()` / `clear_action_ev_caches()` 集中提供生命周期与统计，5 组 LRU 的 get/set/clear/size 均由同一 `RLock` 保护，profile 不再导入私有缓存。不可变 best-combo tuple 可直接复用；Action/资源结果行在入缓存和命中返回时深复制；大型 aggregated-outcome/state-transition 缓存采用“缓存拥有快照、算法热路径只读借用、普通调用方防御性复制”的边界。污染测试会修改嵌套条件分支、代表搭配 row、outcome inventory 和 `EvState.rows`，后续命中仍返回原始结果。内置 H=2 exact state-DP 实测 `21.40s`，临时禁用复制为 `21.06s`，所有权保护未显著改变热路径耗时。

### CS-P1-08 worker 文件协议没有强 schema - TODO

证据：UI 手工拼 input JSON，worker 用 `.get()` 恢复，结果/进度/错误/summary 各自为自由字典。

完成标准：定义带 `schema_version`、`run_id` 的请求/结果/进度模型；进程两端校验；不兼容版本给出用户可读错误；保留失败目录供诊断。

### CS-P1-09 异常边界过宽且部分静默 - DONE

证据：生产代码有多处 `except Exception`，worker/并行路径还捕获 `BaseException`；`append_ui_runtime_log`、worker 失败事件写入等路径直接吞掉二次异常。

完成标准：边界层只捕获可恢复异常；`KeyboardInterrupt`/`SystemExit` 不作为普通计算错误；每次降级都有结构化记录；数据错误与程序错误分开提示。

完成证据：worker/并行算法不再捕获 `BaseException`；原子写清理改用 `finally`；manifest/readiness 仅捕获文件与解析异常；UI 原静默评分、审计、弱位和快照降级均记录事件或展示错误。架构测试禁止生产代码新增 bare except / `BaseException` catch。

### CS-P1-10 可观测性是分散的 best-effort 实现 - DONE

证据：UI 自写 JSONL，worker 另写 progress/error/summary；日志写失败不可见，主日志无轮转，部分用户操作和存储路径没有统一 run/agent/game 关联字段。

完成标准：统一结构化事件 API；自动带 session/run/game/agent；日志限额/轮转；关键交互、加载、保存、计算、取消、异常都有事件；诊断页可定位当前日志。

完成证据：新增共享 `runtime_logging.append_runtime_event()`，自动记录时间、pid、session、source；UI 自动补 game/agent/target，Action/BOX/best-loadout 贯穿 run id。日志按 2 MiB、3 份备份轮转，Doctor 显示路径和大小；代理人/模板/快照/库存关键操作、加载/保存/计算/取消/失败均有事件。worker 的 progress/error/summary 继续作为 run 专属协议文件，并通过同一 run id 与 UI 事件关联。

### CS-P1-11 存储工具重复 - DONE

证据：`_safe_id` 在 4 个模块重复，`_read_store` 在 3 个模块逐 AST 相同，YAML 写入样板分散在更多模块。

完成标准：共享 storage utility 负责安全 ID、mapping 读取、原子 YAML 写入和错误上下文；业务 store 只负责 schema。

完成证据：新增 `storage_io.py`，4 份 `_safe_id` 和 3 份逐 AST 相同 `_read_store` 已归并，用户 store 不再直接执行 YAML 覆盖写。

### CS-P1-12 库存 UI 每次变化都全量重建卡片 - TODO

证据：`_refresh_inventory_view()` 重新筛选、销毁并创建所有卡片；大型库存的编辑、选中和高亮都会触发刷新。

完成标准：使用 model/view 或增量 diff；保留 selection/scroll；以真实大库存建立刷新耗时基线和上限。

### CS-P1-13 测试高度耦合私有实现 - TODO

证据：65 处测试私有导入；`test_desktop_app.py` 3800 行，`test_position_ev.py` 2467 行。

完成标准：核心语义通过公开 API/契约测试覆盖；私有算法仅保留少量白盒数学测试；按领域拆分测试文件和 fixtures。

### CS-P1-14 UI smoke 默认复用固定临时目录 - DONE

证据：`desktop_ui_smoke.run_smoke()` 默认使用系统临时目录下固定的 `gear-ui-smoke-user-data`，不清理旧状态。

风险：前一次运行的库存、快照和日志会影响下一次 smoke，造成假通过或偶发失败。

完成标准：默认每次使用独立临时目录并自动清理；显式传入目录时才保留现场；加入连续运行隔离测试。

完成证据：`run_smoke()` 默认使用 `TemporaryDirectory` 包裹完整 smoke；显式目录路径保持原行为；单测证明运行时目录存在且返回后自动删除。

### CS-P1-15 缺少可执行的静态质量门禁和 CI - DOING

证据：`pyproject.toml` 有 `[tool.ruff]`，但 dev 依赖未包含 Ruff；本机 `python -m ruff`、mypy、radon、vulture 均不可用；仓库无 CI。

完成标准：明确最小 lint/type 规则，加入 dev 依赖和 CI；先冻结现状基线，再逐批收紧；PR 至少执行 compile、lint、核心测试和 UI offscreen smoke。

当前进度：dev 依赖固定 Ruff 0.15.21，基础 `E4/E7/E9/F` 已全仓通过；新增 Windows CI 执行安装、compile、lint 和全量 offscreen pytest。Ruff 首跑额外发现并修复迁移未知角色路径的 `_safe_id` NameError。剩余工作：类型检查/覆盖率基线，以及把真实 UI smoke 独立列为 CI 步骤。

### CS-P1-16 依赖不可完全复现 - TODO

证据：Pydantic/PyYAML 只有下限，无 lock/constraints；桌面依赖单独精确固定，开发/打包环境可能解析出不同组合。

完成标准：选择并提交可更新的 lock/constraints；源码、测试和打包使用同一解析结果；记录更新流程。

### CS-P1-17 旧用户 store 缺少统一 schema version 与升级链 - DONE

证据：当前装备、共享库存、set plan、目标模板格式各自演进，仅新 multi-agent store 有 `schema_version`。

完成标准：所有用户 store 有版本；读取执行显式、可测试、非破坏升级；写前可备份；未知新版本拒绝覆盖。

完成证据：当前装备、共享/旧库存、set plan、目标模板、代理人状态、全局库存和 loadout 均写入并校验 `schema_version=1`；无版本文件按 v0 legacy 读取并在下一次保存升级。未来版本明确抛 `UnsupportedStoreVersionError`/Pydantic validation，UI 由读取失败保护阻止覆盖；覆盖和删除前自动保留同目录 `.bak`。

## P2：清理、边界和工程一致性

### CS-P2-01 存在疑似死代码和失效参数 - DONE

证据：静态引用扫描发现 `_row_enters_best_loadout`、`_sum_vectors`、`_candidate_combos`、`_initial_inventory_pieces`、`_action_hint_summary` 等仅有定义；`fallback_storage_ids` 参数被传入但未使用。

完成标准：逐项确认外部兼容需求；删除死代码/参数或补公开用途测试，不保留“也许以后会用”的分支。

完成证据：删除 9 个无仓库调用的私有 helper、`fallback_storage_ids` 等失效参数，以及 4 个无文档/测试承诺的旧公共便捷函数；旧 `_candidate_combos` 包装已移除并更新算法文档。AST 全仓引用复扫不再发现仅有定义的顶层函数/类。

### CS-P2-02 包导出清单已过时 - DONE

证据：`gear_optimizer.__all__` 未包含 `position_ev`、`portfolio_ev`、`portfolio_models`、用户存储等当前核心模块，现有测试只验证列表内模块可导入，不验证完整性。

完成标准：明确公共 API；`__all__` 与文档一致；增加禁止意外私有依赖的架构测试。

完成证据：`gear_optimizer.__all__` 已覆盖当前支持的领域/存储模块并明确排除 worker、profile 和 PySide6 实现模块；新增架构测试冻结现有 32 处私有跨模块依赖，任何新增依赖都会失败，后续清单只能缩小。

### CS-P2-03 路径层反向依赖 `game_rules` - DONE

证据：`paths.py` 为取得 `PROJECT_ROOT` 导入 `game_rules.py`，多个基础模块再间接依赖配置模型。

完成标准：项目根和 app-data 路径下沉到无业务依赖的基础模块；配置加载依赖路径层，不能反向。

完成证据：新增无业务依赖的 `project_paths.py`；`paths.py`、配置、UI、打包/诊断模块和脚本均直接依赖该基础层；`game_rules` 只保留兼容重导出。PyInstaller bundle root 与 app-data 测试通过。

### CS-P2-04 action mode/engine/scope 使用散落字符串 - DONE

证据：`state_dp`、`inventory_recursive`、`tuning_static`、`tuning/upgrade/all` 等在 UI、worker、算法和测试中重复判断。

完成标准：使用 Enum/Literal + 单点解析；非法值在入口失败；序列化值稳定且有兼容测试。

完成证据：新增 `action_types.py`，统一定义 `ActionEvMode`、`ActionEvEngine`、
`ActionEvLookaheadScope` 和 `PortfolioActionScope` 四组 `StrEnum` 及入口 normalizer；worker、
Position EV、BOX 和桌面端内部判断均使用枚举，旧的 `fast/exact`、
`inventory_recursive/state_dp`、`exact/tuning_static`、`tuning/upgrade/all` 序列化值保持不变。
兼容别名和非法值拒绝均有测试，原公开常量继续显式重导出。

### CS-P2-05 报告模块混合取数、判断和长文本模板 - TODO

证据：`reporting.py` 1260 行、`conclusions.py` 1343 行，存在 130 行以上多参数 Markdown 构建函数。

完成标准：先生成 typed report model，再由 renderer 输出 Markdown；判断逻辑不藏在文案拼接中。

### CS-P2-06 `reports/` 被忽略但仍跟踪部分生成文件 - DONE

证据：`.gitignore` 忽略整个 `reports/`，Git 仍跟踪 9 个历史 report 文件。

完成标准：区分版本化基准/设计文档与一次性产物；前者移入明确目录，后者停止跟踪；发布脚本不依赖脏工作区中的旧报告。

完成证据：3 份长期说明（state-DP 等价性、并发审计、阶段总结）移入 `docs/`；7 份 acceptance/profile 生成物退出版本库，命令仍按需写入已忽略的 `reports/`。生成与 readiness/profile 测试通过。

### CS-P2-07 运行时检查使用 `assert` - DONE

证据：`launcher.desktop_smoke_rows()` 用 `assert callable(pyside6_app.main)` 判断入口，`python -O` 会移除该检查。

完成标准：改为显式条件和明确异常；增加不可调用入口测试。

完成证据：`desktop_smoke_rows()` 改为显式 callable 检查并报告模块名，新增不可调用入口测试。

### CS-P2-08 缺少统一换行和编辑器规则 - DOING

证据：当前修改文件持续出现 LF 将被 Git 转为 CRLF 的警告，仓库无 `.editorconfig`/`.gitattributes`。

完成标准：确定源码换行策略并提交配置；不做无意义全仓换行 churn；后续 diff 不再出现转换警告。

当前进度：已新增 `.gitattributes` / `.editorconfig`，源码/文档固定 LF，PowerShell/CMD 固定 CRLF；待本批所有编辑结束后仅规范化本次触及文件并复查无换行警告。

### CS-P2-09 示例加载会补造默认装备 - DONE

证据：`load_example_current()` 路径通过 `_complete_position_pieces()` 为缺失位置构造 `_default_piece()`。

风险：示例/占位数据可能被误认为用户实际装备，与“空就是空”的数据语义冲突。

完成标准：示例保持原始空/部分状态，或 UI 明确标注为未保存演示数据；不得静默写入代理人快照或库存。

完成证据：`load_example_current()` 直接使用示例原始 pieces，补齐默认六件的 helper 已删除；真实窗口测试证明 1 件示例载入后仍为 1 件且保持未确认，不写库存/快照。

### CS-P2-10 全量反馈周期偏长且没有测试分层标记 - TODO

证据：396 个测试耗时 3 分 39 秒；核心数学、Qt 构造、真实 smoke 和发布检查没有统一 markers/分层命令。

完成标准：定义 core/ui/slow/release 分层；日常核心门禁保持短反馈，全量/真实 smoke 仍定期执行且不被跳过。

## 修复顺序

1. 数据安全基础：CS-P0-03、CS-P1-11、CS-P2-07。
2. 无语义变化的去重：CS-P1-04、CS-P1-05。
3. 错误可见与可观测：CS-P0-02、CS-P1-09、CS-P1-10。
4. 库存唯一真相：CS-P0-01、CS-P0-04、CS-P1-17。
5. 推荐和协议统一：CS-P0-05、CS-P0-06、CS-P1-08、CS-P2-04。
6. 算法/UI 解耦：CS-P1-01、CS-P1-02、CS-P1-03、CS-P1-06、CS-P1-07、CS-P1-12。
7. 工程门禁与仓库清理：剩余 P1/P2 项。

每完成一项都必须在本文件更新状态，并记录实际测试命令；仅“移动了代码”不算完成，行为等价或目标行为需要可验证证据。

## 验证记录

- 2026-07-10 基线：`python -m pytest -q` -> `396 passed in 219.53s`。
- 2026-07-10 数据安全批次：存储、代理人、模板和 launcher 定向测试 -> `31 passed in 1.09s`。
- 2026-07-10 算法去重批次：piece distribution、set-plan、EV state、BOX、Action EV -> `107 passed in 18.84s`。
- 2026-07-10 读取失败防护：5 个窗口交互回归测试 -> `5 passed in 10.61s`；损坏库存/当前装备专项 -> `2 passed in 1.16s`。
- 2026-07-10 smoke 隔离：临时目录包装与 CLI 委托测试 -> `2 passed in 0.43s`。
- 2026-07-10 私有死代码清理：策略、报告、Action EV、BOX、桌面回归 -> `192 passed, 2 deselected in 158.01s`；编译与引用复扫通过。
- 2026-07-10 死代码最终复核：Action EV、策略、结论和报告 -> `107 passed in 19.99s`；AST 顶层零引用复扫为空。
- 2026-07-10 公共模块/架构边界：`test_architecture.py + test_package_exports.py` -> `3 passed in 0.64s`。
- 2026-07-10 缓存生命周期第一步：LRU 上限、公开 clear/size、profile、架构测试 -> `6 passed in 4.72s`；生产私有跨模块导入降至 27。
- 2026-07-10 Ruff/CI 第一层：`python -m ruff check src tests scripts` -> `All checks passed`；相关缓存、迁移、profile、架构测试 -> `20 passed in 5.35s`。
- 2026-07-10 路径依赖拆分：项目根、app-data、诊断、发布、readiness、架构测试 -> `29 passed in 1.21s`；Ruff 通过。
- 2026-07-10 异常边界：存储、worker、并行 EV、readiness、manifest、导入与损坏数据窗口测试 -> `61 passed in 9.45s`；补充架构与真实窗口回归 -> `44 passed in 12.29s`；Ruff/compile 通过。
- 2026-07-10 可观测性：结构化日志/轮转/Doctor/Action 与 BOX run id -> `13 passed in 2.49s`；模板、快照、库存真实 Qt 操作回归 -> `40 passed, 48 deselected in 119.70s`；Ruff/compile 通过。
- 2026-07-10 示例空/部分语义：partial 示例与主窗口回归 -> `2 passed in 5.10s`；Ruff 通过。
- 2026-07-10 reports 清理：acceptance、readiness、串行/并行 profile -> `28 passed in 11.40s`；Ruff 通过。
- 2026-07-10 用户 store 版本化与备份：storage、四类 legacy store、multi-agent store、迁移 -> `38 passed in 1.01s`；Ruff 通过。
- 2026-07-10 推荐权威统一：推荐/brief/门控专项 -> `8 passed, 52 deselected`，桌面主卡 -> `3 passed`，Action EV/报告/结论/state-DP 回归 -> `94 passed in 27.10s`；Ruff 通过。
- 2026-07-10 编译检查：变更模块 `python -m py_compile ...` 通过；`git diff --check` 无空白错误（仍有待处理的换行策略警告，见 CS-P2-08）。
- 2026-07-10 action 协议枚举化：`test_action_types.py + test_action_ev_worker.py + test_portfolio_ev.py + test_position_ev.py` -> `91 passed in 25.30s`；全仓 Ruff 通过。
- 2026-07-10 全局库存迁移安全层：共享 ID 稳定、`_shared.yaml` dry-run、已有 global 幂等迁移专项 -> `3 passed`；代理人/库存/版本完整回归 -> `29 passed in 0.88s`；Ruff/compile 通过。
- 2026-07-10 canonical UI 与 loadout 快照：领域服务 `7 passed in 0.53s`；canonical/BOX/迁移窗口专项 `36 passed, 79 deselected in 17.03s`，旧库存/快照兼容回归 `28 passed, 58 deselected in 70.04s`；全仓 Ruff 与 compile 通过。窗口重启测试覆盖即时持久化、跨代理人背包不变、当前装备隔离、引用删除拦截和 loadout 仅存 item_id。
- 2026-07-10 BOX 目标主属性成型修正：Portfolio `21 passed`、Qt 展示 `1 passed`；叶瞬光真实数据复算为固定物伤 5 号位主 EV/命中后增益 `103.787`、跃迁 `100%`，固定 5 号位随机主属性命中 `22.222%`，随机位置命中 `3.704%`。
- 2026-07-10 全局库存唯一写入收口：真实 PySide6 offscreen smoke `UI_SMOKE_OK`（游戏下拉、绝区零切换、item_id 卸下、BOX 22 行、运行日志）；全仓 `449 passed in 226.50s`；全仓 Ruff/compile 通过。
- 2026-07-10 并发写保护：storage/agents/inventory/legacy store/迁移/架构定向回归 -> `63 passed in 3.01s`；桌面库存/快照/模板回归 -> `57 passed, 52 deselected in 111.71s`；真实 PySide6 offscreen smoke `UI_SMOKE_OK`。双进程覆盖文件锁等待、读改写合并和同一 item_id 装备竞争，Ruff/compile 通过。
- 2026-07-10 缓存值所有权收口：Action EV、state-DP、profile、worker -> `86 passed in 16.51s`；4 类嵌套可变值污染测试通过。内置 H=2 exact state-DP `21.40s`，禁用复制对照 `21.06s`；Ruff/compile 通过。
