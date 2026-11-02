# -*- coding: utf-8 -*-
"""
左侧羁绊面板 → [{"name","count","tiers","active"}]
=================================================
只针对「金铲铲之战（PC 模拟器）」这一种客户端，但窗口宽高比有两种，
所以按宽高比分两套坐标（面板按高度缩放，宽度不同锚点位置会变）：

  16_9   —— 1919×1097（模拟器 16:9 窗口）
  wide   —— 2712×1220（更宽的窗口）

两种布局的排版也不同：
  16_9：名字一行，下面一行是 "当前/下一档"（如 2/3）
  wide：名字一行，下面一行左边是数量、右边是完整档位串（如 2 / 2/4/6）
"""
import re

import numpy as np
from PIL import Image

LAYOUTS = {
    "16_9": dict(box=(0.050, 0.075, 0.190, 0.580), y0=28, pitch=72.8,
                 name=(70, 178, -8, 22), num=(66, 200, 24, 54), tiers=None,
                 scale=3),
    "wide": dict(box=(0.030, 0.050, 0.190, 0.680), y0=80, pitch=102.8,
                 name=(205, 430, -16, 34), num=(196, 231, 34, 72),
                 tiers=(232, 430, 34, 72), scale=3),
}

_ocr = None


def _get_ocr():
    """复用 ocr_extract 里那个实例（串行跑，不并发），省掉一次 ~0.9s 模型加载"""
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
    """两种布局都是金铲铲，只是窗口宽高比不同"""
    W, H = size
    return "wide" if W / H > 2.0 else "16_9"


_DIGIT_FIX = {"T": "1", "一": "1", "I": "1", "l": "1", "O": "0", "o": "0",
              "S": "5", "B": "8", "Z": "2", "g": "9", "q": "9"}


def _norm(s):
    s = re.sub(r"\s", "", s or "")
    return "".join(_DIGIT_FIX.get(ch, ch) for ch in s)


def _read(panel, box, scale):
    x0, x1, y0, y1 = box
    sub = panel.crop((x0, int(y0), x1, int(y1)))
    if sub.width < 8 or sub.height < 8:
        return ""
    sub = sub.resize((sub.width*scale, sub.height*scale), Image.LANCZOS)
    r, _ = _get_ocr()(np.asarray(sub)[:, :, ::-1], use_det=False, use_cls=False)
    if not r:
        return ""
    return r[0][0] if len(r[0]) == 2 else r[0][1]


def extract(img, layout=None, max_rows=7):
    if layout is None:
        layout = pick_layout(img.size)
    cfg = LAYOUTS[layout]
    l, t, r, b = cfg["box"]
    W, H = img.size
    panel = img.crop((int(l*W), int(t*H), int(r*W), int(b*H)))

    out = []
    for k in range(max_rows):
        y = cfg["y0"] + k*cfg["pitch"]
        if y + 60 > panel.height:
            break
        nx0, nx1, ny0, ny1 = cfg["name"]
        name = _read(panel, (nx0, nx1, y+ny0, y+ny1), cfg["scale"]).strip()
        if not name or not any("\u4e00" <= ch <= "\u9fff" for ch in name):
            break

        cx0, cx1, cy0, cy1 = cfg["num"]
        num = _norm(_read(panel, (cx0, cx1, y+cy0, y+cy1), cfg["scale"]))

        count, tiers = None, None
        if cfg.get("tiers"):
            tx0, tx1, ty0, ty1 = cfg["tiers"]
            tv = _norm(_read(panel, (tx0, tx1, y+ty0, y+ty1), cfg["scale"]))
            m = re.search(r"\d{1,2}", num)
            count = int(m.group()) if m else None
            parts = re.findall(r"\d{1,2}", tv) if tv else []
            if len(parts) >= 2:
                tiers = "/".join(parts)
        else:
            # 16_9：整行就是 "当前/下一档" 或 "当前 / 2/4/6"
            parts = re.findall(r"\d{1,2}", num)
            if parts:
                count = int(parts[0])
                if len(parts) >= 2:
                    tiers = "/".join(parts[1:])

        active = None
        if tiers and count is not None:
            nums = [int(x) for x in tiers.split("/")]
            cands = [x for x in nums if x <= count]
            active = max(cands) if cands else None
        out.append({"name": name, "count": count, "tiers": tiers, "active": active})
    return out
