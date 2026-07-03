# gacha-gear-optimizer

本地 PySide6 原生桌面工具，用来维护米哈游装备库存，并计算当前最优搭配与调律 Action EV。

当前重点支持《绝区零》星徽・比利驱动盘分析，同时保留通过 YAML 扩展游戏规则、角色目标、概率模型和示例盘面的能力。

## 当前形态

- 主入口是 PySide6 原生窗口：推荐使用 `gacha-gear-optimizer`；`gacha-gear-optimizer-desktop` 是兼容旧用法的别名，`python desktop_app.py` 和 `scripts/start_desktop.cmd` 也会启动同一个桌面应用。
- 不再保留旧 Web UI、Streamlit 服务、浏览器窗口壳或 `start_app` 脚本。
- 桌面版复用 `src/gear_optimizer` 的核心算法、YAML 配置、库存保存和当前装备保存逻辑。
- PyInstaller Windows exe 会打包 `src`、`configs`、`examples`、`assets` 和 PySide6 runtime。

## 使用方式

进入应用后默认主视角是“总览”：

1. 在顶部选择游戏、角色模板和概率模型。
2. 在“背包库存”里点击“添加库存件”，录入位置、套装、主属性、等级、副词条和 roll。
3. 点击“保存库存到本机”。库存编辑只是静态台账，不会自动触发重计算。
4. 在“当前装备（身上 6 件）”里维护身上盘面，点击“确认当前装备”。
5. 点击“计算当前最优搭配”查看库存 + 当前装备里的最佳组合。
6. 点击“计算调律建议”显式运行 Action EV；horizon=1/2 都是完整概率分布精确计算。

当前装备必须先确认才允许计算。库存变化、当前装备变化、游戏/角色/概率变化都会清空旧结果，避免拿过期盘面继续算。

Action EV 不做 Monte Carlo、不做快速预览、不做近似推荐。horizon=2 可能耗时较长，会在独立 worker 子进程中运行，主窗口仍可切换页面；计算期间可以取消，取消后不会把未完成的 partial 结果展示为推荐。

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

## 验证

```powershell
python -m gear_optimizer.diagnostics
python -m pytest -q
python -m gear_optimizer.acceptance --output reports\acceptance_report.md --check --check-json reports\acceptance_checks.json
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
