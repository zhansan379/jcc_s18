# S18 静态库（data/s18db）

完整字段说明：[data/s18db/INDEX.md](../data/s18db/INDEX.md)  
数据缺口与优先级：[data/s18db/GAPS.md](../data/s18db/GAPS.md)

## 定位

金铲铲之战 S18 的只读静态知识库，供阵容推荐、D 牌概率、装备/强化检索使用。**扫描器 `scan.py` 本身不依赖它**；当前读取它的代码是：

- `core/hero_names.py`：`heroes.json` → 65 个英雄名 + `title` 称号别名（`--names` 校验）。
- `recommend.py` / `core/comp_index.py`：`comps.json`、`heroes.json`、`traits.json`、`items.json`、`augments.json` → 阵容匹配与符文风格索引。

其余文件是给后续推荐/分析用的静态数据。

## 数据来源与版本

| 来源 | 覆盖面 | 版本 |
|---|---|---|
| `jcc.datatft.com/comp/rank` + `/comps` | 27 套阵容：分级、胜率、样本量、阵容码、站位、装备 | 18.5b / 2026-10-24 |
| `jcc.datatft.com/database` | 弈子、羁绊、装备、强化符文、仙灵 | 18.5c / 2026-10-29 |
| `jcc.datatft.com/augment/tier` | 246 条强化符文评级 S/A/B/C/D | 18.4 |
| `jcc.datatft.com/wisp-rules` | 181 条仙灵互斥规则 | 同左 |
| `jcc.datatft.com/rate` | 经验/利息/连胜/伤害表 | 同左 |

全部为**金铲铲**口径；云顶 TFT Lab 数据已移除。

## 术语

| 站点叫法 | 文件 | 条数 | 说明 |
|---|---|---:|---|
| 强化符文 / 强化果实 | `augments.json` | 256 | 同一套东西；银/金/棱彩 × 2-1/3-2/4-2 |
| 仙灵 | `wisps.json` | 181 | 另一套机制：类别、费用、前置条件、升级效果 |

两者字段结构完全不同，**不要互相替代**。

## 主要文件

| 文件 | 条数 | 说明 |
|---|---:|---|
| `heroes.json` | 65 | 费用/羁绊/定位/射程/技能/数值/推荐装备 |
| `hero_skills_tags.json` | 65 | 技能语义标签（LLM 初稿，未逐条人工确认） |
| `traits.json` | 36 | 档位阈值 + 成员 + 91/91 档结构化 effects |
| `items.json` | 151 | 散件/成装/光明/奥恩/纹章/道具；131 件有数值，55 件有配方 |
| `item_recipes.json` | 55 | 合成路径 |
| `augments.json` | 256 | 强化符文：稀有度/回合/类型/描述/评级/统计/图标路径 |
| `augment_stats.json` | 235 | dataj.cc 统计 + 图标映射 |
| `augments_tier.json` | 246 | S/A/B/C/D 评级 |
| `wisps.json` | 181 | 仙灵 |
| `wisp_rules.json` | 181 | 仙灵互斥规则 |
| `comps.json` | 27 | 阵容：分级/胜率/站位/装备/过渡/备注 |
| `comps_summary.json` | 27 | 阵容排名摘要 |
| `shop_odds.json` | 9 级 | 商店概率 + 卡池 |
| `economy.json` | — | 经验/利息/连胜/阶段伤害 |
| `manifest.json` | — | 构建清单 |

## 本次清理后的变化

2026-11-02 深度清理移出了：

- `data/s18db/raw/`：原始响应和导出，重建时需要；
- `data/s18db/images/augments/`：256 张按 hexId 命名的图标，与 `data/augmenticons_s18/` 大量重复。

影响：

- `augments.json` 的 `iconFile` 字段仍指向 `images/augments/<hexId>.png`，但文件已不在；如果要用这些图标，重跑 `tools/fetch_dataj_hex.py` 或从备份恢复。
- `augment_images_index.json` 是符文 id → 名称/稀有度/回合/描述的元数据索引，不依赖图片文件，保留。
- `manifest.json` 的 `files` 只统计主要 JSON，不含图片，因此不受影响。
- 扫描器 `core/augments.py` 不使用 `s18db/images`，只使用 `data/augmenticons_s18/` + `augmenticons_ingame/`。

备份位置：`C:\Users\feng1\AppData\Local\Temp\jcc_s18_cleanup_20261102\`。

## 重建

```bash
python tools/fetch_jcc_comps.py      # 阵容榜单/详情 → comps.json + raw/jcc_comps
python tools/fetch_augment_tier.py   # 强化符文/评级 → augments*.json
python tools/fetch_dataj_hex.py      # dataj 统计 + 图标 → augment_stats.json + images/augments
python tools/build_s18db.py          # 汇总其余表与 manifest
```

`build_s18db.py` 依赖：

- `D:\Download\browserDownload` 下的导出文件（`jcc_s18_*.json`、`h5-data-cn-18.json`）；
- 已生成的 `augments.json`、`augments_tier.json`、`comps.json`；
- `raw/site-data-cn.json`（清理后需恢复备份或重新导出）。

重建会联网并覆盖现有 JSON；除非明确需要，不要运行。

## 已知缺陷

- 榜单接口对 `16292`、`16264` 返回空数据（已下架），最终 27 套。
- 部分阵容含 `999001~999004` 占位单位，放在 `board.extras`。
- `wisp_rules.json` 只有 12 条带互斥强化。
- `augments_tier.json` 有 1 条重复映射（`DA_TradeSector`）。
- 256 个强化符文里 10 个未评级。
- 阵容统计未按段位分桶，只有混合池。
- 技能标签是规则/LLM 初稿，未逐条人工确认。

更多见 [GAPS.md](../data/s18db/GAPS.md)。

## 相关文档

- [architecture](architecture.md)
- [modules/hero-names](modules/hero-names.md)
- [data](data.md)
