# gacha-gear-optimizer

本地 PySide6 原生桌面工具，用来维护米哈游装备库存，并计算当前最优搭配与调律 Action EV。

当前重点支持《绝区零》星徽・比利驱动盘分析，并已接入《崩坏：星穹铁道》的遗器/位面饰品规则、套装文本、固定位置合成和自塑尘脂机会成本口径。其它游戏或角色仍可通过 YAML 扩展游戏规则、角色目标、概率模型和示例盘面。

## 当前形态

- 主入口是 PySide6 原生窗口：推荐使用 `gacha-gear-optimizer`；`gacha-gear-optimizer-desktop` 是兼容旧用法的别名，`python desktop_app.py`、`scripts/start_desktop.ps1` 和 `scripts/start_desktop.cmd` 也会启动同一个桌面应用。
- 不再保留旧 Web UI、Streamlit 服务、浏览器窗口壳或 `start_app` 脚本。
- 桌面版复用 `src/gear_optimizer` 的核心算法、YAML 配置、库存保存和当前装备保存逻辑。
- PyInstaller Windows exe 会打包 `src`、`configs`、`examples`、`assets` 和 PySide6 runtime。

## 使用方式

进入应用后默认主视角是“总览”：

1. 在顶部选择游戏、角色模板和概率模型。
   - “代理人”入口就在顶部表单里，显示为“切换代理人”按钮；代理人只负责展示身份，实际计算仍使用右侧关联的角色模板。
2. 在“背包库存”里点击“添加库存件”，录入位置、套装、主属性、等级、副词条和 roll。
3. 点击“保存库存到本机”。库存编辑只是静态台账，不会自动触发重计算。
4. 在“当前装备（身上 6 件）”里维护身上盘面，点击“确认当前装备”。
5. 点击“计算当前最优搭配”查看库存 + 当前装备里的最佳组合。
6. 点击“计算调律建议”显式运行 Action EV；horizon=1/2 都是完整概率分布精确计算。

当前装备必须先确认才允许计算。库存变化、当前装备变化、游戏/角色/概率变化都会清空旧结果，避免拿过期盘面继续算。

Action EV 不做 Monte Carlo、不做快速预览、不做近似推荐。horizon=1/2 都是理论精确计算；horizon=2 可能耗时较长，会在独立 worker 子进程中运行，主窗口仍可切换页面；计算期间可以取消，取消后不会把未完成的 partial 结果展示为推荐。

结果页先展示推荐卡，包含推荐动作、目标套装/位置、主属性、固定副属性、horizon、质量/母盘、有效/母盘、相对随机和“精确”计算口径。Action EV 明细默认显示前 20 条，可点击“显示全部”展开完整精确结果用于审计。

## 星铁口径

- 星铁关闭随机位置合成；Action EV 只生成固定位置、固定位置 + 固定主属性、固定位置 + 固定主属性 + 固定副属性。
- 外圈遗器只允许头部、手部、躯干、脚部；位面饰品只允许位面球、连结绳。默认模板是 `识海迷坠的学者 4 + 繁星竞技场 2`，用于通用暴击审计，不代表所有角色毕业推荐。
- 当前配置包含 60 套星铁文本素材：32 套隧洞遗器、28 套位面饰品；不内置联网图片，缺图时自动回退文字。
- 星铁和绝区零代理人 catalog 使用真实角色条目和本地图，选择器默认按实装版本从新到旧展示，并支持按属性、职介和名称搜索筛选；代理人只关联计算模板，不等同于模板。
- 自塑尘脂按 800 残骸折算，普通合成按 100 残骸/次，所以 1 个自塑尘脂等价 8 次普通固定位置合成。特殊资源表会显示高级素材机会成本、有效净省母盘和素材判断；这个折算不参与 Action EV 原始排序。
- 主属性概率和副词条抽取权重来自社区整理表，不是官方概率公告；详细边界见 `docs/hsr_relic_research.md`。

## 驱动盘图标

游戏规则里的套装可以配置 `set_icon_path` 指向 `assets` 下的图标文件。桌面版会在当前装备卡片、库存套装列和推荐卡中读取 32x32 套装图标，并在 tooltip 中展示 2/4 件套效果；图标缺失时自动回退文字，不影响启动或计算。

## 快速启动

```powershell
pip install -e ".[dev,desktop]"
python desktop_app.py --check
python desktop_app.py --app-check
python desktop_app.py
python -m gear_optimizer.action_ev_worker --help
```

也可以使用安装后的命令：

```powershell
gacha-gear-optimizer --check
gacha-gear-optimizer --app-check
gacha-gear-optimizer
```

或直接运行脚本：

```powershell
.\scripts\start_desktop.ps1 --check
.\scripts\start_desktop.ps1
```

## Worker、Profile 与 Smoke

horizon=2 的精确 Action EV 通过 worker 子进程运行：

```powershell
python -m gear_optimizer.action_ev_worker --help
```

worker payload 支持 `engine` 字段，合法值为 `inventory_recursive` 和 `state_dp`；缺省值始终是 `inventory_recursive`。也可以用环境变量覆盖：

```powershell
$env:GEAR_OPTIMIZER_ACTION_EV_ENGINE = "state_dp"
python -m gear_optimizer.action_ev_worker --help
```

这只是显式诊断/对比开关，不会把 state DP 变成默认策略。桌面 UI 会在运行日志和结果卡中显示当前 engine 与执行方式；horizon=2 仍通过 QProcess worker 子进程运行，horizon=1 默认在 QThread 后台线程中运行。

算法侧还有一条显式的 state-transition DP 路径：`position_strategy_efficiency_rows(..., use_state_dp=True)`。它把库存压缩成 `EvState`，用 state signature、transition cache 和 `Best(state)` count-state DP 做严格等价计算；当前测试已覆盖 horizon=1/2 与旧 inventory-recursive 精确路径一致。因为小样本 profile 没有明显快于默认路径，桌面推荐仍默认使用旧精确引擎，state DP 作为可审计/可 profile 的显式开关保留。

性能诊断工具会输出 JSON 和 Markdown 摘要；horizon=2 profile 属于手动重型命令，不默认纳入 CI：

```powershell
python -m gear_optimizer.profile_action_ev --horizon 1 --output reports\action_ev_profile.json --summary reports\action_ev_profile_summary.md
python -m gear_optimizer.profile_action_ev --horizon 1 --state-dp --output reports\action_ev_profile_state_dp.json --summary reports\action_ev_profile_state_dp_summary.md
python -m gear_optimizer.profile_action_ev --horizon 2 --output reports\action_ev_profile_h2.json --summary reports\action_ev_profile_h2_summary.md
```

已实现可选的进程池 action-value 计算核心和 profile 命令，用于验证多核并行口径。`GEAR_OPTIMIZER_WORKERS` 可覆盖 worker 数；当前小样本 profile 中 `workers=2` 慢于 `workers=1`，所以并行路径保留为显式诊断能力，不作为桌面默认推荐路径。

```powershell
$env:GEAR_OPTIMIZER_WORKERS = "4"
python -m gear_optimizer.profile_parallel_action_ev --horizon 1 --action-limit 4 --workers 1,2 --output reports\action_ev_parallel_profile.md
```

桌面导入级 smoke 可显式运行：

```powershell
python desktop_app.py --app-check
```

worker 临时目录使用系统临时目录下的 `gear-action-ev-*` 文件夹，内部包含 `input.json`、`result.json`、`progress.jsonl`、`error.json` 和 `summary.json`。成功完成的 horizon=2 任务最多保留最近 3 次，便于短期追溯；失败或取消的目录会保留用于诊断。

## 验证

```powershell
python -m gear_optimizer.diagnostics
python desktop_app.py --app-check
python -m pytest -q
python -m gear_optimizer.acceptance --output reports\acceptance.md --check --check-json reports\acceptance_checks.json
```

完整发布门禁默认不跑 smoke：

```powershell
.\scripts\release_gate.ps1
```

需要 smoke 时显式打开：

```powershell
.\scripts\release_gate.ps1 -SmokeCheck
```

带 Windows exe 构建：

```powershell
.\scripts\release_gate.ps1 -BuildPackage
```

带 Windows exe 构建和打包 smoke：

```powershell
.\scripts\release_gate.ps1 -BuildPackage -SmokeCheck
```

## 打包

```powershell
pip install -e ".[packaging]"
.\scripts\build_windows_app.ps1
```

默认输出：

```text
dist\gacha-gear-optimizer\gacha-gear-optimizer.exe
```

需要打包后 smoke 时显式加：

```powershell
.\scripts\build_windows_app.ps1 -SmokeCheck
```

用户保存的套装方案、当前盘面和库存不会写入临时解包目录。打包版默认使用 `%LOCALAPPDATA%\gacha-gear-optimizer\user_data`，源码运行默认使用项目内 `user_data`；可用 `GEAR_OPTIMIZER_USER_DATA_DIR` 自定义。

## 边界

本项目不做 OCR、图片解析、联网查概率、伤害模拟、账号登录、数据库或云同步。所有装备和候选胚子都通过本地界面手动输入。
