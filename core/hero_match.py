# -*- coding: utf-8 -*-
"""
用人工标注的数据做英雄匹配
==========================
读 data/hero_labels/labels.json（labeler 产出的），把每个已标注裁剪图算成
16×16 模糊灰度描述子建索引；新截图里的棋子裁剪后做最近邻，余弦相似度取最大。

为什么这条路比 VLM 靠谱：
  - 同一渲染来源（都是游戏内 3D 模型），不像 2D 原画那样跨渲染
  - 不需要联网、不需要模型，单张图 5ms
  - 分数低就直接判「未知」，不会硬猜

用法：
    import hero_match
    stats = hero_match.name_units(img, units)   # units 来自 board_units.extract()
"""
import json
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.dirname(HERE), "data")
LABELS = os.path.join(DB, "hero_labels", "labels.json")

SIM_MIN = 0.94          # 与 hero_names.SIM_MIN 保持一致
_idx = None


def load_index():
    """返回 {"names":[...], "D":(N,256), "stars":[...], "paths":[...]}"""
    global _idx
    if _idx is not None:
        return _idx
    from hero_names import desc
    names, D, stars, paths = [], [], [], []
    if os.path.exists(LABELS):
        try:
            with open(LABELS, encoding="utf-8") as f:
                items = json.load(f).get("items", {})
        except Exception:
            items = {}
        for key, rec in items.items():
            name = rec.get("name")
            rel = rec.get("crop") or ("crops/%s.png" % key)
            p = os.path.join(DB, "hero_labels", rel)
            if not name or not os.path.exists(p):
                continue
            names.append(name)
            D.append(desc(Image.open(p).convert("RGB")))
            stars.append(rec.get("star"))
            paths.append(p)
    _idx = {"names": names,
            "D": np.asarray(D, dtype=np.float32) if D else np.zeros((0, 256), np.float32),
            "stars": stars, "paths": paths}
    return _idx


def reload():
    global _idx
    _idx = None
    return load_index()


def topk(pil, k=3):
    """返回 [{name, score, star}]，按分数降序"""
    idx = load_index()
    if not idx["names"]:
        return []
    from hero_names import desc
    q = np.asarray(desc(pil), dtype=np.float32)
    s = idx["D"] @ q / q.size                    # 已零均值单位方差 → 点积均值即余弦
    order = np.argsort(-s)[:k]
    return [{"name": idx["names"][i], "score": round(float(s[i]), 3),
             "star": idx["stars"][i]} for i in order]


def name_units(img, units, k=3):
    """给 board_units.extract() 的结果补 name；返回统计"""
    from hero_names import crop_unit
    stats = {"labeled": len(load_index()["names"]), "hit": 0, "miss": 0}
    for u in units:
        u.setdefault("name", None)
        u.setdefault("name_src", None)
        c = crop_unit(img, u)
        if c is None:
            stats["miss"] += 1
            continue
        cand = topk(c, k)
        if not cand:
            stats["miss"] += 1
            continue
        best = cand[0]
        u["name_top"] = cand
        if best["score"] >= SIM_MIN:
            u["name"], u["name_src"], u["name_score"] = best["name"], "label", best["score"]
            stats["hit"] += 1
        else:
            stats["miss"] += 1
    return stats
