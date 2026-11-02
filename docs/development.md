# 开发与验证

## 环境

没有 `requirements.txt` / `pyproject.toml`，手动安装：

```bash
python -m pip install numpy scipy Pillow
python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ rapidocr-onnxruntime
# 标注器
python -m pip install PyQt6
# 重新打包 exe
python -m pip install pyinstaller
```

Python 3.8+（代码未使用新语法；实测环境 3.11）。Windows 是主要目标（字体路径 `C:/Windows/Fonts/msyh.ttc`）。

## 常用命令

```bash
# 全流程
python scan.py 图.png

# 离线
python scan.py 图.png --backend ocr

# 输出 JSON / 保存裁剪
python scan.py 图.png --json out.json --save-crops

# 跳过模块
python scan.py 图.png --no-players --no-units --no-traits --no-items --no-augments

# 名字
python scan.py 图.png --labels      # 离线
python scan.py 图.png --names       # VLM + 缓存

# 阵容/行动建议（一条命令，摘要输出）
python recommend.py --image 图.png --brief

# 已有 state 时不重复扫描
python scan.py 图.png --labels --json state.json
python recommend.py state.json --json plan.json

# 单模块
python core/ocr_extract.py 图.png
python core/vlm_board_scan.py 图.png

# 坐标预览
python tools/make_crop_preview.py 图.png
```

## 工具脚本

| 脚本 | 用途 | 备注 |
|---|---|---|
| `tools/make_crop_preview.py` | 生成 `REGIONS` 裁剪预览 | 校准坐标必用 |
| `tools/annotate_all.py` | 把 scan 结果画到整图，输出 `output/全部标注.png` + `status.json` | **自己复制了一份区域框**，不是坐标真源；改 `REGIONS` 时注意同步 |
| `tools/bench_ocr_vs_vlm.py` | OCR / VLM 速度效果对比 | 硬编码样例图路径 |
| `tools/find_item_frames.py` | 按黑边/金边切装备方块 | 支持 dark/gold/auto |
| `tools/build_icon_sheet.py` | 由 `data/heroicons_s18/` 生成 `data/sheet_s18.png` | 人眼对照表 |
| `tools/tag_hero_skills.py` | 生成 `s18db/hero_skills_tags.json` | 规则/LLM 初稿，未逐条人工确认 |
| `tools/trait_effects.py` | 解析羁绊档位文本为结构化 `effects` | 被 `build_s18db.py` 调用 |
| `tools/fetch_jcc_comps.py` | 抓阵容榜单/详情 | 联网，写 `s18db` |
| `tools/fetch_augment_tier.py` | 抓强化符文评级 | 联网，写 `s18db` |
| `tools/fetch_dataj_hex.py` | 抓 dataj 统计 + 符文图标 | 联网，写 `s18db` |
| `tools/build_s18db.py` | 汇总静态库与 manifest | 依赖本地导出与 `raw/` |
| `recommend.py` | 局面 → Top 3 阵容 + 行动 | 见 [modules/recommend](modules/recommend.md) |

## 代码结构约定

- `scan.py` 只负责截图 → 局面；`recommend.py` 是独立的推荐入口，不要把它们合并。
- `core/` 模块可独立 import；推荐相关是 `comp_index.py` / `comp_match.py` / `economy.py`。
- `core/` **不是 Python 包**（没有 `__init__.py`），模块间用裸导入：
  `from board_units import match_item`。
  - 从仓库根跑 `scan.py` 时，它会 `sys.path.insert(0, "core")`。
  - 直接跑 `core/xxx.py` 时，脚本目录自动在 `sys.path`。
  - 不要写 `import core.board_units`，会失败。
- `core/` 下只有 `ocr_extract.py`、`vlm_board_scan.py`、`hero_names.py` 带 `__main__`；其余模块没有 CLI。
- OCR 实例统一走 `ocr_extract.get_ocr()` 单例；`player_hp`/`traits` 复用它，避免重复加载 ~0.9s。
- 新增/修改模块时，同步更新 `docs/modules/` 对应文档和根 README 的导航。
- 源码/JSON 全部 UTF-8；不要用 GBK 保存。

## 减少往返与编码问题

- 推荐直接用一条命令：`python recommend.py --image 图.png --brief`；不要先 `scan.py`、再 `recommend.py`、再单独读 JSON。
- 需要中间结果时才落盘：`--save-state state.json --json plan.json`；后续直接复用 `state.json`，不要重复扫描。
- `--brief` 只输出 Top1 + 行动；不要打印完整 `plan.json`，大 JSON 用 `--json` 落盘后按需取字段。
- PowerShell 先 `chcp 65001`、`$env:PYTHONUTF8=1`；读中文文件用支持 UTF-8 的工具，别用默认 `Get-Content` 判断内容。

## 验证方式

没有测试框架、没有 CI。改完代码至少做：

1. `python -m compileall -q scan.py recommend.py core tools labeler`
2. 用 1919×1097 样例跑 `python scan.py 样例.png --backend ocr`，核对：
   - 阶段 / 等级 / 经验 / 金币 / 商店；
   - 玩家 8 行、自己的血量；
   - 单位数量、星级、装备；
   - 羁绊条数、装备栏、符文。
3. 改坐标后：`--save-crops` + `make_crop_preview.py` 看预览。
4. 改推荐器后：`python recommend.py output/sample_state.json`，核对 Top 3、缺失项和 actions；不要只看分数。
5. 改模块后，对比 `output/sample_result.json` 的字段口径（注意样例是当前代码重跑的，不是 golden；不同截图会有差异）。

样例截图：`D:\Download\00a5a489-ca7a-4216-bef0-81821a313981.png`（脚本里的默认样例路径）。

## 硬编码与安全

- `core/vlm_board_scan.py` 有硬编码 DashScope 默认 key；可用 `DASHSCOPE_API_KEY` 覆盖。不要打印/外传。
- `D:\Download\...` 绝对路径出现在：
  `tools/build_s18db.py`、`tools/bench_ocr_vs_vlm.py`、`tools/annotate_all.py`、`labeler/app.py`、`core/hero_names.py`。
  换机器先改路径。
- `data/s18db` 重建依赖 `D:\Download\browserDownload` 的导出文件。
- 当前目录不是 git 仓库；改动前自行备份。

## 本次清理记录

2026-11-02 深度清理，备份在：

```
C:\Users\feng1\AppData\Local\Temp\jcc_s18_cleanup_20261102\
```

移出：`data/s18db/raw/`、`data/s18db/images/`、`output/` 未引用调试产物、根目录 `_augarea.png`、`sol.py`。  
保留：`labeler/英雄标注工具.exe`、`data/hero_labels/`、文档引用样例、`output/crops_sample/`。

备份内 `_manifest.json` 有完整清单。

## 相关文档

- [architecture](architecture.md)
- [backends](backends.md)
- [calibration](calibration.md)
- [troubleshooting](troubleshooting.md)
- [AGENTS.md](../AGENTS.md)
