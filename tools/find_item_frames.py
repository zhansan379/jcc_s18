# -*- coding: utf-8 -*-
"""
通用「方块边框」检测：支持两种边框风格
  dark  —— 金铲铲手游：黑色边框（val<40）
  gold  —— 云顶之弈 PC：金色边框（R高 G中 B低）
  auto  —— 两种都试，取检出多者

算法：长边框线定上边 -> 左右竖边向下生长定下边 -> 内部色彩过滤
"""
import argparse
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

MIN_W, MAX_W = 22, 44
MIN_H, MAX_H = 22, 48


def runs(m, minlen):
    idx = np.flatnonzero(m)
    if idx.size == 0:
        return []
    g = np.split(idx, np.where(np.diff(idx) != 1)[0] + 1)
    return [(int(x[0]), int(x[-1]) + 1) for x in g if len(x) >= minlen]


def border_mask(a, style):
    r = a[:, :, 0].astype(np.int16)
    g = a[:, :, 1].astype(np.int16)
    b = a[:, :, 2].astype(np.int16)
    mx = a.max(axis=2).astype(np.int16)
    if style == "dark":
        return mx < 40
    # 金框：偏黄橙、亮度中等以上、蓝通道明显低
    return (r > 120) & (g > 80) & (b < 130) & ((r - b) > 45) & ((g - b) > 20)


def find_frames(a, style):
    H, W = a.shape[:2]
    sat = (a.max(axis=2) - a.min(axis=2)).astype(np.float32)
    val = a.max(axis=2).astype(np.float32)
    bm = border_mask(a, style)
    out = []
    for y in range(2, H - MIN_H):
        for (xa, xb) in runs(bm[y], MIN_W):
            if not (MIN_W <= xb - xa <= MAX_W):
                continue
            if any(abs(xa - p[0]) < 6 and abs(y - p[1]) < 4 for p in out):
                continue
            y1 = y
            for yy in range(y + 1, min(H, y + MAX_H)):
                left = bm[yy, max(0, xa-1):xa+2].any()
                right = bm[yy, max(0, xb-2):xb+1].any()
                if not (left or right):
                    break
                y1 = yy
            if not (MIN_H <= y1 - y <= MAX_H):
                continue
            ins = sat[y+3:y1-1, xa+3:xb-3]
            inv = val[y+3:y1-1, xa+3:xb-3]
            if ins.size == 0 or ins.mean() < 18 or inv.mean() < 55:
                continue
            out.append((int(xa), int(y), int(xb), int(y1 + 1)))
    # 去重
    uniq = []
    for b in sorted(out, key=lambda t: (t[1], t[0])):
        if not any(abs(b[0]-u[0]) < 5 and abs(b[1]-u[1]) < 5 for u in uniq):
            uniq.append(b)
    uniq.sort(key=lambda t: (t[1] // 40, t[0]))
    return uniq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--style", choices=["dark", "gold", "auto"], default="auto")
    ap.add_argument("-o", "--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "output"))
    ap.add_argument("--tag", default="item_frames")
    ap.add_argument("--roi", default=None,
                    help="限定搜索区域 x0,y0,x1,y1（占整图比例，逗号分隔）")
    a = ap.parse_args()

    img = Image.open(a.image).convert("RGB")
    arr = np.asarray(img).astype(np.int16)
    W, H = img.size

    ox = oy = 0
    if a.roi:
        x0, y0, x1, y1 = [float(t) for t in a.roi.split(",")]
        ox, oy = int(x0 * W), int(y0 * H)
        arr = arr[oy:int(y1 * H), ox:int(x1 * W)]

    if a.style == "auto":
        cand = {s: find_frames(arr, s) for s in ("dark", "gold")}
        style = max(cand, key=lambda s: len(cand[s]))
        frames = cand[style]
        print("auto -> 采用 %s 风格（dark %d / gold %d）" % (style, len(cand["dark"]), len(cand["gold"])))
    else:
        style = a.style
        frames = find_frames(arr, style)

    frames = [(b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy) for b in frames]
    print("检出 %d 个方块" % len(frames))
    for i, b in enumerate(frames):
        print("  #%-2d [%d,%d,%d,%d]  %dx%d" % (i+1, b[0], b[1], b[2], b[3], b[2]-b[0], b[3]-b[1]))

    os.makedirs(a.out, exist_ok=True)
    if frames:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 22)
        small = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 15)
        CW, CH = 190, 235
        cols = min(9, len(frames))
        rows = (len(frames) + cols - 1)//cols
        sh = Image.new("RGB", (cols*CW, rows*CH + 34), (16, 16, 20))
        sd = ImageDraw.Draw(sh)
        sd.text((8, 6), "按边框自动切出的方块（%s）" % style, font=font, fill=(255, 220, 80))
        for i, b in enumerate(frames):
            c = img.crop(b)
            c = c.resize((c.width*8, c.height*8), Image.LANCZOS)
            c.thumbnail((CW-10, CH-42), Image.LANCZOS)
            px, py = (i % cols)*CW, (i//cols)*CH + 34
            sh.paste(c, (px+5, py+20))
            sd.text((px+5, py+1), "#%d %dx%d" % (i+1, b[2]-b[0], b[3]-b[1]), font=small, fill=(215, 215, 215))
        sh.save(os.path.join(a.out, a.tag + ".png"))

    with open(os.path.join(a.out, a.tag + ".json"), "w", encoding="utf-8") as f:
        json.dump({"file": os.path.basename(a.image), "style": style, "数量": len(frames),
                   "方块px": [list(b) for b in frames],
                   "方块比例": [[round(b[0]/W, 4), round(b[1]/H, 4),
                              round(b[2]/W, 4), round(b[3]/H, 4)] for b in frames]},
                  f, ensure_ascii=False, indent=2)
    print("saved ->", a.out)


if __name__ == "__main__":
    main()
