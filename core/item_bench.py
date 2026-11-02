# -*- coding: utf-8 -*-
"""
最左侧的「装备栏」（竖排金框方块）→ 装备名
========================================
云顶/金铲铲左侧那一列是玩家手上的散件与道具，位置是固定栅格：
    x 固定，首个方块 y0，行距 pitch，方块高 h
全部按**图片高度**换算，这样换分辨率也能用。

空格判定：方块内部饱和度标准差 < 25 就是空位（实测有装备 35~75，空背景 3~7）。
名字匹配复用 board_units.match_item（三特征 + 139 张参考图标）。
"""
import numpy as np
from PIL import Image

from board_units import match_item

# 比例以 1919×1097 那张实测值折算（除以 1097）
GRID = {
    "16_9": dict(x0=0.0182, x1=0.0711, y0=0.0985, pitch=0.0629, h=0.0520,
                 rows=9, min_std=25, min_score=0.55),
}


def pick_layout(size):
    W, H = size
    return "wide" if W / H > 2.0 else "16_9"


def extract(img, layout=None):
    if layout is None:
        layout = pick_layout(img.size)
    cfg = GRID.get(layout)
    if not cfg:
        return []
    W, H = img.size
    a = np.asarray(img).astype(np.int16)
    sat = (a.max(axis=2) - a.min(axis=2)).astype(np.float32)

    x0 = int(cfg["x0"]*H)
    x1 = int(cfg["x1"]*H)
    y0 = int(cfg["y0"]*H)
    pitch = int(cfg["pitch"]*H)
    hh = int(cfg["h"]*H)

    out = []
    for k in range(cfg["rows"]):
        y = y0 + k*pitch
        if y + hh > H:
            break
        box = (x0, y, x1, y+hh)
        inner = sat[y+6:y+hh-6, x0+6:x1-6]
        if inner.size == 0 or inner.std() < cfg["min_std"]:
            continue                                   # 空位
        name, score = match_item(img, box)
        if not name or score < cfg["min_score"]:
            continue
        out.append({"name": name, "score": score, "box": list(box)})
    return out
