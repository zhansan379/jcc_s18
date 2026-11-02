# labeler：人工标注工具

目录：`labeler/`  
详细用法与数据格式：[labeler/README.md](../../labeler/README.md)

## 作用

给截图里裁出的 3D 棋子人工打英雄名，产出带名字的裁剪图，供：

- `--labels` 的离线最近邻（`core/hero_match.py`）；
- 以后做 VLM few-shot 参考图；
- 用羁绊面板反查标注质量。

## 使用

双击 `labeler/英雄标注工具.exe`（单文件，无需 Python）。

界面：

- 左侧：当前棋子 3× 放大预览 + 编号/棋盘或备战席/星级/裁剪尺寸。
- 右侧：S18 65 个英雄 2D 头像，点一下完成标注。
- 底部：本图缩略条，绿框=已标注，灰框=未标注。
- 顶部：`本图 3/12 · 累计 27 个不同棋子`。

快捷键：

| 键 | 作用 |
|---|---|
| 空格 / Enter | 下一个未标注 |
| Backspace | 清空当前格 |
| ← → | 上一个 / 下一个棋子 |
| Ctrl+F | 搜索英雄名 |

## 数据落点

```
data/hero_labels/
├── labels.json          # 按裁剪图 sha1 去重
└── crops/<sha1>.png     # 裁剪原件
```

`labels.json` 的关键字段：

```json
{
  "version": 1,
  "items": {
    "<sha1>": {
      "name": "瑟庄妮",
      "image": "源截图.png",
      "unit": 3,
      "star": 1,
      "area": "board",
      "box": [625, 576, 696, 583],
      "crop": "crops/<sha1>.png",
      "ts": 1793602581
    }
  }
}
```

- 同一张图里重复的同一棋子标一次就全绿。
- 不同截图里的同一棋子自动复用。
- `crops/*.png` 可直接当游戏内模板。

## 重新打包

```bash
cd labeler
python build.py
# 产物：labeler/英雄标注工具.exe（约 82 MB）
```

依赖：`PyQt6`、`numpy`、`scipy`、`Pillow`、`PyInstaller`。

exe 不带数据，运行时按 `exe所在目录/../data` 找图标和标注，所以 **exe 必须留在 `labeler/` 下**。

## 注意

- 右侧 65 个头像来自 `data/heroicons_s18/`，包含 S18 野怪单位，没有过滤。
- `data/hero_labels/` 是用户标注数据，不要删除或覆盖。
- 标注质量直接影响 `--labels`；跨地图/宽屏目前匹配不了，见 [hero-names](hero-names.md)。

## 相关文档

- [hero-names](hero-names.md)
- [data](../data.md)
- [labeler/README.md](../../labeler/README.md)
