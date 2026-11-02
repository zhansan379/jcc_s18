# -*- coding: utf-8 -*-
"""
英雄名称识别（VLM + 本地缓存）
================================
棋盘上的 3D 棋子 OCR 读不出名字，只能让 VLM 认。但**不需要每张图都调 VLM**：

  1) 每个单位按血条裁一块 → 算 16×16 模糊灰度描述子（256 维 float）
  2) 先查本地缓存（data/hero_names_cache.json），命中就直接用名字
  3) 没命中的去重后**拼成一张编号九宫格**，一次 VLM 请求全部认完
  4) 认得的结果写回缓存，下次同样的棋子（换回合/换截图）直接命中

缓存键 = 描述子 + 星级（星级会改变模型描边/配色）。
查找用余弦相似度 ≥ 0.94，容忍 ±3px 抖动与 JPEG 压缩。

用法：
    import hero_names
    hero_names.name_units(img, units)          # units 来自 board_units.extract()
    # 每个 unit 会多出 name / name_src ('cache'|'vlm') / name_score
"""
import hashlib
import json
import os
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.dirname(HERE), "data")
CACHE_PATH = os.path.join(DB, "hero_names_cache.json")

HAMMING_MAX = 6          # 已废弃（改用相似度）；保留兼容旧缓存文件
HASH_W = 16              # 描述子边长：16×16 灰度
SIM_MIN = 0.94           # 相似度阈值：实测同单位平移 ±3px 仍 ≥0.98，不同单位 ≤0.90
TILE = 224               # 拼图每格边长。112px 时 VLM 对同一张图会给不同答案，224 才稳定


# ------------------------------------------------------------------ 裁剪
def crop_unit(img, unit, pad_ratio=0.10, below=1.45, above=0.10):
    """按血条位置裁出棋子本体。

    血条在棋子头顶，所以主体在**血条下方**。
    收紧到 (1+2*0.10) 倍血条宽、1.45 倍血条宽高：
    之前 0.35 / 2.2 的宽松版本会把隔壁棋子和血条一起塞进来，
    VLM 会认成隔壁那个（实测「艾翁」被安在两种完全不同的模型上）。
    """
    W, H = img.size
    x0, y0, x1, y1 = unit["box"]
    w = max(1, x1 - x0)
    pad = int(w * pad_ratio)
    top = int(y0 - w * above)
    bot = int(y0 + w * below)
    cx0 = max(0, x0 - pad)
    cx1 = min(W, x1 + pad)
    cy0 = max(0, top)
    cy1 = min(H, bot)
    if cx1 <= cx0 or cy1 <= cy0:
        return None
    return img.crop((cx0, cy0, cx1, cy1))


# ------------------------------------------------------------------ 感知描述子
def dhash(im, w=HASH_W):
    """兼容旧接口：返回 16×16 的归一化灰度向量（不是位串，是 float 列表）"""
    return desc(im, w)


def desc(im, n=HASH_W, blur=1.4):
    """模糊 + 缩到 16×16 灰度 + 零均值单位方差 → 16 个 float。

    实测（两张真实截图，12+5 个单位）：
      同一单位平移 ±3px  → 余弦相似度 ≥ 0.9797
      同一单位 JPEG q60  → ≥ 0.9988
      不同单位之间       → ≤ 0.9020
    所以阈值 0.94 能干净分开。dHash 在 ±2px 就掉到汉明 30+，不可用。
    """
    from PIL import ImageFilter
    g = im.convert("L").resize((n, n), Image.LANCZOS)
    if blur:
        g = g.filter(ImageFilter.GaussianBlur(blur))
    a = np.asarray(g, dtype=np.float32).ravel()
    return ((a - a.mean()) / (a.std() + 1e-6)).tolist()


def sim(d1, d2):
    if not d1 or not d2 or len(d1) != len(d2):
        return 0.0
    return float(np.mean(np.asarray(d1, np.float32) * np.asarray(d2, np.float32)))


# ------------------------------------------------------------------ 缓存
class Cache:
    def __init__(self, path=CACHE_PATH):
        self.path = path
        self.items = []          # [{"h","star","name","hits","seen"}]
        self._dirty = False
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self.items = d.get("items", [])
        except Exception:
            self.items = []

    def save(self):
        if not self._dirty:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "hamming": HAMMING_MAX,
                       "items": self.items}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
        self._dirty = False

    def lookup(self, d, star):
        best, best_s = None, -1.0
        for it in self.items:
            if it.get("star") != star:
                continue
            s = sim(d, it.get("d"))
            if s > best_s:
                best, best_s = it, s
        if best is not None and best_s >= SIM_MIN:
            best["hits"] = best.get("hits", 0) + 1
            self._dirty = True
            if best.get("name"):
                return best["name"], round(best_s, 3)
            # 已知「认不出」：认过 3 次就不再浪费请求
            if best.get("tries", 1) >= 3:
                return "", None
        return None, None

    def mark_unknown(self, d, star):
        for it in self.items:
            if it.get("star") == star and sim(d, it.get("d")) >= 0.98:
                if not it.get("name"):
                    it["tries"] = it.get("tries", 1) + 1
                    it["seen"] = int(time.time())
                    self._dirty = True
                return
        self.items.append({"d": [round(x, 4) for x in d], "star": star,
                           "name": None, "tries": 1, "hits": 0,
                           "seen": int(time.time())})
        self._dirty = True

    def put(self, d, star, name):
        for it in self.items:
            if it.get("star") == star and sim(d, it.get("d")) >= 0.98:
                it["name"] = name
                it["hits"] = it.get("hits", 0) + 1
                it["seen"] = int(time.time())
                self._dirty = True
                return
        self.items.append({"d": [round(x, 4) for x in d], "star": star,
                           "name": name, "hits": 1, "seen": int(time.time())})
        self._dirty = True

    def __len__(self):
        return len(self.items)


# ------------------------------------------------------------------ 名字归一
def _hero_names():
    """从 s18db/heroes.json 取 65 个英雄名（用于把 VLM 输出对齐到标准名）

    VLM 经常答**称号**（如「翠神」是「艾翁」的称号），所以同时返回称号→本名映射。
    """
    p = os.path.join(DB, "s18db", "heroes.json")
    names, alias = [], {}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d = d.get("heroes") or d.get("data") or list(d.values())
        for h in d:
            if isinstance(h, dict):
                n = h.get("name") or h.get("title")
                t = h.get("title")
                if n:
                    names.append(str(n))
                    if t and t != n:
                        alias[str(t)] = str(n)
            elif isinstance(h, str):
                names.append(h)
    except Exception:
        pass
    return names, alias


def _match_name(raw, names, alias=None):
    """把 VLM 返回的名字对齐到标准名单；对不上返回 (None, 0)"""
    if not raw:
        return None, 0.0
    s = str(raw).strip().strip("「」\"'“”")
    if alias and s in alias:
        return alias[s], 0.95
    if s in names:
        return s, 1.0
    import difflib
    hit = difflib.get_close_matches(s, names, n=1, cutoff=0.6)
    if hit:
        r = difflib.SequenceMatcher(None, s, hit[0]).ratio()
        return hit[0], round(r, 2)
    return None, 0.0


# ------------------------------------------------------------------ 拼图 + VLM
def build_sheet(crops, tile=112, cols=4, label=True):
    """把若干裁剪拼成带编号的九宫格；编号画在左上角，便于模型按号回答"""
    n = len(crops)
    rows = (n + cols - 1) // cols
    pad = 6
    W = cols * (tile + pad) + pad
    H = rows * (tile + pad) + pad
    sheet = Image.new("RGB", (W, H), (12, 12, 16))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", max(14, tile // 6))
    except Exception:
        font = ImageFont.load_default()
    for i, c in enumerate(crops):
        cx = pad + (i % cols) * (tile + pad)
        cy = pad + (i // cols) * (tile + pad)
        im = c.copy()
        # 填满格子（thumbnail 只会缩小，不会放大，之前 105px 的原图就那样被塞进 224 的格子里了）
        k = min(tile / im.width, tile / im.height)
        im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))),
                       Image.LANCZOS)
        sheet.paste(im, (cx + (tile - im.width) // 2, cy + (tile - im.height) // 2))
        if label:
            tag = str(i + 1)
            tw = d.textlength(tag, font=font)
            d.rectangle([cx, cy, cx + tw + 8, cy + int(tile * 0.22)],
                        fill=(0, 0, 0))
            d.text((cx + 4, cy + 2), tag, font=font, fill=(255, 230, 60))
    return sheet


PROMPT = (
    "这是《金铲铲之战》S18 的对局截图拼图，每个格子是一个棋子的局部放大图，"
    "左上角有黄色编号 1~{n}。请识别每个编号对应的英雄名字。\n"
    "只输出 JSON，键是编号，值是英雄中文名，例如 {{\"1\":\"薇恩\",\"2\":\"盖伦\"}}。\n"
    "看不清的编号值写 null。不要输出任何解释。"
)


def vlm_names(crops, deadline=None, ask=None):
    """一次请求认完全部裁剪。返回 {下标: 名字} （下标从 0 开始）"""
    if not crops:
        return {}, 0.0
    if ask is None:
        from vlm_board_scan import ask as _ask, parse_json
        ask = _ask
    else:
        from vlm_board_scan import parse_json
    sheet = build_sheet(crops, tile=TILE)
    import base64
    import io
    buf = io.BytesIO()
    sheet.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    url = "data:image/png;base64," + b64
    t0 = time.perf_counter()
    _, dt, text = ask("names", url, PROMPT.format(n=len(crops)), 400,
                      deadline or (time.perf_counter() + 30))
    obj = parse_json(text)
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            try:
                i = int(str(k).strip()) - 1
            except Exception:
                continue
            if 0 <= i < len(crops) and v:
                out[i] = v
    return out, (time.perf_counter() - t0) if dt is None else dt


def name_units(img, units, cache=None, use_vlm=True, ask=None, deadline=None,
               save_sheet=None):
    """给 board_units.extract() 的结果补上 name。

    返回统计 {"hits","unique","vlm_calls","vlm_ms","cache_size"}；
    units 里每项新增 name / name_src / name_score。
    """
    cache = cache if cache is not None else Cache()
    names, alias = _hero_names()
    stats = {"hits": 0, "skipped": 0, "unique": 0, "vlm_calls": 0, "vlm_ms": 0,
             "cache_size": len(cache)}

    pending = []          # [(unit_index, crop, desc, star)]
    seen = []             # [(desc, star, name)]
    for idx, u in enumerate(units):
        u.setdefault("name", None)
        u.setdefault("name_src", None)
        crop = crop_unit(img, u)
        if crop is None:
            continue
        d = desc(crop)
        star = u.get("star")
        nm, sc = cache.lookup(d, star)
        if nm == "":
            stats["skipped"] += 1          # 已知认不出，不再请求
            continue
        if nm:
            u["name"], u["name_src"], u["name_score"] = nm, "cache", sc
            stats["hits"] += 1
            continue
        # 本轮内部去重：同一个棋子在一张图里出现多次（常见于 1★ 多张）
        dup = next((n for (d2, s2, n) in seen
                    if s2 == star and n and sim(d, d2) >= SIM_MIN), None)
        if dup:
            u["name"], u["name_src"] = dup, "vlm"
            continue
        pending.append((idx, crop, d, star))
        seen.append((d, star, None))

    # 二次去重：描述子相近但没超过阈值的，也合并成一张拼图
    uniq = []             # [(idx, crop, desc, star)]
    for idx, crop, d, star in pending:
        if not any(star == s2 and sim(d, d2) >= SIM_MIN for _, _, d2, s2 in uniq):
            uniq.append((idx, crop, d, star))
    stats["unique"] = len(uniq)

    if uniq and use_vlm:
        crops = [c for _, c, _, _ in uniq]
        if save_sheet:
            build_sheet(crops).save(save_sheet)
        got, dt = vlm_names(crops, deadline=deadline, ask=ask)
        stats["vlm_calls"] = 1
        stats["vlm_ms"] = round(dt * 1000)
        for j, raw in got.items():
            nm, score = _match_name(raw, names, alias) if names else (str(raw), 1.0)
            if not nm:
                continue
            _, _, d, star = uniq[j]
            cache.put(d, star, nm)
            # 回填所有同棋子（包括近似的）待定项
            for idx, crop2, d2, star2 in pending:
                if star2 == star and sim(d2, d) >= SIM_MIN:
                    units[idx]["name"] = nm
                    units[idx]["name_src"] = "vlm"
                    units[idx]["name_score"] = score
        # 没认出来的记一笔「未知」，避免每次重跑都再请求一遍
        for idx, crop2, d2, star2 in uniq:
            if not units[idx].get("name"):
                cache.mark_unknown(d2, star2)
    elif uniq:
        stats["vlm_calls"] = 0

    cache.save()
    stats["cache_size"] = len(cache)
    return stats


# ------------------------------------------------------------------ 自检
if __name__ == "__main__":
    import sys
    sys.path.insert(0, HERE)
    import board_units as B

    p = sys.argv[1] if len(sys.argv) > 1 else \
        r"D:\Download\00a5a489-ca7a-4216-bef0-81821a313981.png"
    im = Image.open(p).convert("RGB")
    us = B.extract(im)
    t0 = time.perf_counter()
    st = name_units(im, us, use_vlm=False)
    print("仅缓存模式 %.1fms" % ((time.perf_counter()-t0)*1000), st)
    for i, u in enumerate(us, 1):
        print("  #%d %s %d★ %s" % (i, u["area"], u["star"] or 0, u.get("name")))
