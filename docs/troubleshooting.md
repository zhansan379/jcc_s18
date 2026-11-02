# 排错

## 先看 `_告警`

`scan.py` 输出里的 `_告警` 已经记录了大部分问题：OCR 不可用、VLM 回落失败、羁绊条数不足、商店名单不符、玩家行数不足、模块异常。先读它，再看 `_来源` 判断字段由谁产出。

## 常见现象

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 所有文本字段为空 | 没装 `rapidocr-onnxruntime`；或 `--backend ocr` 下 OCR 失败 | 装 OCR；或看 `_告警`；`hybrid` 会回落 VLM |
| 金币读成 `820` / `99` / `8` | 金币框左边界带进了图标；双框投票不一致 | 重标 `TIGHT["gold"]` / `GOLD_X0`，出裁剪预览 |
| 阶段/等级/经验格式不对 | 框偏了、UI 改版、分辨率变化 | 重标 `REGIONS` 与 `TIGHT` |
| 商店少卡/错位 | 商店 5 个紧框与卡片不匹配 | 重标 `TIGHT["shop"]` 的 5 段 |
| 羁绊只读到 0~2 条 | 面板布局变了、宽屏但未适配、面板未展开 | 看 `_告警`；重标 `traits.LAYOUTS`；确认 16:9 |
| 玩家列表少于 2 行 | 头像环颜色变化、列表被遮挡、慢速回退也失败 | 看 `_告警`；换备战阶段截图；重标 `player_hp.LAYOUTS` |
| 单位数量偏少 | 血条被遮挡/重叠、战斗特效干扰、底部 UI 过滤 | 备战阶段截图；检查 `board_units.find_bars` 阈值 |
| 星级全 1★ | 星级标记不在血条左侧 42px 内，或颜色阈值不匹配 | 看 `star_color`；核对雪佛龙颜色阈值 |
| 装备为空/错配 | 装备格黑边变化、图标库缺、分数低于 0.55 | 检查 `data/equipment_s18/`；看 `score` |
| 装备栏为空 | `wide` 布局（只有 16:9 栅格）或栅格错位 | 用 16:9；重标 `item_bench.GRID` |
| 符文全「未知」 | 图标不在库、形状阈值/gap 不够、底色不是深蓝 | 看 `top` 候选；补图标；核对 `MIN_SCORE/MIN_GAP` |
| `--names` 名字错 | VLM 识别错、缓存粘住错误、棋子太小 | 删 `data/hero_names_cache.json` 重试；改用 `--labels` 人工标注 |
| `--labels` 全判不出 | 标注与当前地图/宽高比不同、标注太少 | 用同源截图；补标注；看 `name_top` 候选 |
| VLM `HTTP401` | key 无效/未配置 | 设 `DASHSCOPE_API_KEY` |
| VLM `timeout` | `--budget` 太小、网络慢 | 增大 `--budget`；注意它只约束 VLM |
| `ModuleNotFoundError: rapidocr_onnxruntime` | 没装 OCR | 安装，或改用 `--backend vlm` |
| `ModuleNotFoundError: board_units` | 在错误目录 import `core` 模块 | 从仓库根跑 `scan.py`，或直接跑 `core/xxx.py` |
| 预览图对但 OCR 错 | `REGIONS` 对、`TIGHT` 不对 | 两套坐标分别校准，见 [calibration](calibration.md) |
| 宽屏大部分字段为空 | 只有 `player_hp`/`traits` 支持 wide | 用 16:9；或补其他模块的 wide 布局 |

## 推荐器

| 现象 | 原因 | 处理 |
|---|---|---|
| 候选阵容分数都很低（<0.45） | 当前棋盘本来就不像主流阵容、或单位名字缺失/错位 | 看 `missing_core` 与 `named_ratio`；不要硬套，考虑转型 |
| 只给 `save`，没有 `buy`/`roll` | 商店没有候选阵容单位、没名字、金币不够、或核心已齐 | 看 `shop_hits`、`missing_core`、`roll_gold` |
| `named_ratio` 为 0 | `scan.py` 没加 `--labels`/`--names` | 先生成带名字的 state；否则只做经济建议 |
| `Level` 建议不符合你的打法 | `config/strategy_rules.json` 的 `level_timing` 是默认约定 | 按版本/段位改配置，不要改代码 |
| 推荐和实际环境不符 | 27 套阵容是榜单主流，缺冷门/克制数据 | 当参考，不要当唯一答案 |
| 符文没有影响排名 | 符文未识别/不可信，或只是战力/装备类，和阵容节奏无关 | 看 `state.augments`、`augment_hits`；确认 `scan.py` 的 `强化符文` 有 name 且 reliable |
| `comps.json` 加载失败 | 静态库被移动/损坏 | 检查 `data/s18db/comps.json` |

推荐链路细节见 [modules/recommend](modules/recommend.md)。

## 宽屏说明

`pick_layout()` 在 `W/H > 2.0` 时启用 `wide`，但当前只有：

- `player_hp.py`：有 `wide`；
- `traits.py`：有 `wide`；
- `item_bench.py`：`GRID` 只有 `16_9`，wide 返回空；
- `board_units.py`：无 layout 分支；
- `ocr_extract.TIGHT` / VLM `REGIONS`：16:9 坐标。

README 里「按比例分两套坐标」只指前两处。宽屏截图请优先用 16:9 重截。

## `--budget` 的误解

`--budget` 是 VLM 请求的 deadline，不是整个 `scan.py` 的墙钟上限。OCR/CV 不受它约束；冷启动（模型加载 + 符文掩膜）总耗时可能超过 budget。

## 样例口径

`output/sample_result.json` / `sample_ocr_result.json` 是 2026-11-02 用当前代码对样例截图重跑的结果：

- `棋子.数量` 只数棋盘，`备战席` 单独给出；
- `_来源` 里 `ocr`/`cv` 是常态，VLM 只在回落时出现；
- 这次 hybrid 未触发 VLM，所以两份样例内容相同。

推荐样例是 `output/sample_state.json`（带名字的局面）和 `output/sample_plan.json`（Top 3 + actions）。它们用于验证字段口径，不是「正确决策」的 golden。

不要把它当 golden 逐字段比对；不同截图、不同分辨率结果会变。

## 相关文档

- [calibration](calibration.md)
- [backends](backends.md)
- [data](data.md)
- [modules/](modules/)
