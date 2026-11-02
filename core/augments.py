# -*- coding: utf-8 -*-
"""
强化符文（Augment）图标识别
==========================
图标库：data/augmenticons_s18/<符文名称>.png   （256 张 200×200，透明背景）
         data/augmenticons_ingame/<符文名称>.png（游戏内模板，同名优先）
索引：  data/augmenticons_s18_index.json      文件名 -> {hexId, 稀有度, 出现回合, 描述}

要点：
  * 参考图是**透明底**，比对前要合成到「截图图标自己的底色」（自动取裁剪里的众数色）。
  * 库里有若干**字节完全相同**的图（同图案的不同稀有度），加载时按 MD5 去重。
  * 判定要看**排名 + 与第二名的差距**，不要只看绝对分数。
"""
import hashlib
import json
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "data")
IMG_DIR = os.path.join(DB, "augmenticons_s18")
INGAME_DIR = os.path.join(DB, "augmenticons_ingame")   # 游戏内截图模板，优先使用
INDEX = os.path.join(DB, "augmenticons_s18_index.json")

_refs = None
_ref_cache = {}
_shape_cache = None
_index = None

# 低于这个分数视为「库里没有」
MIN_SCORE = 0.80
# 前两名差距小于这个值也判为「分不清」
MIN_GAP = 0.03


def build_index():
    global _index
    if _index is None:
        _index = json.load(open(INDEX, encoding="utf-8")) if os.path.exists(INDEX) else {}
    return _index


def sample_bg(pil):
    """图标底色 = 裁剪里出现次数最多的颜色（游戏内是深蓝，参考图是透明）"""
    a = np.asarray(pil.convert("RGB")).reshape(-1, 3)
    if a.size == 0:
        return (0, 0, 0)
    q = a // 16
    keys, counts = np.unique(q, axis=0, return_counts=True)
    k = keys[int(np.argmax(counts))]
    sel = (q == k).all(axis=1)
    return tuple(int(v) for v in np.median(a[sel], axis=0))


def _feat(im, bg, size=56):
    im = im.convert("RGBA")
    b = Image.new("RGBA", im.size, tuple(bg) + (255,))
    im = Image.alpha_composite(b, im).convert("RGB").resize((size, size), Image.LANCZOS)
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


def _load_refs():
    """加载参考图。**游戏内截图模板优先**（同名的原画会被跳过），再按 MD5 去重。"""
    global _refs
    if _refs is None:
        names, seen, ingame = [], {}, set()
        dirs = [d for d in (INGAME_DIR, IMG_DIR) if os.path.isdir(d)]
        for d in dirs:
            for f in sorted(os.listdir(d)):
                if not f.lower().endswith(".png"):
                    continue
                stem = os.path.splitext(f)[0]
                if stem in seen:          # 同名：先加载的（ingame）留下
                    continue
                p = os.path.join(d, f)
                h = hashlib.md5(Image.open(p).convert("RGBA").tobytes()).hexdigest()
                if h in seen:
                    continue
                seen[stem] = f
                seen[h] = f
                names.append(stem)
                if d == INGAME_DIR:
                    ingame.add(stem)
        _refs = {"names": names, "seen": seen, "ingame": ingame}
    return _refs


def _matrix(bg):
    key = tuple(bg)
    if key not in _ref_cache:
        refs = _load_refs()
        G, Hh, C = [], [], []
        for n in refs["names"]:
            for d in (INGAME_DIR, IMG_DIR):
                p = os.path.join(d, n + ".png")
                if os.path.exists(p):
                    break
            g, h, c = _feat(Image.open(p), bg)
            G.append(g.ravel()); Hh.append(h); C.append(c)
        G = np.array(G, dtype=np.float32)
        G -= G.mean(axis=1, keepdims=True)
        G /= (np.linalg.norm(G, axis=1, keepdims=True) + 1e-6)
        _ref_cache[key] = (G, np.array(Hh, dtype=np.float32), np.array(C, dtype=np.float32))
    return _ref_cache[key]

# ------------------------------------------------------------------ 形状匹配
def _q_mask(im, size=128):
    """游戏内图标 -> 金色图案掩膜"""
    from scipy import ndimage
    a = np.asarray(im.convert("RGB").resize((size, size), Image.LANCZOS)).astype(np.int16)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    m = ((R > 85) & (R > B + 15) & (G > 55)) | (a.max(axis=2) > 200)
    m = ndimage.binary_closing(m, np.ones((2, 2)))
    return ndimage.binary_opening(m, np.ones((2, 2)))


def _r_mask(path, size=128):
    from scipy import ndimage
    al = Image.open(path).convert("RGBA").split()[-1].resize((size, size), Image.LANCZOS)
    return ndimage.binary_closing(np.asarray(al) > 110, np.ones((2, 2)))


def _norm_mask(m, n=64):
    """裁到图案自身包围盒再等比缩放到 n×n —— **这一步解决尺度不一致**"""
    ys, xs = np.where(m)
    if len(ys) < 10:
        return np.zeros((n, n), bool)
    sub = m[ys.min():ys.max()+1, xs.min():xs.max()+1]
    h, w = sub.shape
    k = n / max(h, w)
    nh, nw = max(1, int(h*k)), max(1, int(w*k))
    arr = np.asarray(Image.fromarray((sub*255).astype(np.uint8))
                     .resize((nw, nh), Image.LANCZOS)) > 110
    out = np.zeros((n, n), bool)
    oy, ox = (n-nh)//2, (n-nw)//2
    out[oy:oy+nh, ox:ox+nw] = arr
    return out


def _shape_refs():
    """缓存所有参考图的归一化掩膜。
    游戏内模板是 RGB（无 alpha），要用「金色图案」提取掩膜；
    官方原画是透明底，用 alpha 通道提取。
    """
    global _shape_cache
    if _shape_cache is not None:
        return _shape_cache
    refs = _load_refs()
    masks = []
    for n in refs["names"]:
        is_ingame = n in refs.get("ingame", set())
        for d in (INGAME_DIR, IMG_DIR):
            p = os.path.join(d, n + ".png")
            if os.path.exists(p):
                break
        raw = _q_mask(Image.open(p).convert("RGB")) if is_ingame else _r_mask(p)
        masks.append(_norm_mask(raw))
    _shape_cache = masks
    return _shape_cache


def _iou_shift(q, r, rad=3):
    """在 ±rad 像素内找最大 IoU（用 FFT 一次算完所有平移）"""
    from scipy.signal import fftconvolve
    inter = fftconvolve(q.astype(np.float32), r[::-1, ::-1].astype(np.float32), mode="same")
    n = q.shape[0]
    c = n // 2
    win = inter[c-rad:c+rad+1, c-rad:c+rad+1]
    aq, ar = int(q.sum()), int(r.sum())
    best = 0.0
    for v in win.ravel():
        i = round(float(v))
        u = aq + ar - i
        if u > 0:
            best = max(best, i/u)
    return best


def topk(pil, k=5):
    """pil = 截下来的符文图标。返回 [{name, hexId, rarity, score}]"""
    refs = _load_refs()
    if not refs["names"]:
        return []
    qm = _norm_mask(_q_mask(pil))
    masks = _shape_refs()
    scores = np.array([_iou_shift(qm, m) for m in masks], dtype=np.float32)
    order = np.argsort(-scores)[:k]
    idx = build_index()
    out = []
    for i in order:
        n = refs["names"][i]
        meta = idx.get(n + ".png") or {}
        out.append({"name": n, "hexId": meta.get("hexId"),
                    "rarity": meta.get("rarity"), "score": round(float(scores[i]), 3)})
    return out


# ------------------------------------------------------------------ 定位
def find_icons(img, min_side=28, max_side=90, min_gold=0.05):
    """在全图里找出「深蓝底 + 金色图案」的符文图标方块，并逐个匹配"""
    from scipy import ndimage
    a = np.asarray(img).astype(np.int16)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mx = a.max(axis=2)
    navy = (B > R + 25) & (B > G + 5) & (mx > 25) & (mx < 110)
    navy = ndimage.binary_closing(navy, np.ones((3, 3)))
    lab, n = ndimage.label(navy)
    out = []
    for sl, idx in zip(ndimage.find_objects(lab), range(1, n + 1)):
        if sl is None:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        w, h = x1 - x0, y1 - y0
        if not (min_side <= w <= max_side and min_side <= h <= max_side):
            continue
        if abs(w - h) > max(w, h) * 0.25:
            continue
        sub = a[y0:y1, x0:x1]
        gold = ((sub[:, :, 0] > 120) & (sub[:, :, 1] > 90) & (sub[:, :, 2] < 120)).mean()
        if gold < min_gold:
            continue
        crop = img.crop((x0, y0, x1, y1))
        top = topk(crop, 3)
        gap = (top[0]["score"] - top[1]["score"]) if len(top) > 1 else 1.0
        ok = bool(top) and top[0]["score"] >= MIN_SCORE and gap >= MIN_GAP
        out.append({"box": [int(x0), int(y0), int(x1), int(y1)],
                    "name": top[0]["name"] if ok else None,
                    "score": top[0]["score"] if top else 0.0,
                    "reliable": ok, "top": top})
    out.sort(key=lambda d: -d["score"])
    return out
