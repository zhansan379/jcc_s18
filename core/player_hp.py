# -*- coding: utf-8 -*-
"""
右侧玩家列表 → 所有人的排名与血量
================================
快速路径（默认，~0.4s）：
  1) 右侧每条玩家信息最右端有个**橙色圆形头像环**，先用颜色把它找出来 → 得到 8 行的 y 区间
  2) 每行分两行文字：上面是名字、下面是血量数字，各自 rec-only（跳过检测网络）
  3) 名字在上、数字在下；没有名字的那一行就是自己

慢速回退（~3.4s）：
  如果头像环找不到（换皮肤/改版），退回整条竖带跑 det。

自己那一行的判定（两种路径通用）：
  金铲铲手游：该行只有数字、没有名字（头像还更大、环是金色）
"""
import os
import re

import numpy as np
from PIL import Image

# 右侧玩家列表区域（占整图比例）—— 都是金铲铲，只是窗口宽高比不同
LAYOUTS = {
    "16_9": dict(box=(0.820, 0.030, 1.000, 0.800), scale=2.2,
                 av_x=(0.78, 1.00), name_x=(0.36, 0.84), num_x=(0.52, 0.84),
                 name_dy=(0, 30), num_dy=(28, None), self_rule="no_name"),
    "wide": dict(box=(0.880, 0.010, 0.985, 0.960), scale=1.4,
                 av_x=(0.80, 1.00), name_x=(0.10, 0.72), num_x=(0.40, 0.72),
                 name_dy=(0, 34), num_dy=(32, None), self_rule="no_name"),
}

_ocr = None


def _get_ocr():
    """复用 ocr_extract 里那个实例：现在玩家列表是串行跑的，不会再并发抢模型，
    共用可以把「模型加载」的 ~0.9s 省掉一次。"""
    global _ocr
    if _ocr is None:
        try:
            from ocr_extract import get_ocr as _shared
            _ocr = _shared()
        except Exception:
            from rapidocr_onnxruntime import RapidOCR
            _ocr = RapidOCR()
    return _ocr


def pick_layout(size):
    """两种布局都是金铲铲（PC 模拟器），只是窗口宽高比不同"""
    W, H = size
    return "wide" if W / H > 2.0 else "16_9"


# ------------------------------------------------------------------ 行定位
def _row_bands(strip, cfg, min_h=25, max_h=95):
    """用橙色头像环定位每一行的 y 区间"""
    a = np.asarray(strip).astype(np.int16)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    orange = (R > 150) & ((mx - mn) > 70) & (R > G) & (G >= B)
    x0, x1 = cfg["av_x"]
    sw = strip.width
    col = orange[:, int(sw*x0):int(sw*x1)]
    cnt = col.sum(axis=1)
    bands, i, sh = [], 0, strip.height
    while i < sh:
        if cnt[i] >= 3:
            j = i
            while j < sh and cnt[j] >= 3:
                j += 1
            if j - i >= min_h:
                bands.append([i, j])
            i = j
        else:
            i += 1
    # 和顶部 UI 粘在一起的那段会异常高，丢掉
    bands = [b for b in bands if (b[1]-b[0]) <= max_h]
    if len(bands) < 2:
        return bands
    hh = [b[1]-b[0] for b in bands]
    med_h = int(np.median(hh))
    # 用中位间距把顶部缺的行补回来
    if len(bands) >= 2:
        pitch = int(np.median([bands[i+1][0]-bands[i][0] for i in range(len(bands)-1)]))
        while bands[0][0] - pitch >= 0 and len(bands) < 8:
            y0 = bands[0][0] - pitch
            if y0 < 0:
                break
            bands.insert(0, [y0, y0 + med_h])
            break
    return bands


def _rec_line(strip, box, scale, use_det=False):
    c = strip.crop(box)
    if c.width < 6 or c.height < 6:
        return ""
    c = c.resize((int(c.width*scale), int(c.height*scale)), Image.LANCZOS)
    r, _ = _get_ocr()(np.asarray(c)[:, :, ::-1], use_det=use_det, use_cls=False)
    if not r:
        return ""
    return r[0][0] if len(r[0]) == 2 else r[0][1]


def _has_cjk(t):
    return any("\u4e00" <= ch <= "\u9fff" for ch in t)


def _digits(t):
    """从 OCR 文本里取血量：容忍前后杂符号（X100 / %95 / x84 / 80C / 815）"""
    t = t or ""
    if re.search(r"[A-Za-z]{2,}", t):
        return None
    s = re.sub(r"[^0-9]+$", "", t.strip())
    m = re.search(r"(\d{1,3})$", s)
    if not m:
        return None
    v = int(m.group(1))
    if v > 100 and len(m.group(1)) == 3:
        v = int(m.group(1)[:2])          # "815" -> 81（血量不会超过 100）
    return v if 0 <= v <= 100 else None


# ------------------------------------------------------------------ 主流程
def extract(img, layout=None):
    if layout is None:
        layout = pick_layout(img.size)
    cfg = LAYOUTS.get(layout, LAYOUTS["16_9"])
    W, H = img.size
    l, t, r, b = cfg["box"]
    strip = img.crop((int(l*W), int(t*H), int(r*W), int(b*H)))
    sw = strip.width

    bands = _row_bands(strip, cfg)
    rows = []
    if len(bands) >= 4:
        for (y0, y1) in bands:
            nd0, nd1 = cfg["name_dy"]
            ny0, ny1 = y0 + nd0, (y0 + nd1 if nd1 else y1)
            nx0, nx1 = cfg["name_x"]
            name = _rec_line(strip, (int(sw*nx0), ny0, int(sw*nx1), ny1), 4).strip()
            cd0, cd1 = cfg["num_dy"]
            cy0, cy1 = y0 + cd0, (y0 + cd1 if cd1 else y1)
            cx0, cx1 = cfg["num_x"]
            numtxt = _rec_line(strip, (int(sw*cx0), cy0, int(sw*cx1), cy1), 4).strip()
            hp = _digits(numtxt)
            if hp is None:
                continue
            rows.append({"hp": hp, "y": y0,
                         "name": name if _has_cjk(name) else None})
        fast = len(rows) >= 4
    else:
        fast = False

    # ---- 慢速回退：整条竖带跑 det ----
    if not fast:
        s = cfg["scale"]
        c = strip.resize((int(sw*s), int(strip.height*s)), Image.LANCZOS)
        res, _ = _get_ocr()(np.asarray(c)[:, :, ::-1], box_thresh=0.2, thresh=0.2)
        items = []
        for poly, txt, conf in (res or []):
            ys = [p[1] for p in poly]
            items.append({"y": (min(ys)+max(ys))/2/s, "text": txt.strip()})
        items.sort(key=lambda d: d["y"])
        names = [i for i in items if _has_cjk(i["text"])]
        rows = []
        for i in items:
            hp = _digits(i["text"]) if not _has_cjk(i["text"]) else None
            if hp is None:
                continue
            cand = [m for m in names if 0 < (i["y"] - m["y"]) < 90]
            cand.sort(key=lambda m: i["y"] - m["y"])
            rows.append({"hp": hp, "y": i["y"],
                         "name": cand[0]["text"] if cand else None})

    rows.sort(key=lambda x: x["y"])
    # 排行榜：血量单调不增，违反即截断
    clean, last = [], None
    for x in rows:
        if last is not None and x["hp"] > last:
            break
        clean.append(x)
        last = x["hp"]
    clean = clean[:8]

    players = [{"rank": i, "name": x["name"], "hp": x["hp"], "is_self": False}
               for i, x in enumerate(clean, 1)]
    if cfg["self_rule"] == "no_name":
        for p in players:
            if not p["name"]:
                p["is_self"] = True
                p["name"] = "（我）"
                break
    me = next((p for p in players if p["is_self"]), None)
    return {"layout": layout, "fast": fast, "players": players, "self": me}
