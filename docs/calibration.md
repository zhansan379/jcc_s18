# 坐标校准

## 两套坐标，互不同步

| 坐标 | 位置 | 用途 |
|---|---|---|
| `REGIONS` | `core/vlm_board_scan.py` | 5 个分区框：VLM 裁剪 + `make_crop_preview.py` 预览 |
| `TIGHT` | `core/ocr_extract.py` | 分区内部的紧致文字框，只跑 OCR 识别 |

改 `REGIONS` 不会自动改 `TIGHT`；反之亦然。`make_crop_preview.py` 只 import `REGIONS`，所以预览图对不代表 OCR 框对。

## 支持的比例

| profile | 宽高比 | 典型尺寸 | 支持情况 |
|---|---|---|---|
| `16_9` | ≈1.75 | 1919×1097 | 全流程 |
| `wide` | >2.0 | 2712×1220 | **仅 `player_hp`、`traits`** |

`pick_layout()` 在 `W/H > 2.0` 时返回 `wide`。但：

- `item_bench.py` 只有 `16_9` 栅格，`wide` 直接返回空。
- `board_units.py` 没有 layout 分支。
- `ocr_extract.py:TIGHT` 和 VLM `REGIONS` 都是 16:9 坐标。

宽屏截图目前只能保证玩家列表和羁绊面板；其余模块会错位或为空。README 里的「两套坐标」仅指 `player_hp`/`traits`。

## 校准流程

```bash
# 1. 保存实际裁剪块
python scan.py 截图.png --save-crops
#    → output/crops_sample/crop_<文件名>_<分区>.png

# 2. 生成可视化：左=原图打框，右=实际送进 VLM 的裁剪
python tools/make_crop_preview.py 截图.png
#    → output/分割结果预览.png
```

检查顺序：

1. `stage` 框是否完整包住回合数字；
2. `level_exp` 是否同时包住等级和经验；
3. `gold` 左边界是否避开金币图标；
4. `shop` 是否包住 5 张卡且每张卡只取底部名字；
5. `board` 是否覆盖己方棋盘。

OCR 的紧框没有可视化，需直接看 `output/crops_sample` 或临时把 `TIGHT` 画到图上；改动后跑一张已知答案的截图，核对 5 个文本字段。

## 什么时候必须重标

- 换分辨率或宽高比；
- 游戏 UI 改版、换语言、改 UI 缩放；
- 模拟器窗口比例变化；
- 金币/商店/羁绊出现系统性误读，且不是模型加载问题。

## 调框注意

- 百分比框以整图宽高为基准，`REGIONS` 的 `box=(左, 上, 右, 下)` 是 0~1。
- `TIGHT` 是分区内部的比例，不是整图比例。
- 金币框对 2px 极敏感：左边界多带图标就会读成 `8`/`9`；靠双框投票兜底，但最好一次标准。
- 商店 5 个紧框必须一一对应卡片，宽度过大会把相邻卡名字带进来。
- 改完跑 `python scan.py 截图.png --backend ocr --json out.json`，至少核对阶段/等级/经验/金币/商店。
- 需要 VLM 的区域（棋盘）不能只看 OCR 结果。

## 相关文档

- [architecture](architecture.md)
- [backends](backends.md)
- [troubleshooting](troubleshooting.md)
