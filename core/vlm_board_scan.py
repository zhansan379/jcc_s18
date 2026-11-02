# -*- coding: utf-8 -*-
"""
金铲铲 / 云顶之弈 截图信息提取（VLM 版，3 秒内出结果）
=====================================================
把整张截图按 UI 分区裁剪 → 并行调用百炼 qwen3-vl-plus → 汇总成结构化 JSON。

为什么能压到 3 秒内：
  * 不送整图，只送 5 个小裁剪块（单块 20~80KB，图像 token 少）
  * 5 个请求并行发出，总耗时 ≈ 最慢的那一个，而不是相加
  * max_tokens 卡死（每块只让它吐几十个 token）
  * 关闭思考模式（qwen3-vl-plus 默认就是关的）

用法：
    python vlm_board_scan.py 截图1.png [截图2.png ...]
    python vlm_board_scan.py 图1.png --budget 3 --json out.json --save-crops
    python vlm_board_scan.py 图1.png --deep      # 额外识别棋子名字（会超 3s）

实测（1919×1097 截图）：stage 0.52s / level+exp 0.86s / gold 0.74s
                        shop 1.21s / board 1.22s → 总计 1.8s
"""
import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = "qwen3-vl-plus"
# 不内置任何 key：用环境变量 DASHSCOPE_API_KEY（见 README）
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()

# ---------------------------------------------------------------- 分区定义
# (左, 上, 右, 下) 均为整图的百分比，适配 16:9 及其近似比例（实测 1.75 可用）
REGIONS = {
    "stage": dict(
        box=(0.325, 0.005, 0.385, 0.045), scale=4.0, tokens=16, key="阶段",
        prompt="这是游戏顶部回合数字，形如 2-6。只输出这个数字本身，不要任何解释。"),
    "level_exp": dict(
        box=(0.170, 0.750, 0.280, 0.820), scale=3.0, tokens=48, key="等级经验",
        prompt='这是等级与经验面板。只输出 JSON：{"level":等级数字,"exp":"当前xp/上限xp"}'),
    "gold": dict(
        box=(0.462, 0.750, 0.548, 0.820), scale=3.0, tokens=10, key="金币",
        prompt="这是金币图标旁的数字。只输出这个整数，不要任何解释。"),
    "shop": dict(
        box=(0.290, 0.826, 0.868, 1.000), scale=1.8, tokens=120, key="商店",
        prompt=('这是商店的 5 张卡（从左到右）。每张卡最底部那行字是英雄名，'
                '上面带图标的小字是羁绊。只输出 JSON 数组，长度 5：'
                '写每张卡底部的英雄名；若是文字型事件卡就照抄卡面文字；空槽写 null。')),
    "board": dict(
        box=(0.200, 0.150, 0.780, 0.780), scale=1.3, tokens=40, key="棋子",
        prompt=("这是自走棋棋盘。只统计绿色血条（己方）单位的数量。"
                '只输出 JSON：{"own":数量}')),
}
ORDER = ["stage", "level_exp", "gold", "shop", "board"]


# ---------------------------------------------------------------- 工具函数
def make_crop(img, spec, max_width=900):
    l, t, r, b = spec["box"]
    W, H = img.size
    c = img.crop((int(l * W), int(t * H), int(r * W), int(b * H)))
    s = spec["scale"]
    c = c.resize((max(1, int(c.width * s)), max(1, int(c.height * s))), Image.LANCZOS)
    if c.width > max_width:
        c = c.resize((max_width, max(1, int(c.height * max_width / c.width))), Image.LANCZOS)
    buf = io.BytesIO()
    c.save(buf, "JPEG", quality=82)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return "data:image/jpeg;base64," + b64, c, len(buf.getvalue())


def ask(name, data_url, prompt, max_tokens, deadline):
    """单次 VLM 调用；超出 deadline 直接放弃"""
    if not API_KEY:
        return name, None, "no-key（设置环境变量 DASHSCOPE_API_KEY）"
    left = deadline - time.perf_counter()
    if left <= 0.05:
        return name, None, "timeout(before send)"
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": prompt},
        ]}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + API_KEY,
                 "Content-Type": "application/json"}, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=max(0.3, left)) as r:
            d = json.loads(r.read().decode())
        return name, time.perf_counter() - t0, d["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        return name, time.perf_counter() - t0, "HTTP%d %s" % (
            e.code, e.read().decode("utf-8", "ignore")[:120])
    except Exception as e:                      # 超时 / 网络
        return name, time.perf_counter() - t0, "%s: %s" % (type(e).__name__, str(e)[:80])


def parse_json(text):
    """模型偶尔会包 ```json ... ```，这里做容错"""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```")[1]
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    s = s.strip()
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i, j = s.find(open_c), s.rfind(close_c)
        if i >= 0 and j > i:
            try:
                return json.loads(s[i:j + 1])
            except Exception:
                pass
    return None


# ---------------------------------------------------------------- 主流程
def scan(path, budget=3.0, save_crops=False, deep=False):
    t_start = time.perf_counter()
    deadline = t_start + budget

    img = Image.open(path).convert("RGB")
    jobs = []
    for name in ORDER:
        spec = REGIONS[name]
        data_url, crop_img, nbytes = make_crop(img, spec)
        if save_crops:
            out = os.path.splitext(os.path.basename(path))[0]
            crop_img.save("crop_%s_%s.png" % (out, name))
        jobs.append((name, data_url, spec, nbytes))

    if deep:
        jobs.append(("board_deep", jobs[-1][1], dict(
            prompt=('这是自走棋棋盘。列出盘上绿色血条（己方）单位，'
                    '只输出 JSON：{"units":["英雄名",...]}。认不出写 "?"，禁止编造。'),
            tokens=260), 0))

    results, timings = {}, {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs = {}
        for name, data_url, spec, _ in jobs:
            futs[name] = ex.submit(ask, name, data_url, spec["prompt"],
                                   spec["tokens"], deadline)
        for name, fut in futs.items():
            rname, dt, text = fut.result()
            timings[rname] = dt
            results[rname] = text

    # ---- 归一化 ----
    out = {"file": os.path.basename(path)}
    out["阶段"] = (results.get("stage") or "").strip().strip("。") or None

    le = parse_json(results.get("level_exp")) or {}
    out["等级"] = le.get("level")
    out["经验"] = le.get("exp")

    g = (results.get("gold") or "").strip()
    out["金币"] = int("".join(ch for ch in g if ch.isdigit())) if any(ch.isdigit() for ch in g) else None

    shop = parse_json(results.get("shop"))
    if isinstance(shop, list):
        shop = (shop + [None] * 5)[:5]
    out["商店"] = shop

    bd = parse_json(results.get("board")) or {}
    out["棋子"] = {"数量": bd.get("own"), "列表": None}
    if deep:
        dl = parse_json(results.get("board_deep")) or {}
        if isinstance(dl, dict) and "units" in dl:
            out["棋子"]["列表"] = dl["units"]

    out["_raw"] = {k: (v[:200] if isinstance(v, str) else v) for k, v in results.items()}
    out["_耗时"] = {
        "各分区": {k: round(v, 2) for k, v in timings.items()},
        "总计": round(time.perf_counter() - t_start, 2),
        "预算": budget,
    }
    return out


def main():
    ap = argparse.ArgumentParser(description="截图信息提取（VLM，3s 内）")
    ap.add_argument("images", nargs="+", help="截图路径，可多张")
    ap.add_argument("--budget", type=float, default=3.0, help="总时间预算（秒），默认 3.0")
    ap.add_argument("--json", help="把结果写到这个 json 文件")
    ap.add_argument("--save-crops", action="store_true", help="保存裁剪块，便于调坐标")
    ap.add_argument("--deep", action="store_true", help="额外识别棋子名字（实测会超过 3s）")
    a = ap.parse_args()

    all_out = []
    for p in a.images:
        if not os.path.exists(p):
            print("[跳过] 文件不存在:", p, file=sys.stderr)
            continue
        r = scan(p, budget=a.budget, save_crops=a.save_crops, deep=a.deep)
        all_out.append(r)

        print("\n=== %s ===" % r["file"])
        print("  阶段   :", r["阶段"])
        print("  等级   :", r["等级"], " 经验:", r["经验"])
        print("  金币   :", r["金币"])
        print("  商店   :", " / ".join(str(x) for x in (r["商店"] or [])) or "未识别")
        print("  棋子   :", r["棋子"]["数量"], "个（己方）",
              ("  " + str(r["棋子"]["列表"])) if r["棋子"]["列表"] else "")
        t = r["_耗时"]
        print("  耗时   : %.2fs  (预算 %.1fs)  明细: %s" % (
            t["总计"], t["预算"],
            ", ".join("%s=%.2f" % (k, v) for k, v in t["各分区"].items())))

    payload = all_out[0] if len(all_out) == 1 else all_out
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("\n[已写入]", a.json)
    else:
        print("\n" + json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
