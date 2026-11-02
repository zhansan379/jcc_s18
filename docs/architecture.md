# 架构与流水线

## 目标

输入一张金铲铲之战（PC 模拟器）对局截图，输出结构化局面：

```
阶段 / 等级 / 经验 / 金币 / 商店[5] / 棋子 / 玩家排名 / 我的血量
/ 单位（星级+位置+装备）/ 羁绊 / 装备栏 / 强化符文
/ _来源 / _耗时 / _告警
```

主体在本地做 CV/OCR；VLM 只用于文本校验失败回落、`--no-units` 时的棋盘数量，以及可选的棋子命名。

## 端到端流程

```
截图
 ├─ 文本字段（core/ocr_extract.py）
 │    └─ 固定紧框 → RapidOCR rec-only → scan.py:VALIDATORS
 │         └─ 不通过 → VLM 回落（hybrid/vlm）
 │
 ├─ 棋盘单位（core/board_units.py）
 │    └─ 绿血条 → 星级颜色 / 位置 / 装备模板匹配
 │
 ├─ 右侧玩家（core/player_hp.py）
 │    └─ 橙色头像环 → 逐行 OCR 名字 + 血量 → 排名 / 自己
 ├─ 左侧羁绊（core/traits.py）
 │    └─ 逐行 OCR name / count / tiers
 ├─ 装备栏（core/item_bench.py）
 │    └─ 左侧竖排栅格 → 空位判定 → 装备匹配
 ├─ 强化符文（core/augments.py）
 │    └─ 深蓝底定位 → 二值形状 IoU
 └─ 可选命名
      ├─ --labels → core/hero_match.py（离线最近邻）
      └─ --names  → core/hero_names.py（缓存 + 一次 VLM）
```

`scan.py` 是唯一编排入口；各模块可以单独 import，但不负责互相调度。

## 模块边界

| 文件 | 负责 | 主要输出 |
|---|---|---|
| `scan.py` | 参数、编排、校验、回落、汇总 | 最终 JSON |
| `core/vlm_board_scan.py` | VLM 调用、`REGIONS` 坐标、裁剪 | VLM 原始文本 |
| `core/ocr_extract.py` | 文本字段紧框 OCR | 阶段/等级/经验/金币/商店 |
| `core/board_units.py` | 血条、星级、装备、棋盘/备战席 | `单位[]` |
| `core/player_hp.py` | 玩家列表、血量、自己 | `玩家排名[]`、`我的血量` |
| `core/traits.py` | 羁绊面板 | `羁绊[]` |
| `core/item_bench.py` | 最左装备栏 | `装备栏[]` |
| `core/augments.py` | 强化符文定位与匹配 | `强化符文[]` |
| `core/hero_names.py` | VLM 命名 + 本地缓存 | `单位[].name` |
| `core/hero_match.py` | 人工标注最近邻 | `单位[].name` |
| `recommend.py` | 局面 → 阵容/行动 | 推荐 JSON |
| `core/comp_index.py` | `s18db` → 运行时索引 | 阵容/英雄/装备索引 |
| `core/comp_match.py` | 局面 vs 阵容模板（含符文风格） | Top N + 缺失项 |
| `core/economy.py` | 等级/存钱/搜牌/买卡 | 行动列表 |

模块细节见 [modules/](modules/)。推荐链路见 [recommend](modules/recommend.md)。

## 输出结构

| 字段 | 类型 | 说明 |
|---|---|---|
| `阶段` | `"2-6"` | 回合 |
| `等级` | int 1~11 | 人口等级 |
| `经验` | `"4/10"` | 当前/上限 |
| `金币` | int 0~999 | 金币 |
| `商店` | 长度 5 的数组 | 英雄名 / 事件卡文字 / `null` |
| `棋子` | `{数量, 备战席}` | 棋盘与备战席数量；CV 产出 |
| `玩家排名` | `[{rank,name,hp,is_self}]` | 血量降序 |
| `我的血量` | int / null | 自己那一行 |
| `单位` | `[{star,star_color,area,pos,box,items}]` | 血量条级别的单位 |
| `羁绊` | `[{name,count,tiers,active}]` | 左侧面板 |
| `装备栏` | `[{name,score,box}]` | 最左侧竖排 |
| `强化符文` | `[{box,name,score,reliable,top}]` | 候选 + 是否可信 |
| `_来源` | dict | 每个字段由 `ocr`/`vlm`/`cv`/`cache`/`label` 产出 |
| `_耗时` | dict | 各阶段毫秒 + `total_ms` + `触发回落` |
| `_告警` | string[] | 校验失败、名单不符、模块异常 |
| `_名字统计` | dict | 仅 `--names`/`--labels` 时出现 |

样例：[output/sample_result.json](../output/sample_result.json)（`--backend hybrid`，2026-11-02 用当前代码重跑）。这次 OCR 全部通过，未触发 VLM，所以 `_来源` 里只有 `ocr`/`cv`。

## 关键设计

1. **固定分区**：5 个 `REGIONS` 百分比框，与分辨率无关，但依赖 16:9 UI 布局。见 [calibration](calibration.md)。
2. **OCR 只跑识别网络**：坐标写死，跳过 det 网络，单行约 80ms；代价是框必须精确。
3. **CV 优先**：棋盘数量、星级、装备、玩家行、符文都先走颜色/模板规则，比 VLM 快且可解释。
4. **VLM 只兜底**：文本字段校验不过才回落；棋盘默认不问 VLM；`--names` 是实验性开关。
5. **单一坐标源**：`core/vlm_board_scan.py:REGIONS` 同时供 VLM 裁剪和预览脚本使用；OCR 的 `TIGHT` 是第二套独立紧框。

## 实测耗时

1919×1097 截图，单进程、模型已加载：

| 环节 | 耗时 | 做法 |
|---|---|---|
| 文本字段 | ~154ms | 固定框 + rec-only |
| 玩家列表 | ~279ms | 橙色头像环 + 逐行 rec-only（回退 det ~2s） |
| 棋盘单位 | ~244ms | 纯 CV |
| 羁绊面板 | ~198ms | 逐行 rec-only |
| 装备栏 | ~100ms | 黑边切格 + 模板匹配 |
| 强化符文 | ~153ms | 深蓝底 + 形状 IoU（首次建掩膜 ~1.6s） |
| **合计** | **~1.16s** | 墙钟约 1200ms |

冷启动首张约 3.7s：RapidOCR 模型加载 ~0.9s，符文参考掩膜 ~1.6s。三个 OCR 模块共用同一个 `RapidOCR` 实例，模型只加载一次。数字随机器和截图变化，仅作量级参考。

## 下游推荐（可选）

`scan.py` 只负责把截图变成局面；推荐是独立的一层：

```text
state.json
  → comp_index（s18db: comps / heroes / traits / items）
  → comp_match（核心单位 / 羁绊 / 装备 / 商店 / 符文风格 / meta 评分）
  → economy（等级 / 存钱 / 搜牌 / 买卡）
  → Top 3 + 行动 + 告警
```

入口是 `recommend.py`，不修改 `scan.py` 的输出。详细评分、规则参数和限制见 [modules/recommend.md](modules/recommend.md)。

推荐器最大前提是**单位名字**：默认 `scan.py` 只给数量/星级，没有名字时只能做经济建议。名字来源见 [hero-names](modules/hero-names.md)。

## 进一步阅读

- [backends](backends.md)：三种后端与校验规则。
- [calibration](calibration.md)：坐标与宽高比。
- [data](data.md)：运行期依赖哪些数据。
- [modules/recommend](modules/recommend.md)：阵容/行动推荐。
