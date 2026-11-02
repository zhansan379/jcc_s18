# -*- coding: utf-8 -*-
"""
本地 OCR vs 云端 VLM —— 纯文本区域的速度/效果对比

跑法:  python bench_ocr_vs_vlm.py
输出:  终端表格 + 对比结果写入 bench_ocr_vs_vlm.json
"""
import base64
import io
import json
import os
import time
import urllib.request

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
if not KEY:
    raise SystemExit("请先设置环境变量 DASHSCOPE_API_KEY（本项目不内置 key）")
URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
SRC = r"D:\Download\00a5a489-ca7a-4216-bef0-81821a313981.png"
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..", "output", "crops_sample", "crop_00a5a489-ca7a-4216-bef0-81821a313981_")

# 各裁剪块内，纯文字的紧致子框（det 标定一次后写死，占该裁剪块的比例）
TIGHT = {
    "stage": [(0.633, 0.114, 0.998, 0.705)],
    "level_exp": [(0.098, 0.446, 0.302, 0.827), (0.594, 0.584, 0.798, 0.801)],
    "gold": [(0.420, 0.502, 0.640, 0.784)],
    "shop": [(x0, 0.735, x1, 0.880) for x0, x1 in
             [(0.00, 0.185), (0.185, 0.375), (0.375, 0.565), (0.565, 0.750), (0.750, 0.90)]],
}
GT = {"stage": "2-6", "level_exp": "4级 4/10", "gold": "20",
      "shop": "雷克塞 苍蓝哨戒 卡尔玛 苍蓝哨戒 拼一把小的"}

PROMPT = {
    "stage": "只输出回合数字，形如 2-6。",
    "level_exp": '只输出JSON：{"level":等级,"exp":"当前/上限"}',
    "gold": "只输出金币数字。",
    "shop": '这是商店5张卡，每张卡底部那行是英雄名。只输出JSON数组，长度5，空槽写null。',
}

ocr = RapidOCR()


def rec_tight(name):
    """只用识别网络，跳过检测网络"""
    im = np.asarray(Image.open(BASE + name + ".png").convert("RGB"))[:, :, ::-1]
    h, w = im.shape[:2]
    out = []
    t0 = time.perf_counter()
    for (x0, y0, x1, y1) in TIGHT[name]:
        sub = im[int(y0*h):int(y1*h), int(x0*w):int(x1*w)]
        if sub.size == 0:
            continue
        r, _ = ocr(sub, use_det=False, use_cls=False)
        if r:
            out.append(r[0][0] if len(r[0]) == 2 else r[0][1])
    return (time.perf_counter()-t0)*1000, out


def ocr_full(name):
    """检测 + 识别（不写死坐标）"""
    im = np.asarray(Image.open(BASE + name + ".png").convert("RGB"))[:, :, ::-1]
    t0 = time.perf_counter()
    r, _ = ocr(im)
    return (time.perf_counter()-t0)*1000, [x[1] for x in (r or [])]


def vlm(name):
    im = Image.open(BASE + name + ".png").convert("RGB")
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=85)
    url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    p = {"model": "qwen3-vl-plus",
         "messages": [{"role": "user", "content": [
             {"type": "image_url", "image_url": {"url": url}},
             {"type": "text", "text": PROMPT[name]}]}],
         "temperature": 0, "max_tokens": 120}
    req = urllib.request.Request(URL, data=json.dumps(p).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}, method="POST")
    t0 = time.perf_counter()
    d = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
    return (time.perf_counter()-t0)*1000, d["choices"][0]["message"]["content"].replace("\n", " ")


rows = []
print("%-10s %-9s %-9s %-9s" % ("区域", "VLM", "OCR(det)", "OCR(rec)"))
print("-" * 60)
for k in ["stage", "level_exp", "gold", "shop"]:
    tv, rv = vlm(k)
    td, rd = ocr_full(k)
    tr, rr = rec_tight(k)
    print("%-10s %7.0fms %7.0fms %7.0fms" % (k, tv, td, tr))
    rows.append({"区域": k, "标准答案": GT[k],
                 "VLM": {"ms": round(tv), "输出": rv[:120]},
                 "OCR_det": {"ms": round(td), "输出": rd[:8]},
                 "OCR_rec": {"ms": round(tr), "输出": rr}})

print("\n=== 输出明细 ===")
for r in rows:
    print("\n[%s]  标准: %s" % (r["区域"], r["标准答案"]))
    print("  VLM  %5dms  %s" % (r["VLM"]["ms"], r["VLM"]["输出"]))
    print("  OCR-det %5dms  %s" % (r["OCR_det"]["ms"], r["OCR_det"]["输出"]))
    print("  OCR-rec %5dms  %s" % (r["OCR_rec"]["ms"], r["OCR_rec"]["输出"]))
    if r["区域"] == "shop":
        print("  -> 取每张卡最后一段名字: %s" % [x for x in r["OCR_rec"]["输出"]])

with open(os.path.join(HERE, "..", "output", "bench_ocr_vs_vlm.json"), "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
print("\n已写入 bench_ocr_vs_vlm.json")
