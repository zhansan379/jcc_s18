# S18 静态数据库（data/s18db）

金铲铲之战 S18 的静态知识库，供阵容推荐、D 牌概率、装备与强化检索使用。
全部文件为只读静态数据，由 `tools/build_s18db.py` 等脚本生成。

> 运行扫描器不需要本目录（只有 `core/hero_names.py` 读 `heroes.json` 做名字校验）。
> 2026-11-02 深度清理移出了 `raw/` 与 `images/`，详见 [`docs/s18db.md`](../../docs/s18db.md) 与 [`docs/data.md`](../../docs/data.md)。

## 数据来源与版本

| 来源 | 覆盖面 | 版本 |
|---|---|---|
| `jcc.datatft.com/comp/rank`（榜单）+ `jcc.datatft.com/comps`（`/team/list`） | 27 套阵容：分级、胜率、样本量、阵容码、站位、装备 | 18.5b / 2026-10-24 |
| `jcc.datatft.com/database`（资料库） | 弈子、羁绊、装备、强化符文、仙灵 | 18.5c / 2026-10-29 |
| `jcc.datatft.com/augment/tier`（`api.datatft.com/augment-tier/config`） | 246 条强化符文评级 S/A/B/C/D | 18.4 |
| `jcc.datatft.com/wisp-rules` | 181 条仙灵互斥规则 | 同左 |
| `jcc.datatft.com/rate` | 经验/利息/连胜/伤害表 | 同左 |

全部数据均为**金铲铲**口径（此前混入的云顶 TFT Lab 数据已移除）。

## 术语（重要）

| 站点叫法 | 数据字段 | 条数 | 说明 |
|---|---|---|---|
| 强化符文 / 强化果实 | `hexs18` → `augments.json` | 256 | 同一套东西。数据库 tab 叫「强化符文」，评级页口语叫「强化果实」。银/金/棱彩 × 2-1/3-2/4-2 |
| 仙灵 | `charms18` → `wisps.json` | 181 | 另一套机制：有类别（弈子/装备/商店…）、费用、前置条件、升级效果 |

> ⚠️ 两者**不是**同一样东西，字段结构完全不同，不要互相替代。

## 文件清单

| 文件 | 条数 | 说明 |
|---|---|---|
| `heroes.json` | 65 | 弈子：费用/羁绊/定位/射程/技能（正文+各星级数值）/基础数值/推荐装备 |
| `hero_skills_tags.json` | 65 | 技能语义标签（LLM 初稿）：伤害类型/目标形态/控制/召唤/标签 |
| `hero_skills_tags.md` | 65 | 上面这份的可读表格，方便抽检 |
| `traits.json` | 36 | 羁绊：档位阈值 + 成员 + **91/91 档位结构化 effects**（61 档含数值） |
| `traits_effects.md` | 91 | 上面这份 effects 的可读表格（抽检用） |
| `items.json` | 151 | 装备：散件/成装/光明装/奥恩神器/纹章/道具；131 件解析出数值属性，55 件带合成路径 |
| `item_recipes.json` | 55 | 合成路径（沿用 `data/EquipmentData.json`） |
| `augments.json` | 256 | **强化符文**：稀有度/回合/类型/描述/评级 + 真实样本（235 条）+ 图标路径（256 条） |
| `augment_stats.json` | 235 | dataj.cc 统计 + 图标映射（含 268 条图鉴的 id/name/icon） |
| `images/augments/` | 256 | **已移出（2026-11-02）**：强化符文图标（按 hexId 命名，200×200 PNG，9.8 MB）。需要时重跑 `tools/fetch_dataj_hex.py` 或从备份恢复 |
| `augments_tier.json` | 246 | 强化符文评级：S/A/B/C/D（JOC 冠军 TLG糕手雕妹） |
| `wisps.json` | 181 | **仙灵**：类别/费用/生效回合/前置条件/效果/升级效果 |
| `wisp_rules.json` | 181 | 仙灵互斥规则（12 条带互斥强化列表） |
| `comps.json` | 27 | 阵容：分级 + 胜率 + 站位棋盘 + 装备 + 过渡 + 社区备注 |
| `comps_summary.json` | 27 | 阵容排名摘要 |
| `shop_odds.json` | 9 级 | 商店概率（1~5 费 × Lv1~9）+ 卡池数量 |
| `economy.json` | — | 升级经验/回合金币/利息/连胜/阶段伤害/单位伤害 |
| `manifest.json` | — | 构建清单（来源、条数、文件大小） |
| `raw/jcc_comps/` | — | **已移出（2026-11-02）**：榜单与详情原始响应（`rank.json`、`strategy_<id>.json`、`extra_<id>.json`） |
| `raw/augment_tier/` | — | **已移出（2026-11-02）**：强化符文评级原始数据（`config_jcc.json` 评级码、`dom.tsv` 渲染后导出） |
| `raw/site-data-cn.json` | — | **已移出（2026-11-02）**：站点主数据包（AES 解密后的 5 个赛季数据，含 hexs/charms/equips） |

## 主要字段

**augments.json** — `augments[]`（强化符文）```
hexId, code(2 字符站内编号), key, name,
rarity(silver/gold/prismatic), rarityZh, rounds[2-1/3-2/4-2],
type[](标签 id), typeZh[经济/战力/装备/羁绊/专属/其他],
desc, img, tier(S/A/B/C/D，未评级为 null),
stats{sampleCount, playRate, avgPlacement, top4Rate, topRate, rounds[], roundStats[]},
datajHexId, iconFile
```
`stats` 来自 dataj.cc/hex 的 235 条统计，含 3-2 / 4-2 分阶段表现；
`iconFile` 指向 `images/augments/<hexId>.png`，但 `images/` 已在 2026-11-02 清理中移出；要恢复图标请重跑 `tools/fetch_dataj_hex.py` 或从备份恢复。扫描器 `core/augments.py` 不使用这里，使用 `data/augmenticons_s18/`。
图标与统计的匹配：先按中文名，再按图标名（slug），最后用 12 条别名表（如 秘法帮派→窃贼帮派、纹章树→羁绊树、嘀嘀街区→DD街区）。

**wisps.json** — `wisps[]`（仙灵）
```
key, name, category(Shop/Combat/Risky/Champion/GoldXP/Item/Misc),
tier(1/2/3), cost, rounds[], requires[], effect, effectText,
upgrade{cost, effect}, mutex[], mutexCondition
```

**comps.json** — `comps[]`
```
id, tier(S/A/B/C/D), title, titleApi[], mainHeroId, mainHeroName, emblemTrait,
stats{playRate, winRate, top4Rate, avgPlace},
score, tftCode, strategyId,          # 来自 /team/list
difficulty(1~3), tags[],
core, open, earlyDesc, midDesc, finalDesc,
board{units[], extras[], hexs[], error},
earlyBoard{units[], hexs[], error},
equipOptions[{heroId, equips[[id,id,id], ...]}],
jccCode, conditions, updateTime,
tips[{desc, type, tags, author, like, time}]
```
`board.units[]`：`id, name, slot(0~27), row(slot//7), col(slot%7), stars, isMain, equips[{id,name}]`
`stars=null` 表示站点未标注（渲染时也不显示星标，通常按 2 星理解）。
`meta.sampleCount` = `/team/list` 返回的 `count`（统计窗口内对局总数，当前 814,416）；
每套阵容的估算场次 = `playRate × sampleCount`（`playRate` 为每局使用率）。

**items.json** — `items[]`
```
id, name, type(散件/成装/光明装/奥恩神器/纹章/道具), typeRaw, code, key,
effect, effectText,
stats[{stat(AD/AP/HP/ARMOR/MR/AS/CRIT/CRITMULT/MANAREGEN/DA/SV/DR), statKey, value, percent}],
recipe[{id, name}]          # 只有 55 件有（39 成装 + 16 纹章）
```
`stats` 来自站点的 `effectAttr`（成装/光明/奥恩）或 `effect`（散件），131/151 件可解析；
剩下的 20 件是冠冕/纹章/药水/宝箱这类本来就没有数值的。
`recipe` 来自项目原有 `data/EquipmentData.json`，按中文名/别名对齐到站点 `equipId`。

**traits.json** — `traits[]````
key, name, type(种族/职业), code,
breakpoints[{style(1~4), unitCount(激活阈值), effect(文本), stats[]}],
unitCount(成员数), units[]
```
`stats[]` = `{stat, statKey, value, percent}`，是 `effects` 里 kind=stat 的子集（保持旧结构兼容）。
`effects[]` 由 `tools/trait_effects.py` 解析，覆盖 **91/91 档**，共 11 种 kind：

```
stat      {stat, statKey, value, percent}        属性数值（61 档有）
dot       {type: burn/true/bleed, value}         持续伤害
debuff    {type: wound/shred_armor/shred_mr, value, duration}
gold      {value}                                获得金币
unit      {name}                                 获得/召唤单位
slot      {scope: shop/board, value}             引燃商店栏位 / 占用棋盘位
teamSize  {value}                                最大队伍规模
execute   {interval}                             处决
resource  {name, value, trigger}                 魔女精粹这类资源
mechanic  {key, note}                            悬赏令/月相/种子/兽灵赐福等机制
counter   {trait, value}                         为某羁绊提供计数
```

**hero_skills_tags.json** — `skills[]`（技能语义，LLM 初稿）
```
id, hero, cost, role, traits[], skill, mana,
damageType(magic/physical/true/mixed/none),
targeting(single/aoe/line/multi/self/ally/summon),
cc[{type, value, duration}],        # stun/knockup/taunt/slow/sleep/shred_armor/shred_mr/burn/wound/ignite
utility[],                          # shield/heal/buff_as/buff_ad/buff_ap/damage_reduction/cleanse/untargetable/execute/mana_regen
summon(bool), scaling(AP/AD/HP/none), tags[], note
```
> 由 `tools/tag_hero_skills.py` 生成，规则来自技能原文，**未经人工逐条确认**，改完重跑即可。

**heroes.json** — `heroes[]````
id, name, title, cost, role, roleDesc, range,
traits[{name, icon, type}],
skill{name, mana, startMana, maxMana, description, breakdown[{label, array}], starScaling[]}
stats{hp, attackDamage, armor, magicResist, attackSpeed, crit, attackRange, mana, startMana}
recommendedEquips[{id, name}], roleRecommendedEquips[{id, name}]
```
`skill.starScaling[]`：`{label, percent, starCount, byStar{"1":x,"2":y,...}}`，
由 `breakdown[].array` 的 `[1/2/3(/4)]` 原文拆分；1~2 费 4 个值（4 星），3 费以上 3 个值。
覆盖 156/164 行，剩下 8 行本来就没有数组（如「持续时长：5.0」）；易没有可拆分数值。

**shop_odds.json**
```
poolSizeByCost {1:30, 2:25, 3:18, 4:10, 5:9}, shopSlots: 5,
byLevel[{level, oddsPct{1..5}, oddsRaw{1..5}}]
```

**augments_tier.json** — `levels[]`
```
name, tier(S/A/B/C/D), rarity, rarityZh, hexId, key, rounds[], typeZh[], desc
```

## 已知数据缺陷

- 榜单详情接口对 `16292`、`16264` 返回空数据（已下架），最终为 27 套。
- 部分阵容棋盘里会出现 `999001`~`999004` 占位单位（站点前端也没有对应中文名），已单独放在 `board.extras`。
- `wisp_rules.json` 只有 12 条仙灵带互斥强化（站点页面本身只覆盖这些）。
- `augments_tier.json` 有 1 条重复映射（`DA_TradeSector`）：「嘀嘀街区加强版」与站内「DD街区+」不同名。
- 256 个强化符文里 10 个站点未评级。
- 站点不给样本量（局数），只给 playRate / top4 / win，且未按段位分桶。
- 配方只有 55 条（39 成装 + 16 纹章），来自项目原有 `data/EquipmentData.json`；已按中文名/别名合并进 `items.json` 的 `recipe` 字段（100% 对齐）。

## 重新生成

```bash
python tools/fetch_jcc_comps.py     # 阵容榜单 / 详情 → comps.json + raw/jcc_comps
python tools/fetch_augment_tier.py  # 强化符文 + 评级
python tools/fetch_dataj_hex.py     # dataj 统计 + 符文图标 → augment_stats.json + images/augments
python tools/build_s18db.py         # 其余静态表与清单
```

`build_s18db.py` 依赖：

- `D:\Download\browserDownload` 下的原始导出文件（`jcc_s18_*.json`、`h5-data-cn-18.json`）；
- `raw/site-data-cn.json`；
- 已生成的 `augments.json`、`augments_tier.json`、`comps.json`。

`raw/` 与 `images/` 已在 2026-11-02 清理中移出；重建前需从备份恢复（`C:\Users\feng1\AppData\Local\Temp\jcc_s18_cleanup_20261102\`）或重新导出。重建会联网并覆盖现有 JSON，除非明确需要不要运行。
