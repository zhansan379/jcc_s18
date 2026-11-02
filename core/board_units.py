# -*- coding: utf-8 -*-
"""
棋盘单位识别：血条 → 星级 + 位置 + 身上装备
==========================================
1) 找血条：亮绿色宽扁色块（己方绿条）
2) 星级：血条左侧雪佛龙的颜色 —— 铜=1★ 银=2★ 金=3★
3) 装备：血条正下方按黑边切出装备方块，再和 data/equipment_s18 的图标做三特征匹配

纯 numpy/scipy，不调模型。
"""
import os

import numpy as np
from scipy import ndimage
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, "..", "data", "equipment_s18")

# 装备方块（黑边）搜索参数
DARK = 40
MIN_W, MAX_W = 22, 42
MIN_H, MAX_H = 24, 46

_refs = None


# ------------------------------------------------------------------ 血条
def _is_player_bar(a, bar):
    """玩家状态条（等级数字＋血条）不是英雄。
    特征：左侧有一个装数字的方框，方框里有大片近白色像素；英雄的星级标记没有白色。
    """
    h = bar["h"]
    y0, y1, x0 = bar["y0"], bar["y1"], bar["x0"]
    reg = a[max(0, y0-6):y1+6, max(0, x0-int(h*4.5)):x0]
    if reg.size == 0:
        return False
    mx = reg.max(axis=2)
    mn = reg.min(axis=2)
    white = int(((mx > 185) & ((mx - mn) < 40)).sum())
    return white > 25


def find_bars(a):
    """只取己方绿色血条（英雄单位）。

    判据要点：
    * **B 通道**：血量条的绿是高 B 的薄荷绿（B≈95~190），草地绿 B=0。
    * 血条是**分段式**的（每段 20~45×6~10，中间有暗缝），先横向闭运算桥接。
    * 逐行找「宽度 55~135 的绿段」，再把上下相邻、x 范围接近的行合并成一条 ——
      这样即使血条下方紧贴单位的绿色身体（连成一坨、整体填充率很低）也能切出来。
    """
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    green = (G > 150) & (G - R > 35) & (B > 60)
    green = ndimage.binary_closing(green, np.ones((1, 7)))
    H, W = green.shape

    segs = []
    for y in range(H):
        idx = np.flatnonzero(green[y])
        if idx.size == 0:
            continue
        for g in np.split(idx, np.where(np.diff(idx) != 1)[0] + 1):
            if len(g) >= 55:
                x0, x1 = int(g[0]), int(g[-1]) + 1
                if 55 <= x1 - x0 <= 150:
                    segs.append((y, x0, x1))

    # 合并上下相邻、水平重叠的段
    segs.sort()
    bars = []
    for (y, x0, x1) in segs:
        for b in bars:
            if y - b["y1"] <= 2 and min(b["x1"], x1) - max(b["x0"], x0) > 0.6*min(b["x1"]-b["x0"], x1-x0):
                b["y1"] = y + 1
                b["x0"] = min(b["x0"], x0)
                b["x1"] = max(b["x1"], x1)
                b["n"] += 1
                break
        else:
            bars.append({"x0": x0, "y0": y, "x1": x1, "y1": y + 1, "n": 1})

    out = []
    val = a.max(axis=2).astype(np.float32)
    for b in bars:
        b["w"] = b["x1"] - b["x0"]
        b["h"] = b["y1"] - b["y0"]
        if b["h"] < 4 or b["h"] > 20 or b["n"] < 4:
            continue
        if b["y0"] / H > 0.755:            # 底部 UI 面板里的经验条
            continue
        # 血条一定嵌在深色边框里：上沿、下沿各有暗行
        top = val[max(0, b["y0"]-3):b["y0"], b["x0"]:b["x1"]]
        bot = val[b["y1"]:b["y1"]+4, b["x0"]:b["x1"]]
        if top.size == 0 or bot.size == 0:
            continue
        if (top < 70).mean() < 0.55 or (bot < 70).mean() < 0.55:
            continue
        if _is_player_bar(a, b):           # 「等级数字+血量」的玩家状态条
            continue
        out.append(b)

    out.sort(key=lambda b: (b["y0"] // 60, b["x0"]))
    return out


def _hsv(c):
    r, g, b = [v/255 for v in c]
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d == 0:
        h = 0
    elif mx == r:
        h = 60 * (((g-b)/d) % 6)
    elif mx == g:
        h = 60 * ((b-r)/d + 2)
    else:
        h = 60 * ((r-g)/d + 4)
    return h, mx, (0 if mx == 0 else d/mx)


def _hue_sv(px):
    """px: (N,3) 逐像素色相/明度/饱和"""
    p = px.astype(np.float32)
    r, g, b = p[:, 0], p[:, 1], p[:, 2]
    mx = p.max(axis=1); mn = p.min(axis=1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 0
    mr = nz & (mx == r); mg = nz & (mx == g) & ~mr; mb = nz & ~mr & ~mg
    h[mr] = (60 * (((g[mr]-b[mr])/d[mr]) % 6))
    h[mg] = (60 * ((b[mg]-r[mg])/d[mg] + 2))
    h[mb] = (60 * ((r[mb]-g[mb])/d[mb] + 4))
    s = np.where(mx > 0, d/np.maximum(mx, 1), 0)
    return h, mx/255.0, s


def classify_marker(reg):
    """血条左侧「星级标记」的颜色 -> 星级。

    实测（同一张 1919×1097 截图）：
      1★ 铜色雪佛龙  银蓝像素 0 个，暖色像素 40~220 个
      2★ 银蓝菱形    银蓝像素 126~156 个，暖色 0 个
    两组完全分离，所以用「绝对像素数」判断，比取平均色稳。
    """
    if reg.size == 0:
        return None, None
    mx = reg.max(axis=2)
    mn = reg.min(axis=2)
    m = (mx > 70) & ((mx - mn) > 20)
    if m.sum() < 15:
        return None, None
    h, v, s = _hue_sv(reg[m])
    silver = int(((h >= 165) & (h <= 225) & (s < 0.35) & (v > 0.50)).sum())
    gold = int(((h >= 30) & (h <= 62) & (s > 0.55) & (v > 0.80)).sum())
    if silver > 60:
        return 2, "银"
    if gold > 60:
        return 3, "金"
    return 1, "铜"


def star_of_bar(a, bar):
    """取血条左侧星级标记的颜色 → 星级。
    标记可能落在血条左端之外（1★ 雪佛龙），也可能被并进检测框左端（2★ 菱形），
    所以以血条左沿为中心、左右各取 42px 一起看。
    """
    y0, y1 = bar["y0"], bar["y1"]
    W = a.shape[1]
    xa = max(0, bar["x0"] - 42)
    xb = min(W, bar["x0"] + 42)
    ya, yb = max(0, y0-10), y1+8
    if xb <= xa:
        return None, None
    return classify_marker(a[ya:yb, xa:xb])


# ------------------------------------------------------------------ 装备方块
def _runs(m, minlen):
    idx = np.flatnonzero(m)
    if idx.size == 0:
        return []
    g = np.split(idx, np.where(np.diff(idx) != 1)[0] + 1)
    return [(int(x[0]), int(x[-1]) + 1) for x in g if len(x) >= minlen]


def find_item_boxes(a, bar, max_slots=3, val=None, sat=None):
    """在血条正下方按黑边找装备方块"""
    if val is None:
        val = a.max(axis=2).astype(np.float32)
    if sat is None:
        sat = (a.max(axis=2) - a.min(axis=2)).astype(np.float32)
    H, W = val.shape
    y_start = bar["y1"] + 4
    y_end = min(H, bar["y1"] + bar["h"] * 7)
    x_lo = max(0, bar["x0"] - bar["h"] * 2)
    x_hi = min(W, bar["x1"] + bar["h"])
    boxes = []
    for y in range(y_start, int(y_end) - MIN_H):
        for (xa, xb) in _runs(val[y, x_lo:x_hi] < DARK, MIN_W):
            xa += x_lo; xb += x_lo
            if not (MIN_W <= xb - xa <= MAX_W):
                continue
            if any(abs(xa - b[0]) < 5 and abs(y - b[1]) < 5 for b in boxes):
                continue
            y1 = y
            for yy in range(y + 1, min(H, y + MAX_H)):
                if not (val[yy, max(0, xa-1):xa+2].min() < DARK or
                        val[yy, max(0, xb-2):xb+1].min() < DARK):
                    break
                y1 = yy
            if not (MIN_H <= y1 - y <= MAX_H):
                continue
            ins = sat[y+3:y1-1, xa+3:xb-3]
            if ins.size == 0 or ins.std() < 18:
                continue
            boxes.append((xa, y, xb, y1 + 1))
    boxes.sort()
    return boxes[:max_slots]


# ------------------------------------------------------------------ 装备匹配
def _prep(im, size=56):
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, (0, 0, 0, 255))
    im = Image.alpha_composite(bg, im).convert("RGB").resize((size, size), Image.LANCZOS)
    g = np.asarray(im.convert("L"), dtype=np.float32)
    hsv = np.asarray(im.convert("HSV"), dtype=np.float32)
    hist = np.concatenate([
        np.histogram(hsv[:, :, 0], bins=18, range=(0, 256))[0],
        np.histogram(hsv[:, :, 1], bins=8, range=(0, 256))[0]]).astype(np.float32)
    hist /= hist.sum() + 1e-9
    cells = np.array([g[i*18:(i+1)*18, j*18:(j+1)*18].mean()
                      for i in range(3) for j in range(3)], dtype=np.float32)
    cells = (cells - cells.mean()) / (cells.std() + 1e-6)
    return g, hist, cells


def _ncc(x, y):
    x = x - x.mean(); y = y - y.mean()
    d = np.sqrt((x*x).sum()) * np.sqrt((y*y).sum())
    return float((x*y).sum()/d) if d else 0.0


def _load_refs():
    """一次性把全部参考图标堆成矩阵，匹配时用矩阵乘法，避免 139 次循环"""
    global _refs
    if _refs is None:
        names, G, Hh, C = [], [], [], []
        if os.path.isdir(REF):
            for f in sorted(os.listdir(REF)):
                if not f.lower().endswith(".png"):
                    continue
                g, h, c = _prep(Image.open(os.path.join(REF, f)))
                names.append(os.path.splitext(f)[0])
                G.append(g.ravel()); Hh.append(h); C.append(c)
        if names:
            G = np.array(G, dtype=np.float32)
            G -= G.mean(axis=1, keepdims=True)
            G /= (np.linalg.norm(G, axis=1, keepdims=True) + 1e-6)
            _refs = {"names": names, "G": G, "H": np.array(Hh, dtype=np.float32),
                     "C": np.array(C, dtype=np.float32)}
        else:
            _refs = {"names": [], "G": None, "H": None, "C": None}
    return _refs


def match_item(img, box):
    refs = _load_refs()
    if not refs["names"]:
        return None, 0.0
    q = img.crop(box)
    q = q.crop((2, 2, q.width-2, q.height-2))       # 去掉 2px 黑边
    qg, qh, qc = _prep(q)

    qv = qg.ravel() - qg.mean()
    nv = np.linalg.norm(qv) + 1e-6
    ncc = (refs["G"] @ qv) / nv                      # (N,)
    hist = np.sqrt(refs["H"] * qh).sum(axis=1)       # 直方图求交
    cells = ((refs["C"] * qc).mean(axis=1) + 1) / 2
    score = 0.42*ncc + 0.30*hist + 0.28*cells
    i = int(np.argmax(score))
    return refs["names"][i], round(float(score[i]), 3)


# ------------------------------------------------------------------ 对外
BENCH_Y = 0.580      # y 超过这条线视为备战席，否则是棋盘


def extract(img):
    a = np.asarray(img).astype(np.int16)
    W, H = img.size
    val = a.max(axis=2).astype(np.float32)                 # 只算一次，8 条血条复用
    sat = (a.max(axis=2) - a.min(axis=2)).astype(np.float32)
    units = []
    for bar in find_bars(a):
        star, color = star_of_bar(a, bar)
        items = []
        for box in find_item_boxes(a, bar, val=val, sat=sat):
            name, score = match_item(img, box)
            if name and score >= 0.55:
                items.append({"name": name, "score": score,
                              "box": [round(box[0]/W, 4), round(box[1]/H, 4),
                                      round(box[2]/W, 4), round(box[3]/H, 4)]})
        cy = bar["y0"] / H
        units.append({"star": star, "star_color": color,
                      "area": "bench" if cy >= BENCH_Y else "board",
                      "pos": [round(bar["x0"]/W, 4), round(bar["y0"]/H, 4)],
                      "box": [bar["x0"], bar["y0"], bar["x1"], bar["y1"]],
                      "items": items})
    return units


def annotate(img, units, out_path, title=None):
    """在原图上标出每个单位：血条框 + 星级 + 归属（带底色标签，避免和场景混在一起）"""
    from PIL import ImageDraw, ImageFont

    v = img.convert("RGBA")
    ov = Image.new("RGBA", v.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 22)
        big = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 26)
    except Exception:
        font = ImageFont.load_default()
        big = font

    COL = {"board": (0, 255, 120), "bench": (90, 190, 255)}
    for i, u in enumerate(units, 1):
        x0, y0, x1, y1 = u["box"]
        c = COL[u["area"]]
        # 血条框
        d.rectangle([x0 - 2, y0 - 2, x1 + 1, y1 + 1], outline=c + (255,), width=2)
        # 标签
        tag = "#%d  %s%d★  %s" % (i, (u.get("name") + " ") if u.get("name") else "",
                                   u["star"] or 0,
                                   "棋盘" if u["area"] == "board" else "备战席")
        tw = d.textlength(tag, font=font)
        th = 26
        # 交错高度，避免相邻标签重叠
        lift = 26 + (i % 2) * 24
        ly = y0 - lift
        if ly < 4:
            ly = y1 + 6
        lx = min(max(2, x0 - 4), v.width - tw - 14)
        d.rounded_rectangle([lx, ly, lx + tw + 12, ly + th], radius=6,
                            fill=(10, 10, 14, 225), outline=c + (255,), width=2)
        d.text((lx + 6, ly + 2), tag, font=font, fill=c + (255,))
        # 引线
        d.line([(lx + 10, ly + th if ly < y0 else ly), (x0 + 6, y0)], fill=c + (200,), width=1)
        # 装备框
        for it in u["items"]:
            bx = it["box"]
            d.rectangle([bx[0]*v.width, bx[1]*v.height, bx[2]*v.width, bx[3]*v.height],
                        outline=(255, 200, 0, 255), width=2)

    # 图例
    lg = "绿框=棋盘　蓝框=备战席　黄框=装备　数字=星级"
    tw = d.textlength(lg, font=big)
    d.rounded_rectangle([8, 8, 8 + tw + 20, 46], radius=8, fill=(10, 10, 14, 225))
    d.text((18, 12), lg, font=big, fill=(255, 235, 150, 255))

    out = Image.alpha_composite(v, ov).convert("RGB")
    out.save(out_path)
    return out_path
