# AGENTS.md — jcc_s18

金铲铲之战（仅 PC 模拟器，不覆盖云顶 PC）截图 → 结构化 JSON。本地 CV/OCR 为主，VLM 兜底。

## 先读哪里

- [`docs/README.md`](docs/README.md)：文档总索引（按目标/模块/主题）。
- [`README.md`](README.md)：项目简介、快速开始、导航。
- [`docs/architecture.md`](docs/architecture.md)：流水线、模块边界、输出字段。
- [`docs/modules/`](docs/modules/)：各识别模块的参数、输出与限制；改 `core/*.py` 前先读对应文档。
- [`docs/data.md`](docs/data.md)：数据资产与本次清理记录。
- [`data/s18db/INDEX.md`](data/s18db/INDEX.md) / [`GAPS.md`](data/s18db/GAPS.md)：静态库字段与缺口。
- [`labeler/README.md`](labeler/README.md)：标注器。

仓库是 git：<https://github.com/zhansan379/jcc_s18>（public，`main` 为默认分支）。没有 CI、测试框架、`requirements.txt`；提交前用样例图跑一遍 `python scan.py` 人工核对。
**不要提交** `labeler/*.exe`（82MB）、`output/advisor_cache/`、`output/crops_sample/`、`.opencode/`，`.gitignore` 已排除；密钥走环境变量 `DASHSCOPE_API_KEY`，代码里不要写回默认值。

## 环境与命令

依赖：`numpy` `scipy` `Pillow`；本地 OCR 需 `rapidocr-onnxruntime`；标注器与 `advisor/` 需 `PyQt6`（打包再加 `PyInstaller`）。

```bash
python scan.py 图.png                      # 默认 hybrid
python scan.py 图.png --backend ocr        # 全离线，不调 VLM
python scan.py 图.png --json out.json --save-crops
python scan.py 图.png --no-players --no-units --no-traits --no-items --no-augments
python scan.py 图.png --labels             # 离线，用 data/hero_labels 匹配名字
python scan.py 图.png --names              # 实验性：VLM + 缓存，会联网

python core/ocr_extract.py 图.png          # 只跑文本 OCR
python core/vlm_board_scan.py 图.png       # 只跑 VLM

python recommend.py output/sample_state.json   # 规则推荐，不联网
python recommend.py --image 图.png --brief     # 扫描+推荐，摘要输出

python advisor/app.py 图.png                   # 图形界面对局助手（推荐页 + 识别标注页）
python advisor/pipeline.py 图.png              # 只跑助手流水线（--no-llm 关 LLM）
```

- 改坐标后的验证：`--save-crops` 后用 `python tools/make_crop_preview.py 图.png` 生成 `output/分割结果预览.png` 肉眼看。没有自动化测试。
- 样例截图：`D:\Download\00a5a489-ca7a-4216-bef0-81821a313981.png`。
- `core/` 下只有 `ocr_extract.py`、`vlm_board_scan.py`、`hero_names.py` 带 `__main__`；其他 core 模块只能被 import。
- `core/` 不是包（无 `__init__.py`），模块间用裸导入（如 `from board_units import match_item`）。不要 `import core.xxx`；从仓库根跑 `scan.py`，或直接运行 `core/` 下的脚本。

## 架构要点

- 文本字段：`core/ocr_extract.py:TIGHT` 紧框只跑识别网络 → `scan.py:VALIDATORS` → 失败才回落 VLM。金币双框投票；商店对 `data/HeroData.json` 的 65 人名单核对。
- 棋盘 3D 棋子 OCR 无效：数量/星级/位置/装备由 `core/board_units.py` 纯 CV 得出；默认开启 CV 时棋盘数量只由 CV 产出，失败也不回落 VLM。
- 玩家/羁绊/装备栏/符文：`player_hp.py`、`traits.py`、`item_bench.py`、`augments.py` 独立执行；`item_bench` 复用 `board_units.match_item`。
- 坐标两套且**不共享**：`core/vlm_board_scan.py:REGIONS`（5 个分区框，预览脚本也 import）与 `core/ocr_extract.py:TIGHT`（分区内紧框）。改一个不会同步另一个。
- `data/s18db/` 是静态库；`scan.py` 自身不读。`hero_names.py` 读 `heroes.json`；`recommend.py`/`core/comp_index.py` 读 `comps/heroes/traits/items/augments.json`。`augments.py` 用 `data/augmenticons_s18/` + `augmenticons_ingame/` + `augmenticons_s18_index.json`。`data/HeroData.json` 只用于商店校验。
- 推荐链路：`recommend.py` → `core/comp_index.py`（s18db 索引）→ `core/comp_match.py`（核心单位/羁绊/装备/商店/符文风格/meta 评分）→ `core/economy.py`（等级/存钱/搜牌/买卡）。参数在 `config/strategy_rules.json`，不是数据事实。
- `advisor/` 是对上面链路的 GUI 编排（`pipeline.analyze` = scan + comp_match + s18db 补充 + LLM），不改 `core/` 行为；`advisor/databook.py` 额外读 `comps.json` 的 `board/earlyBoard/equipOptions/conditions/jccCode`，这些字段 `comp_index` 不保留。界面文字（拿牌/节奏/升级/变阵/装备）由 `advisor/plan.py` 现算，**不要**把结论写进模板硬编码——概率用 `databook.find_chance()`，经验用截图里的 `x/y`。
- `--labels` 读 `data/hero_labels/labels.json`；`--names` 走 `data/hero_names_cache.json`。

## 容易踩的坑

- **只支持 16:9（≈1.75）**。`wide` 只在 `player_hp.py`、`traits.py` 实现（`W/H > 2.0`）；`item_bench.py`、`board_units.py`、`ocr_extract.TIGHT`、VLM `REGIONS` 都只有 16:9。宽屏会大面积失败。
- 没装 `rapidocr-onnxruntime` 时，hybrid 会把所有文本字段回落 VLM（不再离线）。
- `--budget` 只是 VLM 的 deadline，不限制 OCR/CV；冷启动总耗时可能超过 budget。
- `--no-units` 在 hybrid/vlm 下**反而会发一次棋盘 VLM 请求**（改用 VLM 数数量）。
- 固定框对 2px 偏差极敏感（金币框多带图标就会读错）。先出裁剪预览再改；换分辨率/UI/语言必须重标。
- VLM/LLM 的 key 只从 `DASHSCOPE_API_KEY` 读，**仓库里没有默认 key**；没设置时 VLM 返回 `no-key`、助手回落规则文案。别把 key 写回代码或提交。
- 多处硬编码 `D:\Download\...`（`tools/build_s18db.py`、`tools/bench_ocr_vs_vlm.py`、`tools/annotate_all.py`、`labeler/app.py`、`core/hero_names.py`）。换机器先改；重建 s18db 还依赖 `D:\Download\browserDownload`。
- `labeler/英雄标注工具.exe` 必须留在 `labeler/` 下（运行时向 `../data` 找图标/标注）。重新打包：`cd labeler; python build.py`。
- 源码/JSON 均 UTF-8。PowerShell 默认编码可能显示乱码，别据此「修复」文本。
- `output/*.json` 是样例，不是 golden；`sample_result.json` 已于 2026-11-02 用当前代码重跑（`棋子.数量` 只数棋盘，`备战席` 单列）。`data/hero_labels/` 是用户标注，勿删。
- 推荐依赖单位名字：没有 `--labels`/`--names` 时 `recommend.py` 只能给经济建议。当前也没有对手棋盘，无法做克制/对位；评分只是规则分，不是准确率。
- 推荐参数改 `config/strategy_rules.json`（等级节奏/血量线/搜牌金币/权重），不要散改 `core/comp_match.py` 的默认权重。
- `advisor/` 的 LLM 只吃压缩文本、输出要过 `llm._validate()`（符文名/牌名必须来自候选池），装备建议是配方算出来的、**不交给 LLM**；别在 prompt 里放开这些约束，会开始编英雄名。
- `advisor/` 的 10s 预算是这么保的：启动预热（OCR/模板/符文掩膜）+ `output/advisor_cache/` 内容哈希缓存 + LLM 墙钟硬超时 3.5s。改识别参数或缓存 key（`_cache_key` 里的 `v2`）会一起失效，属预期。
- 2026-11-02 深度清理：`data/s18db/raw/`、`data/s18db/images/`、`output/` 未引用调试产物、根目录 `_augarea.png`/`sol.py` 已移到 `C:\Users\feng1\AppData\Local\Temp\jcc_s18_cleanup_20261102\`。不要假设这些路径存在；重建前看 [`docs/data.md`](docs/data.md)。

## 静态数据重建

`s18db` 由脚本生成，会联网并覆盖现有 JSON，除非明确要求不要跑：

```bash
python tools/fetch_jcc_comps.py      # 阵容榜单 / 详情
python tools/fetch_augment_tier.py   # 强化符文 + 评级
python tools/fetch_dataj_hex.py      # dataj 统计 + 符文图标
python tools/build_s18db.py          # 汇总其余表与 manifest
```

`build_s18db.py` 依赖 `raw/site-data-cn.json` 与 `D:\Download\browserDownload` 的导出；`raw/` 已移出，需恢复备份或重新导出。细节见 [`docs/s18db.md`](docs/s18db.md)。
