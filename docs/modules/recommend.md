# recommend：阵容与行动推荐

文件：

- `recommend.py`：CLI
- `core/comp_index.py`：`data/s18db` → 运行时索引
- `core/comp_match.py`：当前局面 vs 27 套阵容模板
- `core/economy.py`：等级/存钱/搜牌/买卡建议
- `config/strategy_rules.json`：可调节奏参数

## 定位

这是**规则推荐器**，不是最终答案：

- 用 `comps.json` 的阵容模板、`heroes.json` 的羁绊/费用、`traits.json` 的档位、`items.json` 的装备方案做匹配；
- 用 `augments.json` 把当前强化符文归到「刷新/经济/经验」风格，和阵容节奏做粗匹配；
- 用 `strategy_rules.json` 做经济/节奏判断；
- 输出 Top N、缺失单位、羁绊差距、候选动作；
- 不联网、不调用 VLM、不直接让 AI 读原始数据。

## 用法

```bash
# 一条命令：扫描 + 推荐 + 只输出摘要（推荐日常使用）
python recommend.py --image 截图.png --brief

# 需要落盘时
python recommend.py --image 截图.png --brief --save-state state.json --json plan.json

# 已有 state 时，不重复扫描
python recommend.py state.json
python recommend.py state.json --top 3 --json plan.json
python recommend.py state.json --rules config/strategy_rules.json
```

`--brief` 只输出：局面一行、Top1、缺核心、符文契合、行动、告警；完整候选/评分用 `--json` 落盘，不要直接打印整个 JSON。

样例：

- [output/sample_state.json](../../output/sample_state.json)：`scan.py --labels` 的局面。
- [output/sample_plan.json](../../output/sample_plan.json)：`recommend.py` 的完整输出。

> `--labels` 依赖 `data/hero_labels/`；标注不够时，推荐器仍能输出候选，但置信度会下降。没有名字时只给经济建议。

## 输入

直接使用 `scan.py --json` 的输出，重点字段：

| 字段 | 用途 |
|---|---|
| `阶段` / `等级` / `经验` / `金币` / `我的血量` | 经济与节奏 |
| `单位[]` | `name`（关键）、`star`、`area`、`items` |
| `商店` | 买卡/补阵容 |
| `羁绊` | 目标羁绊完成度；缺失时用单位反推 |
| `强化符文` | 当前符文风格（刷新/经济/经验）与阵容节奏是否匹配 |
| `装备栏` | 装备命中 |
| `棋子` | 校验/展示 |

单位名字会对齐到 `data/s18db/heroes.json` 的标准名；称号别名（如「翠神」→「艾翁」）也支持。

## 输出

```json
{
  "state": {"stage": "4-1", "level": 7, "gold": 55, "hp": 70,
            "named_ratio": 1.0, "named_units": 12, "units": 12},
  "recommendations": [
    {
      "title": "7峡谷魔沼蛙",
      "tier": "S",
      "score": 0.88,
      "confidence": 0.86,
      "missing_core": [],
      "missing_units": ["..."],
      "trait_gaps": [{"name": "峡谷野怪", "current": 5, "target": 7}],
      "shop_hits": ["魔沼蛙"],
      "item_hits": ["海克斯科技枪刃"],
      "augment_hits": [{"name": "DD街区", "fit": 1.0}],
      "augment_fit": 1.0,
      "reasons": ["核心 3/3 已有", "单位 8/9 已有", "符文契合：DD街区(1.0)"],
      "score_parts": {"core_units": 1.0, "units": 0.89}
    }
  ],
  "actions": [
    {"type": "buy", "priority": 1, "target": "魔沼蛙", "why": "商店有魔沼蛙，是候选阵容核心"},
    {"type": "save", "priority": 3, "why": "金币 55，当前利息 +5；血量安全时优先存钱"}
  ],
  "warnings": []
}
```

`score_parts` 用于调试/调权重，不要直接展示给玩家。

## 评分

权重在 `config/strategy_rules.json` 的 `weights`：

| 分项 | 默认权重 | 计算 |
|---|---:|---|
| `core_units` | 0.30 | 主 C / `equipOptions` 英雄的覆盖率 |
| `units` | 0.15 | 阵容全部单位的覆盖率 |
| `traits` | 0.20 | 目标羁绊的当前计数 / 目标计数，按目标人数加权 |
| `items` | 0.08 | 当前装备/装备栏与阵容推荐装备的交集 |
| `shop` | 0.10 | 商店 5 卡中属于该阵容的比例 |
| `meta` | 0.08 | `tier` + `top4Rate` + `winRate` |
| `economy` | 0.04 | `difficulty` 的轻惩罚 |
| `augments` | 0.05 | 当前符文风格 vs 阵容是「追三星/慢D」还是「运营上人口」 |

这套权重是**起始值**，不是从对局数据回归出来的。建议用真实截图标注后调整。

### 置信度

```
confidence = 0.15
           + 0.35 × named_ratio
           + 0.35 × score
           + 0.15 × 与下一名的差距
```

- `named_ratio` 是「有名字的单位 / 全部单位」。
- 没有名字时置信度被压到 0.35 以下。
- 最高候选分 <0.45 时会给「更适合当转型参考」的告警，而不是硬推。

## 行动规则

`core/economy.py` 输出这些类型：

| 类型 | 触发 |
|---|---|
| `level` | 当前等级低于阶段目标等级 |
| `stabilize` | 血量低于 `hp_danger` |
| `buy` | 商店出现候选阵容单位；核心优先 |
| `roll` | 等级已达标、金币 ≥ `roll_gold`、且候选还缺核心 |
| `save` | 血量安全且金币 ≥10；按利息提示 |

默认参数：

```json
{
  "level_timing": [{"stage":"2-1","level":4}, {"stage":"3-2","level":6},
                   {"stage":"4-1","level":7}, {"stage":"4-5","level":8},
                   {"stage":"5-1","level":9}],
  "hp_danger": 35,
  "roll_gold": 30,
  "interest_cap": 5,
  "min_named_ratio": 0.6
}
```

这些是**节奏约定**，不是 `s18db` 的数据事实；换版本/段位应调整。

## 已知限制

- **单位名字是硬前提**：`scan.py` 默认只给数量/星级，不给名字；需要 `--labels` 或 `--names`。没有名字时只做经济建议。
- **没有对手棋盘**：无法判断克制/对位；`GAPS.md` 也明确缺 comp 对局胜率。
- **没有连胜/连败、D 牌次数、海克斯历史**：节奏建议只能按阶段/金币/血量估算。
- **comps 没有显式成型等级/搜牌回合**：`level_timing` 是人工配置，不是数据推导。
- **阵容统计未按段位分桶**：`tier/top4Rate` 是混合池。
- **装备匹配只做名字交集**：还没有用 `item_recipes.json` 把散件组合成目标成装。
- **符文只做风格粗匹配**：把 `typeZh/desc` 归到「刷新/经济/经验」，再和阵容的 `追三星/运营` 标签比较；不解析具体数值收益、回合或叠加关系。`scan.py` 的符文识别不可信时不会参与评分。
- **站位建议未实现**：当前 `units.pos` 是归一化坐标，`comps` 是 0~27 格，需要额外网格映射。
- **AI 解释层未接入**：当前只输出结构化建议；后续可把 `recommendations + state` 压缩后交给 LLM，但必须做名字白名单校验。

## 下一步

1. 扩充 `data/hero_labels/`，提高 `named_ratio`。
2. 用 20~30 张截图人工标注「正确阵容/正确动作」，评估 Top-1/Top-3 和动作准确率。
3. 增加装备配方匹配（`item_recipes.json`）。
4. 细化符文适配：结合 `augments_tier.json` / `augment_stats.json`、符文回合和阵容核心装备/羁绊做更细评分。
5. 再做 AI 解释层，而不是让 AI 直接读原始 `s18db`。

## 相关文档

- [architecture](../architecture.md)
- [data](../data.md)
- [s18db](../s18db.md)
- [hero-names](hero-names.md)
