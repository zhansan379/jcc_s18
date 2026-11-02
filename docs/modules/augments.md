# augments：强化符文

文件：`core/augments.py`  
入口：`find_icons(img) -> augments[]`

## 职责

在全图里找「深蓝底 + 金色图案」的强化符文图标，输出候选名、分数和是否可信。

## 输出

```json
[
  {
    "box": [1200, 280, 1264, 344],
    "name": "DD街区+",
    "score": 1.0,
    "reliable": true,
    "top": [
      {"name": "DD街区+", "hexId": "DA_TradeSectorPlus", "rarity": "gold", "score": 1.0},
      {"name": "DD街区", "hexId": "DA_TradeSector", "rarity": "gold", "score": 1.0}
    ]
  }
]
```

- `name`：仅在 `reliable=true` 时给出，否则 `null`。
- `score`：第一名 IoU。
- `top`：前 3 个候选，含 `hexId` / `rarity`（来自 `data/augmenticons_s18_index.json`）。

## 定位

`find_icons()`：

- 深蓝底判据：`B > R+25 & B > G+5 & 25 < max < 110`。
- `3×3` 闭运算后连通域标记。
- 尺寸 28~90，宽高差不超过长边的 25%。
- 区域内金色像素占比 ≥5%：
  `R>120 & G>90 & B<120`。
- 每个候选裁出来送 `topk(crop, 3)`。
- 结果按分数降序。

## 形状匹配

`topk()`：

1. 查询图 `_q_mask()`：缩到 128×128，取金色图案，闭/开运算去噪。
2. 参考图：
   - 游戏内模板（`data/augmenticons_ingame/`）：RGB 无 alpha，用金色图案提掩膜。
   - 官方原画（`data/augmenticons_s18/`）：透明底，用 alpha >110 提掩膜。
3. `_norm_mask()`：裁到图案自身包围盒，等比缩放到 64×64 居中。**这是尺度一致的关键**：直接整块缩放 IoU 只有 ~0.19，按 bbox 归一化后 ~0.785。
4. `_iou_shift()`：FFT 卷积一次算完 ±3px 平移，取最大 IoU。
5. 取 top-k，查索引补 `hexId` / `rarity`。

## 参考库加载

`_load_refs()`：

- 目录顺序：`data/augmenticons_ingame/` → `data/augmenticons_s18/`。
- 同名文件：先加载的游戏内模板保留，官方原画跳过。
- 按转换后 RGBA 像素 MD5 去重；同一图案的不同稀有度只留一份。
- `augmenticons_s18` 有 256 张；`augmenticons_ingame` 目前 1 张覆盖。

## 判定阈值

```python
MIN_SCORE = 0.80   # 第一名绝对分
MIN_GAP   = 0.03   # 领先第二名
reliable = top[0].score >= 0.80 and (top[0].score - top[1].score) >= 0.03
```

不满足就判「未知」，但仍返回候选，便于人工确认。

## 已知限制

- 首次运行要给全部参考图建归一化掩膜，约 1.6s；之后进程内缓存。
- 只看形状，不看颜色/文字；同形状不同名的图标会进候选，靠 gap 区分。
- 图标被UI遮挡、缩放、旋转、或底色不是深蓝时会漏检。
- 阈值 0.80 + gap 0.03 是实测折中；太低会误认，太高会大量「未知」。
- `data/s18db/images/augments/` 已在清理中移出仓库；扫描器不使用它，不要把它当成必需依赖。
- 新增符文：把图标按「符文名.png」放进 `data/augmenticons_s18/`（游戏内截图优先放 `augmenticons_ingame/`），并更新 `augmenticons_s18_index.json`。

## 相关文档

- [data](../data.md)
- [architecture](../architecture.md)
- [troubleshooting](../troubleshooting.md)
