# gacha-gear-optimizer

本地 PySide6 原生桌面工具，用来维护米哈游装备库存，并计算当前最优搭配与调律 Action EV。

当前重点支持《绝区零》星徽・比利驱动盘分析，同时保留通过 YAML 扩展游戏规则、角色目标、概率模型和示例盘面的能力。

## 当前形态

- 主入口是 PySide6 原生窗口：`gacha-gear-optimizer`、`gacha-gear-optimizer-desktop`、`python desktop_app.py` 和 `scripts/start_desktop.cmd` 都启动同一个桌面应用。
- 不再保留旧 Web UI、Streamlit 服务、浏览器窗口壳或 `start_app` 脚本。
- 桌面版复用 `src/gear_optimizer` 的核心算法、YAML 配置、库存保存和当前装备保存逻辑。
- PyInstaller Windows exe 会打包 `src`、`configs`、`examples`、`assets` 和 PySide6 runtime。

## 使用方式

进入应用后默认主视角是“背包库存（未装备盘）”：

1. 在顶部选择游戏、角色模板和概率模型。
2. 在“背包库存”里点击“添加库存件”，录入位置、套装、主属性、等级、副词条和 roll。
3. 点击“保存库存到本机”。库存编辑只是静态台账，不会自动触发重计算。
4. 在“当前装备（身上 6 件）”里维护身上盘面，点击“确认当前装备”。
5. 点击“计算当前最优搭配”查看库存 + 当前装备里的最佳组合。
6. 点击“计算调律建议”显式运行 Action EV；horizon=2 会显示进度、DP 状态和缓存命中。

当前装备必须先确认才允许计算。库存变化、当前装备变化、游戏/角色/概率变化都会清空旧结果，避免拿过期盘面继续算。

## 快速启动

```powershell
pip install -e ".[dev,desktop]"
python desktop_app.py --check
python desktop_app.py --app-check
python desktop_app.py
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
python -m gear_optimizer.acceptance --output reports\first_version_acceptance.md --check
```

完整发布门禁：

```powershell
.\scripts\release_gate.ps1
```

带 Windows exe 构建和打包 smoke：

```powershell
.\scripts\release_gate.ps1 -BuildPackage
```

## 打包

```powershell
pip install -e ".[packaging]"
.\scripts\build_windows_app.ps1 -SmokeCheck
```

默认输出：

```text
dist\gacha-gear-optimizer\gacha-gear-optimizer.exe
```

用户保存的套装方案、当前盘面和库存不会写入临时解包目录。打包版默认使用 `%LOCALAPPDATA%\gacha-gear-optimizer\user_data`，源码运行默认使用项目内 `user_data`；可用 `GEAR_OPTIMIZER_USER_DATA_DIR` 自定义。

## 边界

本项目不做 OCR、图片解析、联网查概率、伤害模拟、账号登录、数据库或云同步。所有装备和候选胚子都通过本地界面手动输入。
