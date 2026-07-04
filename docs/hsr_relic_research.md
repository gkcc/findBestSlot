# 崩铁遗器概率与合成口径调研

日期：2026-07-05

## 当前结论

- 星铁遗器需要区分外圈遗器和位面饰品：头部、手部、躯干、脚部只应使用外圈遗器套装；位面球、连结绳只应使用位面饰品套装。
- 常规配装硬约束以 4+2 为主：外圈 4 件套 + 位面 2 件套。2+2+2 或其它混搭应保留入口，但不作为默认星铁模板。
- 遗器合成没有“随机 1-6 位置”的策略入口，当前 HSR 配置关闭 `random_position_actions`，只生成固定位置及其主/副属性锁定策略。
- 当前版本的定向合成高级素材可按统一“自塑尘脂”口径建模：固定主属性 1；固定主属性 + 1 个副属性总计 2；固定主属性 + 2 个副属性总计 5。
- 自塑尘脂机会成本按用户提供的游戏内兑换口径配置：1 个自塑尘脂 = 800 残骸；普通合成 1 次 = 100 残骸；因此 1 个自塑尘脂折算为 8 次普通固定位置合成。该折算只用于“特殊资源全局边际 EV”的值不值得花判断，不参与 Action EV 原始排序。
- 主属性概率和副属性权重没有在官方更新说明里找到完整表；当前配置使用 Wiki/Fandom 的 `Relic/Stats` 表作为社区来源。
- 5 星遗器初始副属性是 3-4 条；初始 3/4 的精确概率未找到官方来源。当前 `hsr_default` 继续使用社区常见 80/20 假设，并在配置 notes 中标明。

## 已落配置

- `configs/games/hsr.yaml`
  - 接入 2026-07-05 从中文 Wiki 结构化字段整理的 60 套文本素材：32 套隧洞遗器、28 套位面饰品。
  - 增加 `position_set_names`，硬限制外圈/内圈位置。
  - 移除脚部“击破特攻”主属性。
  - 将主属性概率从均匀占位改为调研口径。
  - 将副属性抽取权重从全 1 改为调研口径。
- `configs/probabilities/hsr_default.yaml`
  - 增加自塑尘脂 1/2/5 口径：
    - `tuner_per_fixed_main_attempt: 1`
    - `core_fixed_substat_1_attempt: 1`
    - `core_fixed_substat_2_attempt: 4`
    - 因此总高级素材分别为 1、2、5。
  - 增加残骸机会成本配置：
    - `remains_per_fixed_position_attempt: 100`
    - `self_modeling_resin_remains_cost: 800`
    - `advanced_material_equivalent_fixed_position_attempts: 8`

## 来源与边界

- HoYoverse 3.5 更新说明：3.5 后「遂愿尘脂」合并至「自塑尘脂」，仅需消耗相应数量自塑尘脂定向主副属性。
  - 页面：[Version 3.5 "Before Their Deaths" Update Honkai: Star Rail | HoYoLAB](https://www.hoyolab.com/article/40516796)
- HoYoverse 3.5 更新说明二次转载/镜像文本确认：此前定向 2 条副属性为 1 自塑 + 4 遂愿，3.5 后简化为直接消耗 5 自塑；1 条副属性对应总消耗 2 自塑。
- Fandom `Relic/Stats`：提供主属性分布和副属性权重表。该来源是社区百科，不是官方概率公告；页面自身也说明主属性概率来自 user-compiled data。
  - 页面：[Relic/Stats | Honkai: Star Rail Wiki | Fandom](https://honkai-star-rail.fandom.com/wiki/Relic/Stats)
- 中文 Wiki `遗器图鉴` 页面与 Semantic MediaWiki API：提供当前 60 套遗器/位面饰品名称、分类与套装效果文本；页面显示 60 套，其中隧洞遗器 32 套、位面饰品 28 套。本轮只写入文本，不下载或内置图片。
  - 页面：[遗器图鉴 - 崩坏：星穹铁道WIKI_BWIKI_哔哩哔哩](https://wiki.biligame.com/sr/%E9%81%97%E5%99%A8%E5%9B%BE%E9%89%B4)
  - API 查询口径：`api.php?action=ask&query=[[分类:遗器]]|?名称|?类别|?两件套效果|?四件套效果|?实装版本|limit=1000`
- Honey Hunter 4.4 页面：BWIKI 当前对 `坠星启航地` 和 `寰宇生研院` 的 `两件套效果` 字段为空；为避免 UI 出现半截套装，当前暂用 Honey Hunter 的文本补齐这两套效果。该来源属于 fan database / beta data，后续应以官方或 BWIKI 补全文本复核。
  - 页面：[坠星启航地](https://starrail.honeyhunterworld.com/land-of-the-starfall-voyage-relic_set/?lang=CHS)
  - 页面：[寰宇生研院](https://starrail.honeyhunterworld.com/universe-shrinker-lab-relic_set/?lang=CHS)
- 自塑尘脂 = 800 残骸、普通合成 = 100 残骸为用户提供的游戏内口径；当前配置将该口径落为 `advanced_material_equivalent_fixed_position_attempts: 8`。

## 已知素材边界

- `坠星启航地` 和 `寰宇生研院` 的效果文本来自 Honey Hunter，待官方或 BWIKI 补全后复核。
- 当前没有接入本地授权图片；UI 使用文字和 fallback 展示。

## 不确定性结论

- 官方公告没有提供完整主属性概率、副属性抽取权重或初始 3/4 副属性概率表；当前配置不能声称“官方概率”，只能声称“社区调研概率”。
- 主属性概率和副属性权重目前采用 Fandom / CN community user-compiled data 口径；如果后续能从客户端数据或官方公告取得更权威表，应替换 `configs/games/hsr.yaml`。
- 初始 3/4 副属性概率暂用社区常见 80/20 假设；这是显式假设，不作为官方结论。
- 自塑尘脂每月限量会影响主观资源价值；当前折算只按残骸兑换机会成本，不自动加入“限量稀缺溢价”。
