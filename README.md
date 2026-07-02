# gacha-gear-optimizer

本地可视化的米哈游装备词条概率 / 期望寻优工作台。

第一版重点支持《绝区零》星徽·比利驱动盘分析：

- 当前 6 件盘评分和最弱位置识别
- 候选胚子继续强化期望评估
- 调律策略资源期望和长期 / 当前收益对比
- 套装方案、4/5/6 主属性倾向、副词条优先级可在侧栏临时覆盖
- 通过 YAML 配置游戏布局、主属性概率、副属性池和《崩坏：星穹铁道》规则扩展
- 另内置 ZZZ 泛用异常模板，用于验证角色目标、套装方案、主属性倾向和副词条优先级不是写死在星徽·比利上

## 本地形态

当前主入口是 PySide6 原生桌面 UI：`gacha-gear-optimizer-desktop` 或 `scripts/start_desktop.cmd` 会直接打开桌面窗口，不再启动本地 Streamlit 服务，也不再用浏览器承载 UI。`gacha-gear-optimizer` 仍保留为 legacy Streamlit Web 入口，方便对照旧页面和继续跑既有 UI 回归。

桌面版仍复用 `src/gear_optimizer` 的核心算法和 YAML 配置；改造只替换交互层和打包链路：

- 桌面：`desktop_app.py` / `scripts/start_desktop.cmd` 直接启动 PySide6 原生窗口。
- Web legacy：`scripts/start_app.cmd` 仍可启动 Streamlit 本地页面。
- 打包：PyInstaller Windows exe 构建脚本会收集 PySide6、`src`、`configs`、`examples` 和 `assets`。

桌面版不再套网页壳，也不会弹浏览器或本地服务终端。

## 使用方式

侧栏先选择游戏、角色模板和目标套装方案。套装方案只保留目标结构输入：4+2、2+2+2 或不限套装；选择后会展示相关套装图标和 2/4 件套效果。用户只决定目标组合，先补 4 件还是 2 件由工具根据当前盘面、缺口、主属性、锁定盘和可让位位置自动判断。
第一版不做套装方案市场、方案对比、保存方案或自由组合编辑；要长期复用角色目标时，使用“角色目标 YAML”导入/导出。
套装阶段排序会把“核心 4 件 / 2 件套角色”、当前进度、缺口、配置优先级和可让位盘质量一起纳入计算；如果某个弱位已被锁定，或当前缺口只能动到高分盘，阶段推荐会相应降权。
“角色目标 YAML”可以导入已导出的目标配置，用于复用套装方案、主属性倾向和副词条优先级。
“概率模型 YAML”可以导入或导出当前概率模型，用于复用目标套装概率、初始 3/4 词条概率和资源成本假设。
侧栏“概率模型参数”可以直接临时调整目标套装概率、初始 3/4 词条概率、母盘/校音器/共鸣核成本；导出的概率模型会使用当前界面里的实际参数。ZZZ 默认按“指定套装调律”为口径：目标套装概率 100%，随机位置约 3 母盘/次，固定位置约 6 母盘/次，固定主属性消耗校音器，固定副属性消耗共鸣核。
“主属性倾向”用于定义角色在各位置接受哪些主属性；“副词条优先级”用于区分核心词条、可用词条和不可用词条。界面不要求手填小数，用户只需按顺序选择核心/可用词条，内部再映射成稳定排序系数。
角色 YAML 直接写 `substat_priority.core` 和 `substat_priority.usable` 列表；工具按列表顺序排序，不再生成副词条小数系数，导出的目标配置也优先保留这种列表形式。
角色模板可以同时配置 `target_effective_rolls` 和 `target_weighted_score`：前者用于判断最终有效词条数量是否达标，后者用于当前补弱、套装让位、调律相对收益和质量目标线判断。
侧栏“评分目标”是高级可选项，普通使用保持角色模板默认即可；它只是工具内部观察线，不是伤害模拟。只有想让推荐更激进或更保守时，才临时覆盖有效词条目标、质量分目标和 usable / good / excellent 评级线；界面也提供“恢复角色模板评分目标”。
如果当前位置主属性偏离角色目标，当前补弱排序和调律策略会把“修正主属性”作为更强的提升信号，而不是只按副词条分数判断。

当前装备页的 6 个盘位按游戏配置中的 `board_layout` 展示。ZZZ 默认使用上排 1/2/3、下排 4/5/6 的 2x3 矩阵，避免宽屏下环形布局挤压和留白失控。侧栏“盘面显示密度”可以在紧凑、标准、宽松之间切换，2K 全屏默认推荐紧凑。盘位卡片会直接标出评级、最弱位、主属性是否命中和套装让位判断；点击卡片即可编辑该位置的套装、主属性、等级、副属性和 roll 次数。
ZZZ 盘位方块会把本地驱动盘图标作为格子背景水印，格子内直接显示套装、评级、规划目标、有效词条、质量分、主属性和保留/让位状态；崩铁则按配置展示两排部位布局。
当前装备页会在盘位矩阵下方显示“盘面状态摘要”，用来快速查看保存就绪、完整度、自动校验和保存路径；崩铁占位配置同样保持两排部位布局。
如果某个位置已经是想长期保留的极品盘，可以在卡片弹窗里勾选“保留此盘”，它仍参与评分，但不会再被套装让位和当前调律优先级推荐替换。
如果锁定盘占用了过多位置，导致当前 4+2 或 2+2+2 方案在剩余位置里无法完成，套装阶段会提示“锁定冲突”，建议改套装方案、解锁或接受过渡。
候选胚子如果落在已锁定位置，工具会保留它自身的强化期望计算，但结论会按备用 / 过渡盘处理，不再把它视为替换当前盘的目标。
当前装备页在“盘面状态摘要”下方提供“保存当前盘面”入口；编辑每个盘位时会实时写入当前会话并重新校验，确认保存就绪后填写模板名称并保存到本机 `user_data/current_gear/<game>/<character>.yaml`。“盘面模板”可以显式重载当前角色示例盘面，也可以清空为手动输入状态；保存后的盘面会作为“已保存”盘面重新出现在该角色的模板下拉列表中。
“导入/导出”可以把当前盘面下载为本地 YAML，也可以重新上传同格式 YAML 回填盘面；同时可以导出 Markdown 分析报告，方便复现和分享一次分析。
当前装备和候选胚子的 YAML 导入会按当前游戏规则校验位置、套装、主属性、副属性、等级步长、roll 上限和副属性唯一性，避免不合法盘面进入分析。
当前装备 YAML 也可以写 `initial_substat_count: 3` 或 `4`，用于保留“初始 3 词条 +3 先补第 4 条”的 roll 上限判断；旧文件不写时会按已有可见副属性兼容导入。
Markdown 报告会包含当前结论、调律结论、当前推荐目标的五档成本阶梯、角色目标和当前装备评分明细。
侧栏“规则概览”会展示当前游戏的位置 / 主属性池、副属性池、强化规则和概率模型，方便确认 ZZZ 与 HSR 配置是否正确加载。
游戏规则加载时会校验主属性概率和副属性概率配置，避免未知属性、负概率或主属性概率总和错误悄悄影响策略结果。

当前装备示例会按当前游戏和角色加载；ZZZ 内置星徽·比利示例，HSR 内置占位遗器示例用于验证布局、规则和 YAML 流程可加载展示。
候选胚子页会按当前游戏加载 `examples/*candidate*.yaml` 示例；ZZZ 示例覆盖“继续”和“仅过渡”，HSR 占位候选用于验证同一套强化期望链路可跨游戏运行。
候选评估同时展示原始有效词条期望和按角色副词条优先级计算的质量期望，方便区分“可用但低优先级”的词条。
候选结果概率会分别展示超过当前同位置、达到有效词条目标线、达到质量目标线，以及达到 good / excellent 评级的概率。
继续 / 暂停 / 仅过渡 / 放弃的建议会根据角色目标线和评级阈值推导，不再使用固定写死的星徽·比利阈值。
候选结论会把胚子满级期望和当前同位置盘面对比，直接标出是否值得继续、是否有望替换、主属性和套装方案是否命中；如果当前套装方案还有缺口，也会区分候选是“命中当前缺口”还是只“符合长期方案”。“候选补位价值”会把当前位置是否最弱、主属性是否命中、套装缺口和满级质量期望增量合在一起，避免只看强化期望数字误判；“强化观察点”会把下一跳 +3/+6 该看什么、命中概率和止损规则直接列出来。
候选页还会对照当前套装目标判断这个胚子是否命中当前位置的替换意图，例如命中让位 2 件套、命中核心 4 件保留位，或者不补当前缺口；结果概率里会单独给出“命中套装目标并超过当前”的概率。
“候选 YAML”可以导入或导出单个胚子，也可以导出候选分析 Markdown 报告，用于复现实战里的强化决策案例。

库存维护不需要手动编辑 YAML。进入应用默认就是“库存”工作区：打开“背包库存（点这里添加未装备盘）”，点击“添加库存件”，选择位置、套装、主属性、等级和副属性，最后点击“保存库存到本机”。身上 6 件在“方案模板”工作区维护；库存编辑是静态台账，不会自动触发 Action EV；需要看配装时点“计算当前最优搭配”，需要看调律路线时点“计算调律建议”。导入 / 导出库存 YAML 只作为备份、迁移或给别人复现实验使用。

库存工作区会做全局扫描，跨所有位置、目标套装和角色主属性倾向给出当前补弱、长期目标、校音器和共鸣核建议；“调律结论”会直接回答现在该固定几号位、长期目标、资源是否该用以及长期 / 当前是否冲突；下方仍保留单个手动目标的五种策略对比。
方案模板工作区聚焦身上 6 件盘评分、最弱位置、实时校验和保存盘面；不再重复展示调律行动清单。
库存工作区展示套装阶段拆解、随机 vs 固定位置收益效率、固定主属性/副属性省母盘阶梯；已有极品盘会按质量分、主属性命中和锁定状态优先保留，避免为了凑套装牺牲高质量位置。
库存工作区会展示“策略上下文”，把当前套装方案、套装组进度、合并后的套装概率、4/5/6 主属性倾向和副词条优先级放在一张表里，方便确认策略是在当前 4+2、2+2+2 或不限套装目标下计算的。
手动目标策略比较里的“目标套装”也支持可接受套装组，例如啄木鸟电音 / 河豚电音 / 激素朋克 会按组合并后的套装概率计算成本，而不是只按单一套装估算。
普通手动比较默认只看随机位置、固定位置、固定主属性三档，不锁副属性、不消耗共鸣核；“固定副属性 / 共鸣核观察”折叠区只用于极限毕业或明确要花共鸣核的场景。
如果某个位置配置了多个可接受主属性，例如 4 号位暴击率 / 暴击伤害，全局扫描会分别评估这些主属性，不只拿第一个目标。
如果套装方案包含可选 2 件套，例如啄木鸟电音 / 河豚电音 / 激素朋克，自动全局扫描会把它作为一个可接受套装组计算概率；手动目标策略仍按用户选择的单一套装精确计算。
策略表会标出固定副词条的优先级，例如核心词条和低优先级可用词条会分别显示，避免只看到一串副属性名却不知道资源为什么锁它们。
库存工作区和当前分析报告都会展示“概率与资源假设”，明确目标套装概率、初始 3/4 词条概率，以及母盘、校音器、共鸣核的单位成本；校音器和共鸣核只单独计数，不折算成母盘。
调律结论的依据会同时写出可接受套装范围和套装概率来源，避免把可选 2 件套组合误读成单套装成本。
“随机 vs 固定位置收益效率”会在点击“计算调律建议”后按当前库存池估算收益：随机和固定都会把新盘加入库存后重求当前套装约束下的最优组合，并同时展示质量提升 / 母盘和原始有效词条提升 / 母盘。
Action EV 展望步数选 2 时仍是完整概率分布的精确理论计算，不是抽样模拟。为避免页面控件一变化就自动长时间重算，horizon=1 和 horizon=2 都需要点击“计算调律建议”后才会运行；horizon=2 会显示 action 进度、DP 状态数和缓存命中数。
“特殊资源全局边际 EV”是审计明细，默认不自动计算；只有需要复核校音器 / 共鸣核边际差值时，先勾选“计算特殊资源全局边际 EV 详情”，再点击“计算调律建议”。
“固定主属性省母盘阶梯”会在已经决定固定位置之后，列出达到 +1/+2/+3 质量分目标时，锁主属性相对不锁主属性能少刷多少母盘，以及需要多少期望校音器；这里不做校音器 / 共鸣核折算。
“固定副属性省母盘阶梯”会在已经固定位置和主属性之后，比较锁 1/2 个目标副词条能少刷多少母盘，并单独列出期望校音器和期望共鸣核；共鸣核仍只作为极限毕业观察，不进入常规补弱默认动作。
“胚子挡位概率解释”会展示初始 3/4 词条、3中2、4中3 等挡位的条件概率和总出现概率。多数情况下初始 3 词条按概率模型作为主流；4中3 只有在主属性没有挤占有效副词条时才可能出现，例如 5 号物伤可以 4中3，6 号生命百分比会挤掉生命百分比副词条。

## 第一版验收口径

当前内置星徽·比利示例应能直接回答：

- 当前 6 件盘哪件最弱：示例盘面应识别 6 号位。
- 现在应该优先刷/调律哪个位置：当前补弱策略应偏向 6 号位。
- 新胚子值不值得强化：两个候选示例分别覆盖“继续”和“仅过渡”。
- 固定位置、主属性、副属性的期望成本：库存工作区先比较随机 / 固定位置的提升 / 母盘，再展示固定主属性和固定副属性的省母盘阶梯；固定副属性仍只作为极限毕业观察。
- 长期最优和当前提升是否冲突：示例盘面应显示当前补 6 号位与长期 5 号物伤目标存在冲突。

页面里的“验收总览”Tab 会把当前装备、候选胚子、调律策略三块答案合并成一张表；顶部“今日行动摘要”会先给出先刷什么、特殊资源怎么处理、候选胚子下一跳和长期提醒。命令 `gacha-gear-optimizer-acceptance` 和 `scripts/acceptance_report.ps1` 会用内置星徽·比利示例生成同样口径的 Markdown 报告，并附带随机 / 固定位置收益效率、固定主属性省母盘阶梯、固定副属性省母盘阶梯和胚子挡位概率解释。需要把验收变成可失败的命令时，可以加 `--check`；需要机器读取时，可以加 `--check-json reports/first_version_acceptance_checks.json`。

## 快速启动

```bash
pip install -e ".[dev]"
gacha-gear-optimizer
gacha-gear-optimizer-doctor
gacha-gear-optimizer-acceptance --output reports/first_version_acceptance.md --check
pytest
```

默认 `pytest` 运行快速单元 / 非 UI 回归 lane；重型 Streamlit AppTest UI 回归测试已标记为 `streamlit_ui`，需要单独运行时：

```powershell
pytest -m streamlit_ui
```

完整发布门禁：

```powershell
.\scripts\release_gate.ps1
```

需要把 Windows exe 构建和打包 smoke 也纳入门禁时：

```powershell
.\scripts\release_gate.ps1 -BuildPackage
```

release gate 会先跑 doctor、第一版验收、源码 PySide6 native app smoke 和默认 pytest lane，并把源码 smoke 结果写入 `reports\source_app_smoke_checks.json`、pytest JUnit XML 写入 `reports\pytest.xml`。`-BuildPackage` 默认构建已验证的 onedir 形态，并在打包 smoke 通过后继续验证 `reports\release_artifact_manifest.json` 和 exe 是否匹配，最后写出 `reports\first_version_readiness_checks.json` 汇总第一版可交付状态；readiness 默认读取 `reports\pytest.xml`，记录生成时间和参与汇总的证据文件路径，并校验验收 JSON、源码 smoke JSON、pytest report 和发布 exe 不早于各自覆盖的源码、测试、脚本、配置、示例和资源输入。跳过 pytest 的流程会显式跳过 pytest 证据，避免误用旧报告。只想复查已有 manifest 时：

```powershell
.\scripts\release_gate.ps1 -VerifyManifest
```

已有验收 JSON 和 release manifest 时，也可以只跑轻量交付聚合检查：

```powershell
gacha-gear-optimizer-readiness --acceptance-checks reports\first_version_acceptance_checks.json --app-smoke-checks reports\source_app_smoke_checks.json --manifest reports\release_artifact_manifest.json --json reports\first_version_readiness_checks.json
```

源码目录下，Windows 也可以直接运行：

```powershell
.\scripts\start_app.ps1
```

生成第一版验收报告和机器可读检查 JSON：

```powershell
.\scripts\acceptance_report.ps1
```

或双击：

```text
scripts/start_app.cmd
scripts/acceptance_report.cmd
scripts/release_gate.cmd
```

可选桌面窗口启动：

```powershell
pip install -e ".[dev,desktop]"
gacha-gear-optimizer-desktop --check
gacha-gear-optimizer-desktop --app-check
gacha-gear-optimizer-desktop --app-check-json reports\source_app_smoke_checks.json
gacha-gear-optimizer-desktop
```

源码目录下也可以运行或双击脚本：

```powershell
.\scripts\start_desktop.ps1 --check
.\scripts\start_desktop.ps1
```

```text
scripts/start_desktop.cmd
```

桌面入口是 PySide6 原生窗口。关闭窗口即退出应用；不会启动本地 HTTP 服务，也没有 Edge/Chrome app-window fallback。`gacha-gear-optimizer-desktop --check` 会检查 PySide6 runtime 和原生 UI 模块是否可用。`gacha-gear-optimizer` 和 `gacha-gear-optimizer-desktop` 是安装后的命令入口，前者保留 legacy Web，后者是主桌面入口。

可选生成 Windows exe：

```powershell
pip install -e ".[packaging]"
.\scripts\build_windows_app.ps1
```

构建脚本默认会先运行 `gacha-gear-optimizer-doctor`、第一版验收报告检查和源码 PySide6 app import smoke，避免资源、验收或原生 UI 导入问题被延后到 exe 启动时才暴露。确认本机环境已经检查过、只想重新打包时，可以加 `-SkipPreflight`。需要直接从打包脚本生成测试证据时，可以加 `-RunPytest`，它会在 PyInstaller 前跑默认 pytest lane 并写出 `reports\pytest.xml`。需要构建完成后立刻验证打包入口时，可以加 `-SmokeCheck`，脚本会对生成的 exe 执行 `--check` 和 `--app-check`。`-SmokeCheck` 成功且验收 / 源码 smoke 证据存在时，也会写出 `reports\first_version_readiness_checks.json`；如果同次构建启用了 `-RunPytest`，readiness 也会纳入这份 pytest 证据。如果 `-SkipPreflight` 导致这些证据不存在，脚本会明确提示跳过 readiness。
每次构建完成后会写出并自动验证 `reports/release_artifact_manifest.json`，记录版本、exe 路径、文件大小、SHA256、构建时间、onefile 状态、预检 / smoke 状态、smoke 超时上限和额外 PyInstaller 参数，确保发布记录和实际 exe 匹配。
需要单独验证 manifest 和 exe 是否匹配时：

```powershell
gacha-gear-optimizer-verify-release --manifest reports\release_artifact_manifest.json
```

默认输出：

```text
dist\gacha-gear-optimizer\gacha-gear-optimizer.exe
```

需要单文件时：

```powershell
.\scripts\build_windows_app.ps1 -OneFile
```

第一版发布优先使用默认 onedir 输出；`-OneFile` 适合额外分发验证。onefile 首次启动可能受解包和杀毒扫描影响，建议带 `-SmokeCheck -SmokeTimeoutSeconds 90` 单独验证，不把它作为默认发布门禁。

需要在构建后自动验证 exe 的 PySide6 runtime 和原生 UI 导入时：

```powershell
.\scripts\build_windows_app.ps1 -SmokeCheck
```

需要让打包脚本同时生成 pytest 证据时：

```powershell
.\scripts\build_windows_app.ps1 -RunPytest -SmokeCheck
```

PyInstaller 版本会把 `src`、`configs`、`examples` 和本地图标资源一起打包，并额外收集 PySide6 runtime。用户保存的套装方案、盘面模板和库存不会写入临时解包目录，打包版默认放在 `%LOCALAPPDATA%\gacha-gear-optimizer\user_data`，如果该目录不可写会退到系统临时目录。源码运行时仍默认写入项目内 `user_data`；需要自定义保存位置时，可以设置 `GEAR_OPTIMIZER_USER_DATA_DIR`。

如果安装后启动失败，先运行 `gacha-gear-optimizer-doctor`。它会检查 Python 版本、核心运行依赖、console script 声明、验收 / manifest / readiness 发布辅助模块、当前项目根目录、`app.py`、桌面入口、PySide6 UI 模块、Windows 启动 / 验收 / 打包 / release gate 脚本、配置 YAML、示例盘面、本地驱动盘图标目录，以及每个已配置套装图标文件是否存在且非空；同时会提示 PySide6 桌面运行时是否可用。缺少 PySide6 是 desktop extra 的 notice；需要运行桌面版时执行 `pip install -e ".[desktop]"`。需要手动指定项目根目录时，可以设置 `GEAR_OPTIMIZER_PROJECT_ROOT`。

## 当前边界

本项目不做 OCR、图片解析、联网查概率、伤害模拟、账号登录、数据库或云同步。所有装备和候选胚子都通过界面手动输入。
