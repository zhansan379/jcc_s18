# -*- coding: utf-8 -*-
"""
纯文本字段的本地 OCR 提取（不调云端，全部本机完成）

比 vlm_board_scan.py 快 3~10 倍，代价是坐标必须更精确。
棋盘（3D 棋子）没有文字，OCR 帮不上，仍需 VLM。

用法:
    python ocr_extract.py 截图.png [截图2.png ...] [--json out.json]
依赖: rapidocr-onnxruntime  (pip install -i https://mirrors.aliyun.com/pypi/simple/ rapidocr-onnxruntime)
"""
import argparse
import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vlm_board_scan import REGIONS          # 复用同一份分区坐标

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    print("缺依赖: pip install -i https://mirrors.aliyun.com/pypi/simple/ rapidocr-onnxruntime")
    sys.exit(1)

# 在每个分区内部，纯文字的精确定位框（占该分区宽高的比例）
# 由 det 网络标定一次后写死；跳过检测网络是提速的关键
TIGHT = {
    "stage":       [(0.633, 0.114, 0.998, 0.705)],
    "level_exp":   [(0.098, 0.446, 0.302, 0.827),      # 4级
                    (0.594, 0.584, 0.798, 0.801)],     # 4/10
    "gold":        [(0.420, 0.502, 0.640, 0.784)],     # 20（左侧留出金币图标之外）
    "shop":        [(x0, 0.735, x1, 0.880) for x0, x1 in
                    [(0.000, 0.185), (0.185, 0.375), (0.375, 0.565),
                     (0.565, 0.750), (0.750, 0.900)]],  # 5 张卡底部英雄名
}

_ocr = None


def get_ocr():
    global _ocr
    if _ocr is None:
        _ocr = RapidOCR()
    return _ocr


def _rec(img_rgb, box):
    """在给定比例框内做纯识别（跳过检测），返回文字"""
    h, w = img_rgb.shape[:2]
    x0, y0, x1, y1 = box
    sub = img_rgb[int(y0*h):int(y1*h), int(x0*w):int(x1*w)]
    if sub.size == 0:
        return ""
    r, _ = get_ocr()(sub, use_det=False, use_cls=False)
    if not r:
        return ""
    return r[0][0] if len(r[0]) == 2 else r[0][1]


def _region_array(img, name):
    l, t, r, b = REGIONS[name]["box"]
    W, H = img.size
    c = img.crop((int(l*W), int(t*H), int(r*W), int(b*H)))
    return np.asarray(c.convert("RGB"))[:, :, ::-1]


# 金币框最容易踩的坑：左边界稍偏就把金币图标读成 "8"/"9"。
# 用两个不同左边界各读一次，结果一致才采信；不一致就判为失败，交给 VLM 回落。
GOLD_X0 = (0.44, 0.52)


def _gold_agree(img):
    arr = _region_array(img, "gold")
    _, y0, _, y1 = TIGHT["gold"][0]
    h, w = arr.shape[:2]
    outs = []
    for x0 in GOLD_X0:
        sub = arr[int(y0*h):int(y1*h), int(x0*w):int(0.72*w)]
        if sub.size == 0:
            continue
        r, _ = get_ocr()(sub, use_det=False, use_cls=False)
        if r:
            outs.append(r[0][0] if len(r[0]) == 2 else r[0][1])
    if not outs or len(set(outs)) != 1:
        return None          # 两次结果不一致 → 判为不可信
    return outs[0]


def extract_fields(img):
    """对 PIL.Image 提取 4 个纯文本字段，返回 (dict, 耗时ms)。供 scan.py 复用。"""
    t0 = time.perf_counter()
    out = {}

    out["阶段"] = _rec(_region_array(img, "stage"), TIGHT["stage"][0]) or None

    lv = _rec(_region_array(img, "level_exp"), TIGHT["level_exp"][0])
    ex = _rec(_region_array(img, "level_exp"), TIGHT["level_exp"][1])
    m = re.search(r"\d+", lv)
    out["等级"] = int(m.group()) if m else None
    out["经验"] = ex if "/" in ex else None

    g = _gold_agree(img)
    m = re.search(r"\d+", g or "")
    out["金币"] = int(m.group()) if m else None

    arr = _region_array(img, "shop")
    names = []
    for box in TIGHT["shop"]:
        s = _rec(arr, box)
        s = re.sub(r"[\d\s]+$", "", s)
        s = re.sub(r"[\s]+$", "", s)
        names.append(s or None)
    out["商店"] = names

    return out, round((time.perf_counter() - t0) * 1000)


def extract(path):
    img = Image.open(path).convert("RGB")
    out, ms = extract_fields(img)
    out["file"] = os.path.basename(path)
    out["_耗时ms"] = ms
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--json")
    a = ap.parse_args()

    t_warm = time.perf_counter()
    get_ocr()
    print("[i] OCR 模型加载 %.0fms（仅首次）" % ((time.perf_counter()-t_warm)*1000))

    res = []
    for p in a.images:
        if not os.path.exists(p):
            print("[跳过]", p, file=sys.stderr); continue
        r = extract(p)
        res.append(r)
        print("\n=== %s ===" % r["file"])
        print("  阶段 %s | 等级 %s | 经验 %s | 金币 %s" %
              (r["阶段"], r["等级"], r["经验"], r["金币"]))
        print("  商店 %s" % r["商店"])
        print("  耗时 %dms" % r["_耗时ms"])

    payload = res[0] if len(res) == 1 else res
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("\n[已写入]", a.json)
    else:
        print("\n" + json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
