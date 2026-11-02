# 文档索引

根目录 [README](../README.md) 只保留项目简介、快速开始和入口；细节按主题拆到本目录。

## 按目标阅读

| 我想…… | 先读 |
|---|---|
| 跑一张截图 | [README · 快速开始](../README.md#快速开始) |
| 理解整体流程 | [architecture](architecture.md) |
| 改 OCR / VLM / 回落逻辑 | [backends](backends.md) |
| 改固定框或换分辨率 | [calibration](calibration.md) |
| 改某个识别模块 | [modules/](#模块文档) 下对应文档 |
| 从截图推荐阵容/下一步 | [recommend](modules/recommend.md) |
| 用图形界面看推荐+识别结果 | [advisor](../advisor/README.md) |
| 查数据文件/图标库 | [data](data.md) |
| 用或重建 S18 静态库 | [s18db](s18db.md) |
| 搭环境、跑验证 | [development](development.md) |
| 排查识别失败 | [troubleshooting](troubleshooting.md) |
| 给 AI agent 的速查 | [AGENTS.md](../AGENTS.md) |

## 总览文档

| 文档 | 内容 |
|---|---|
| [architecture.md](architecture.md) | 端到端流水线、模块边界、输出结构、耗时 |
| [backends.md](backends.md) | OCR / VLM / hybrid 三种后端、校验规则、VLM 配置 |
| [calibration.md](calibration.md) | `REGIONS` / `TIGHT` 两套坐标、16:9 与 wide、校准步骤 |
| [data.md](data.md) | `data/` 资产清单、运行期依赖、图标与缓存、数据来源 |
| [s18db.md](s18db.md) | S18 静态库的用途、文件、字段、缺口、重建 |
| [development.md](development.md) | 环境、命令、代码约定、验证方式、硬编码路径 |
| [troubleshooting.md](troubleshooting.md) | 常见失败现象、原因与处理 |

## 模块文档

| 模块 | 文档 | 职责 |
|---|---|---|
| `core/board_units.py` | [modules/board-units.md](modules/board-units.md) | 血条 → 星级 / 位置 / 装备、备战席 |
| `core/player_hp.py` | [modules/player-hp.md](modules/player-hp.md) | 右侧玩家排名、血量、自己 |
| `core/traits.py` | [modules/traits.md](modules/traits.md) | 左侧羁绊面板 |
| `core/item_bench.py` | [modules/item-bench.md](modules/item-bench.md) | 最左侧装备栏 |
| `core/augments.py` | [modules/augments.md](modules/augments.md) | 强化符文图标定位与匹配 |
| `core/hero_names.py` | [modules/hero-names.md](modules/hero-names.md) | `--names`：VLM 认名字 + 缓存 |
| `core/hero_match.py` | [modules/hero-names.md](modules/hero-names.md#离线匹配--labels) | `--labels`：人工标注最近邻 |
| `core/ocr_extract.py` | [backends.md](backends.md#ocr-路径) | 文本字段紧框 OCR |
| `core/vlm_board_scan.py` | [backends.md](backends.md#vlm-路径) | VLM 调用、`REGIONS` 坐标 |
| `recommend.py` | [modules/recommend.md](modules/recommend.md) | 规则推荐器：Top 3 阵容 + 行动 |
| `core/comp_index.py` | [modules/recommend.md](modules/recommend.md) | `s18db` → 运行时索引 |
| `core/comp_match.py` | [modules/recommend.md](modules/recommend.md) | 当前局面 vs 阵容模板 |
| `core/economy.py` | [modules/recommend.md](modules/recommend.md) | 等级/存钱/搜牌/买卡建议 |
| `advisor/` | [../advisor/README.md](../advisor/README.md) | PyQt6 对局助手：推荐页 + 识别标注页 |
| `labeler/` | [modules/labeler.md](modules/labeler.md) | PyQt6 人工标注工具 |

## 相关文件

- [data/s18db/INDEX.md](../data/s18db/INDEX.md)：静态库完整字段说明。
- [data/s18db/GAPS.md](../data/s18db/GAPS.md)：数据缺口与补齐优先级。
- [labeler/README.md](../labeler/README.md)：标注器用法与数据格式。
- [advisor/README.md](../advisor/README.md)：对局助手（推荐页 + 识别标注页）用法、耗时与限制。
- [AGENTS.md](../AGENTS.md)：agent 工作约束与高危操作提醒。
