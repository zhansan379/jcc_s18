# 后端：OCR / VLM / hybrid

## 三种模式

| backend | 文本字段 | 棋盘数量 | 网络 | 适用 |
|---|---|---|---|---|
| `ocr` | 本地 RapidOCR | CV（默认）；`--no-units` 时 `null` | 否 | 离线 |
| `vlm` | 云端 qwen3-vl-plus | CV（默认）；`--no-units` 时 VLM | 是 | 文本 OCR 不稳时 |
| `hybrid`（默认） | OCR，失败才 VLM | CV（默认）；`--no-units` 时 VLM | 失败时 | 日常 |

> 棋盘数量默认三种后端都由 `core/board_units.py` 的 CV 产出，不是 OCR 读出来的。只有 `--no-units` 且 backend 为 `vlm`/`hybrid` 时才让 VLM 数数量；`--backend ocr --no-units` 则保持 `null`。

`hybrid` 的并行关系：

```
OCR 文本字段 ──┐
               ├─ 校验 → 失败字段再请求 VLM
棋盘 CV ───────┘（默认不与 VLM 并发，因为 CV 已够用）
```

> `--no-units` 在 `hybrid`/`vlm` 下会改走 VLM 数棋盘数量；想完全离线请用 `--backend ocr`。

## 文本字段校验

`scan.py:VALIDATORS`：

| 字段 | 规则 |
|---|---|
| 阶段 | `^\d+-\d+$` |
| 等级 | 1 ~ 11 的整数 |
| 经验 | `^\d+/\d+$` |
| 金币 | 0 ~ 999 的整数 |
| 商店 | 长度 5，至少 3 项非空 |

额外两道保护：

- **金币双框投票**：`GOLD_X0=(0.44, 0.52)` 两个左边界各读一次，结果一致才采信，否则判失败回落 VLM。金币框多带 2px 图标会读成 `820`/`99`。
- **商店名单核对**：结果与 `data/HeroData.json` 的 65 个英雄名比对，不在名单里的进 `_告警`（通常是事件卡，如「拼一把的小！」）。

## OCR 路径

实现：`core/ocr_extract.py`

- 先按 `REGIONS` 裁出 5 个分区，再在分区内用 `TIGHT` 紧框裁文字。
- `use_det=False, use_cls=False`：跳过检测/方向分类，只跑识别。
- `_region_array` 把 PIL 图转成 RapidOCR 需要的 BGR numpy。
- `get_ocr()` 单例；`player_hp`、`traits` 也复用它，避免重复加载模型。
- 紧框比例写死，换分辨率/UI 必须重标，见 [calibration](calibration.md)。

## VLM 路径

实现：`core/vlm_board_scan.py`

- OpenAI 兼容接口：`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- 模型：`qwen3-vl-plus`
- `temperature=0`，`max_tokens` 按分区卡死，避免长输出。
- API key：只从环境变量 `DASHSCOPE_API_KEY` 读取，**仓库不内置任何 key**；没设置时 VLM 调用直接返回 `no-key`，`--backend ocr` 不受影响。
- 每个分区单独裁剪、缩放到 `scale`、最长边 900px、JPEG q82，再 base64。
- `deadline` 是单次请求的剩余预算；超时直接返回错误字符串，不重试。
- `parse_json` 容错 Markdown 代码围栏包裹和前后杂字。

`REGIONS` 的 5 个框：

| 名称 | 内容 | prompt 输出 |
|---|---|---|
| `stage` | 回合 | 纯文本 `2-6` |
| `level_exp` | 等级+经验 | `{"level":4,"exp":"4/10"}` |
| `gold` | 金币 | 整数 |
| `shop` | 商店 5 卡 | 长度 5 的 JSON 数组 |
| `board` | 棋盘 | `{"own":数量}` |

## 实测对比

同 4 个纯文本区域：

| 方案 | 回合 | 等级+经验 | 金币 | 商店 5 张 | 端到端 |
|---|---|---|---|---|---|
| VLM（5 请求并行） | 630ms | 1009ms | 1684ms | 1259ms | **1.76s** |
| OCR 检测+识别 | 1640ms | 2015ms | 1577ms | 6799ms | **13.5s** |
| OCR 仅识别（紧框） | 172ms | 438ms | 287ms | 437ms | **0.56s** |

结论：det 网络是瓶颈；坐标本来固定，直接喂紧框只跑识别即可。

原始对比数据：[output/bench_ocr_vs_vlm.json](../output/bench_ocr_vs_vlm.json)。

## 失败与回落

| 现象 | 处理 |
|---|---|
| OCR 未安装 / 导入失败 | `_告警`；`ocr` 后端返回空字段；`hybrid` 全部回落 VLM |
| 金币两次不一致 | 判失败，回落 VLM |
| 阶段/等级/经验格式不对 | 回落 VLM |
| 商店不足 3 项 | 回落 VLM |
| VLM 超时 / HTTP 错误 | `_告警`，保留 OCR 结果（若有） |
| 商店含名单外文字 | 保留结果，写 `_告警` |

`--budget` 只约束 VLM 请求，不限制 OCR/CV；冷启动总耗时可能超过 budget。

## 相关文档

- [architecture](architecture.md)
- [calibration](calibration.md)
- [modules/hero-names](modules/hero-names.md)（`--names` 也走 VLM）
