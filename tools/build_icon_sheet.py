# -*- coding: utf-8 -*-
"""把 S18 的 65 张英雄图标拼成带编号的对照表（sheet_s18.png）。"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "data", "heroicons_s18")
OUT = os.path.join(HERE, "..", "data", "sheet_s18.png")

files = sorted(os.listdir(ROOT))
CELL = 110
COLS = 9
rows = (len(files) + COLS - 1) // COLS
sheet = Image.new("RGB", (COLS * CELL, rows * CELL), (25, 25, 30))
d = ImageDraw.Draw(sheet)
try:
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 14)
except Exception:
    font = ImageFont.load_default()

for i, f in enumerate(files):
    im = Image.open(os.path.join(ROOT, f)).convert("RGB")
    im.thumbnail((CELL - 8, CELL - 24), Image.LANCZOS)
    x, y = (i % COLS) * CELL, (i // COLS) * CELL
    sheet.paste(im, (x + (CELL - im.width) // 2, y + (CELL - 24 - im.height) // 2))
    d.rectangle([x, y, x + CELL - 1, y + CELL - 1], outline=(70, 70, 80))
    d.text((x + 3, y + CELL - 20), "%d" % (i + 1), font=font, fill=(255, 220, 80))

sheet.save(OUT)
with open(os.path.join(HERE, "..", "data", "s18_index.txt"), "w", encoding="utf-8") as fh:
    for i, f in enumerate(files):
        fh.write("%d\t%s\n" % (i + 1, f))
print("saved", OUT, sheet.size, "items", len(files))
