# -*- coding: utf-8 -*-
"""生成「分割结果」可视化：左=原图打框，右=实际送进模型的裁剪块。
用法: python make_crop_preview.py <截图> [输出png]
     （需要先 python vlm_board_scan.py <截图> --save-crops 生成 crop_*.png）
"""
import sys
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "core"))
from vlm_board_scan import REGIONS, ORDER  # 直接复用坐标定义，避免两份真相

SRC = sys.argv[1] if len(sys.argv) > 1 else None
if not SRC:
    print("用法: python make_crop_preview.py <截图> [输出png]")
    sys.exit(1)

base = os.path.join(HERE, "..", "output", "crops_sample",
                    "crop_%s_" % os.path.splitext(os.path.basename(SRC))[0])
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "output", "分割结果预览.png")

CN = {"stage": "① 回合", "level_exp": "② 等级+经验", "gold": "③ 金币",
      "shop": "④ 商店 5 张卡", "board": "⑤ 棋盘"}
COLOR = {"stage": (255, 80, 80), "level_exp": (255, 200, 60), "gold": (90, 240, 255),
         "shop": (120, 255, 130), "board": (255, 130, 255)}

font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 22)
small = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 17)

img = Image.open(SRC).convert("RGB")
W, H = img.size
left_w = 900
sc = left_w / W
left = img.resize((left_w, int(H * sc)), Image.LANCZOS)
d = ImageDraw.Draw(left)
for k, spec in REGIONS.items():
    l, t, r, b = spec["box"]
    d.rectangle([l*left_w, t*H*sc, r*left_w, b*H*sc], outline=COLOR[k], width=3)
    d.text((l*left_w + 4, max(0, t*H*sc - 20)), CN[k], font=small, fill=COLOR[k])

right_w = 820
pad, gap = 16, 44
crops = []
for k in ORDER:
    im = Image.open(base + k + ".png").convert("RGB")
    w = min(right_w, im.width)
    im2 = im.resize((w, max(1, int(im.height * w / im.width))), Image.LANCZOS)
    crops.append((k, im, im2))

canvas_h = max(left.height + 56, sum(i.height + gap for _, _, i in crops) + 70)
cv = Image.new("RGB", (left_w + right_w + pad*3, canvas_h), (16, 16, 20))
cv.paste(left, (pad, 56))
d2 = ImageDraw.Draw(cv)
d2.text((pad, 16), "① 原图：5 个裁剪框", font=font, fill=(235, 235, 235))
d2.text((left_w + pad*2, 16), "② 实际送进 VLM 的裁剪图（未识别）", font=font, fill=(235, 235, 235))

y = 56
for k, orig, im2 in crops:
    x = left_w + pad*2
    cv.paste(im2, (x, y))
    d2.rectangle([x, y, x + im2.width, y + im2.height], outline=COLOR[k], width=2)
    info = "%s   %dx%d  %.0f KB  ≈%d image tokens" % (
        CN[k], orig.width, orig.height,
        os.path.getsize(base + k + ".png")/1024, orig.width*orig.height/784)
    d2.text((x, y + im2.height + 4), info, font=small, fill=COLOR[k])
    y += im2.height + gap

cv.save(OUT)
print("saved", OUT, cv.size)
