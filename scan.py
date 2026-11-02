# -*- coding: utf-8 -*-
"""
统一入口：金铲铲 / 云顶之弈 截图信息提取
===========================================
三种后端，一套输出：

  --backend ocr     只用本地 OCR，不联网。最快（~0.4s），但对坐标精度极敏感
  --backend vlm     只用云端 qwen3-vl-plus。最稳，~1.8s
  --backend hybrid  默认。先用 OCR 读纯文本，校验不过的字段再回落 VLM；
                    棋盘（3D 棋子）OCR 读不了，始终走 VLM

用法:
    python scan.py 截图.png
    python scan.py 图1.png 图2.png --json out.json
    python scan.py 图1.png --backend vlm --budget 3
    python scan.py 图1.png --backend ocr
    python scan.py 图1.png --save-crops        # 存裁剪块，便于校准坐标

输出字段: 阶段 / 等级 / 经验 / 金币 / 商店[5] / 棋子{数量}
          _来源（每个字段由谁产出）/ _耗时 / _告警
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "core"))
from vlm_board_scan import REGIONS, make_crop, ask, parse_json   # 单一坐标来源
import player_hp                                               # 右侧玩家列表
import board_units                                             # 血条→星级/位置/装备
import traits as traits_mod                                    # 左侧羁绊面板
import item_bench                                              # 最左侧装备栏
import augments as aug_mod                                    # 强化符文图标

# ------------------------------------------------------------------ 校验规则
def v_stage(x):
    return isinstance(x, str) and bool(re.fullmatch(r"\d+-\d+", x))


def v_level(x):
    return isinstance(x, int) and 1 <= x <= 11


def v_exp(x):
    return isinstance(x, str) and bool(re.fullmatch(r"\d+/\d+", x))


def v_gold(x):
    return isinstance(x, int) and 0 <= x <= 999


def v_shop(x):
    return isinstance(x, list) and len(x) == 5 and sum(1 for i in x if i) >= 3


VALIDATORS = {"阶段": v_stage, "等级": v_level, "经验": v_exp,
              "金币": v_gold, "商店": v_shop}


def load_roster():
    """65 个英雄名，用于给商店结果做交叉核对"""
    p = os.path.join(HERE, "data", "HeroData.json")
    try:
        with open(p, encoding="utf-8-sig") as f:
            return {h["HeroName"] for h in json.load(f)}
    except Exception:
        return set()


ROSTER = load_roster()


# ------------------------------------------------------------------ OCR 后端
def ocr_text_fields(img):
    try:
        from ocr_extract import extract_fields, get_ocr
    except ImportError as e:
        return None, 0, "OCR 不可用: %s（pip install -i https://mirrors.aliyun.com/pypi/simple/ rapidocr-onnxruntime）" % e
    get_ocr()
    try:
        vals, ms = extract_fields(img)
        return vals, ms, None
    except Exception as e:
        return None, 0, "OCR 失败: %s" % e


# ------------------------------------------------------------------ VLM 后端
FIELD_TO_REGION = {"阶段": "stage", "等级": "level_exp", "经验": "level_exp",
                   "金币": "gold", "商店": "shop", "棋子": "board"}


def vlm_fields(img, fields, deadline):
    """并行调 VLM，返回 ({region: 原始文本}, 耗时秒)"""
    regions = sorted({FIELD_TO_REGION[f] for f in fields})
    t0 = time.perf_counter()
    texts = {}
    with ThreadPoolExecutor(max_workers=max(1, len(regions))) as ex:
        jobs = {}
        for rg in regions:
            spec = REGIONS[rg]
            url, _, _ = make_crop(img, spec)
            jobs[rg] = ex.submit(ask, rg, url, spec["prompt"], spec["tokens"], deadline)
        for rg, f in jobs.items():
            texts[rg] = (f.result()[2] or "")
    return texts, time.perf_counter() - t0


def parse_vlm(raw):
    """把 VLM 原始文本解析成字段"""
    out = {}
    s = (raw.get("stage") or "").strip().strip("。")
    out["阶段"] = s or None

    le = parse_json(raw.get("level_exp")) or {}
    out["等级"] = le.get("level") if isinstance(le.get("level"), int) else None
    out["经验"] = le.get("exp")

    g = (raw.get("gold") or "").strip()
    digits = "".join(ch for ch in g if ch.isdigit())
    out["金币"] = int(digits) if digits else None

    shop = parse_json(raw.get("shop"))
    out["商店"] = (shop + [None]*5)[:5] if isinstance(shop, list) else None

    bd = parse_json(raw.get("board")) or {}
    n = bd.get("own") if isinstance(bd, dict) else None
    out["棋子"] = {"数量": int(n) if isinstance(n, int) else None}

    return out


# ------------------------------------------------------------------ 主流程
def scan(path, backend="hybrid", budget=3.0, save_crops=False, with_players=True,
         with_units=True, with_traits=True, with_items=True, with_augments=True,
         with_names=False, with_labels=False):
    t_start = time.perf_counter()
    deadline = t_start + budget
    img = Image.open(path).convert("RGB")
    tag = os.path.splitext(os.path.basename(path))[0]

    if save_crops:
        cdir = os.path.join(HERE, "output", "crops_sample")
        os.makedirs(cdir, exist_ok=True)
        for rg in ["stage", "level_exp", "gold", "shop", "board"]:
            _, crop_img, _ = make_crop(img, REGIONS[rg])
            crop_img.save(os.path.join(cdir, "crop_%s_%s.png" % (tag, rg)))

    result, src, warn = {}, {}, []
    t_ocr = t_vlm = 0.0
    fell_back = []

    # ---- 0) 棋盘单位：有 CV 版本就不问 VLM（更快更准） ----
    pool = ThreadPoolExecutor(max_workers=6)
    board_fut = None
    if backend in ("vlm", "hybrid") and not with_units:
        spec = REGIONS["board"]
        url, _, _ = make_crop(img, spec)
        board_fut = pool.submit(ask, "board", url, spec["prompt"], spec["tokens"], deadline)
    elif backend == "ocr":
        spec = REGIONS["board"]
        make_crop(img, spec)     # 只为 --save-crops 时能落盘

    # ---- 0.5) 玩家列表（右侧）：OCR 慢且吃 CPU，放到最后串行跑，避免和文本 OCR 抢核 ----
    player_fut = None

    # ---- 1) OCR 阶段 ----
    if backend in ("ocr", "hybrid"):
        vals, t_ocr, err = ocr_text_fields(img)
        if err:
            warn.append(err)
            if backend == "ocr":
                vals = None
        if vals:
            for k, v in vals.items():
                ok = VALIDATORS[k](v)
                result[k] = v
                src[k] = "ocr" if ok else "ocr(未通过校验)"
                if not ok:
                    fell_back.append(k)

    # ---- 2) 决定哪些「文本字段」要回落 VLM ----
    need = []
    if backend == "vlm":
        need = [k for k in FIELD_TO_REGION if k != "棋子"]
    elif backend == "hybrid":
        for k in ["阶段", "等级", "经验", "金币", "商店"]:
            if k not in result or not VALIDATORS[k](result[k]):
                need.append(k)

    # ---- 3) VLM 回落（只针对失败的文本字段）----
    if need:
        try:
            tv = time.perf_counter()
            raw = {}
            futs = {}
            for k in need:
                rg = FIELD_TO_REGION[k]
                if rg in futs:
                    continue
                spec = REGIONS[rg]
                url, _, _ = make_crop(img, spec)
                futs[rg] = pool.submit(ask, rg, url, spec["prompt"], spec["tokens"], deadline)
            for rg, f in futs.items():
                raw[rg] = f.result()[2] or ""
            t_vlm = time.perf_counter() - tv
            parsed = parse_vlm(raw)
            for k in need:
                if k in ("等级", "经验") and "level_exp" not in raw:
                    continue
                v = parsed.get(k)
                ok = VALIDATORS[k](v)
                if ok:
                    result[k] = v
                    src[k] = "vlm"
                elif k not in result:
                    result[k] = v
                    src[k] = "vlm(未通过校验)"
                    warn.append("%s 回落后仍不合法: %r" % (k, v))
        except Exception as e:
            warn.append("VLM 回落失败: %s" % e)

    # ---- 4) 收棋盘结果 ----
    if board_fut is not None:
        try:
            dt, txt = board_fut.result()[1], board_fut.result()[2]
            bd = parse_json(txt) or {}
            n = bd.get("own") if isinstance(bd, dict) else None
            result["棋子"] = {"数量": int(n) if isinstance(n, int) else None}
            src["棋子"] = "vlm"
            t_vlm = max(t_vlm, dt or 0)
        except Exception as e:
            result["棋子"] = {"数量": None}
            src["棋子"] = "vlm(失败)"
            warn.append("棋盘 VLM 失败: %s" % e)
    else:
        result["棋子"] = {"数量": None, "说明": "OCR 读不了 3D 棋子，请用 --backend vlm/hybrid"}
        src["棋子"] = "-"

    pool.shutdown(wait=False)

    # ---- 4.5) 收玩家列表结果 ----
    player_data = None
    if with_players:
        try:
            t_pl = time.perf_counter()
            player_data = player_hp.extract(img)
            t_pl = time.perf_counter() - t_pl
            src["玩家排名"] = "ocr"
        except Exception as e:
            t_pl = 0
            warn.append("玩家列表识别失败: %s" % e)
    else:
        t_pl = 0

    # ---- 4.6) 棋盘单位（星级/位置/装备）+ 羁绊面板 ----
    units_data = traits_data = None
    t_units = t_traits = 0.0
    if with_units:
        try:
            t0u = time.perf_counter()
            units_data = board_units.extract(img)
            t_units = time.perf_counter() - t0u
            src["单位"] = "cv"
        except Exception as e:
            warn.append("单位识别失败: %s" % e)
    if with_traits:
        try:
            t0t = time.perf_counter()
            traits_data = traits_mod.extract(img)
            t_traits = time.perf_counter() - t0t
            src["羁绊"] = "ocr"
            if len(traits_data) < 3:
                warn.append("羁绊只读出 %d 条，可能面板布局变了" % len(traits_data))
        except Exception as e:
            warn.append("羁绊识别失败: %s" % e)

    # ---- 4.7) 最左侧装备栏（散件/道具） ----
    bench_items = []
    t_bench = 0.0
    if with_items:
        try:
            t0i = time.perf_counter()
            bench_items = item_bench.extract(img)
            t_bench = time.perf_counter() - t0i
            src["装备栏"] = "cv"
        except Exception as e:
            warn.append("装备栏识别失败: %s" % e)

    # ---- 4.75) 强化符文图标 ----
    aug_list = []
    t_aug = 0.0
    if with_augments:
        try:
            t0a = time.perf_counter()
            aug_list = aug_mod.find_icons(img)
            t_aug = time.perf_counter() - t0a
            src["强化符文"] = "cv"
        except Exception as e:
            warn.append("符文识别失败: %s" % e)

    # ---- 4.9) 英雄名称 ----
    name_stats = None
    t_names = 0.0
    if with_labels and units_data:
        try:
            import hero_match as hm_mod
            t0n = time.perf_counter()
            name_stats = hm_mod.name_units(img, units_data)
            t_names = time.perf_counter() - t0n
            src["英雄名称"] = "label"
            if name_stats["miss"]:
                warn.append("英雄匹配：%d 个棋子没有超过阈值，留空（不硬猜）"
                            % name_stats["miss"])
        except Exception as e:
            warn.append("英雄匹配失败: %s" % e)
    elif with_names and units_data:
        try:
            import hero_names as hn_mod
            t0n = time.perf_counter()
            name_stats = hn_mod.name_units(img, units_data)
            t_names = time.perf_counter() - t0n
            src["英雄名称"] = "vlm" if name_stats["vlm_calls"] else "cache"
            if name_stats["vlm_calls"] and not any(u.get("name") for u in units_data):
                warn.append("英雄名称：VLM 未返回可用结果")
        except Exception as e:
            warn.append("英雄名称识别失败: %s" % e)

    # ---- 4.8) 棋子数量：优先用 CV 结果（比 VLM 数得准，且只算棋盘上的） ----
    if units_data:
        nb = sum(1 for u in units_data if u["area"] == "board")
        nbench = sum(1 for u in units_data if u["area"] == "bench")
        result["棋子"] = {"数量": nb, "备战席": nbench}
        src["棋子"] = "cv"

    for k in ["阶段", "等级", "经验", "金币", "商店", "棋子"]:
        result.setdefault(k, None)
        src.setdefault(k, "-")

    # ---- 5) 商店名单交叉核对 ----
    if isinstance(result.get("商店"), list) and ROSTER:
        bad = [x for x in result["商店"] if x and x not in ROSTER]
        if bad:
            warn.append("商店中不在 S18 名单里的项（可能是事件卡或误读）: %s" % bad)

    total = time.perf_counter() - t_start
    out = {"file": os.path.basename(path)}
    out.update({k: result[k] for k in ["阶段", "等级", "经验", "金币", "商店", "棋子"]})

    # ---- 玩家排名 / 我的血量 ----
    if player_data:
        out["玩家排名"] = player_data["players"]
        out["我的血量"] = (player_data.get("self") or {}).get("hp")
        src["我的血量"] = "ocr"
        if len(player_data["players"]) < 2:
            warn.append("玩家列表只识别到 %d 行，可能漏读" % len(player_data["players"]))
    else:
        out["玩家排名"] = None
        out["我的血量"] = None
        src["我的血量"] = "-"

    # ---- 单位 / 羁绊 / 装备栏 ----
    out["单位"] = units_data
    out["羁绊"] = traits_data
    out["装备栏"] = bench_items
    out["强化符文"] = aug_list

    out["_来源"] = src
    out["_耗时"] = {"ocr_ms": int(t_ocr), "vlm_ms": round(t_vlm*1000),
                    "players_ms": round(t_pl*1000),
                    "units_ms": round(t_units*1000),
                    "traits_ms": round(t_traits*1000),
                    "items_ms": round(t_bench*1000),
                    "augments_ms": round(t_aug*1000),
                    "names_ms": round(t_names*1000),
                    "total_ms": round(total*1000), "预算s": budget,
                    "触发回落": fell_back}
    if name_stats is not None:
        out["_名字统计"] = name_stats
    out["_告警"] = warn
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="截图信息提取（统一入口）")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--backend", choices=["ocr", "vlm", "hybrid"], default="hybrid")
    ap.add_argument("--budget", type=float, default=3.0)
    ap.add_argument("--json")
    ap.add_argument("--save-crops", action="store_true")
    ap.add_argument("--no-players", action="store_true",
                    help="跳过右侧玩家列表识别（可省 ~2s）")
    ap.add_argument("--no-units", action="store_true",
                    help="跳过棋盘单位（星级/位置/装备）识别")
    ap.add_argument("--no-traits", action="store_true",
                    help="跳过左侧羁绊面板识别")
    ap.add_argument("--no-items", action="store_true",
                    help="跳过最左侧装备栏识别")
    ap.add_argument("--no-augments", action="store_true",
                    help="跳过强化符文识别")
    ap.add_argument("--names", action="store_true",
                    help="用 VLM 认棋子名字（一次请求 + 本地缓存；默认关闭）")
    ap.add_argument("--labels", action="store_true",
                    help="用 data/hero_labels 的人工标注做本地匹配（离线，约 10ms）")
    a = ap.parse_args()

    out = []
    for p in a.images:
        if not os.path.exists(p):
            print("[跳过] 不存在:", p, file=sys.stderr)
            continue
        r = scan(p, backend=a.backend, budget=a.budget, save_crops=a.save_crops,
                 with_players=not a.no_players,
                 with_units=not a.no_units,
                 with_traits=not a.no_traits,
                 with_items=not a.no_items,
                 with_augments=not a.no_augments,
                 with_names=a.names, with_labels=a.labels)
        out.append(r)
        print("\n=== %s  [%s] ===" % (r["file"], a.backend))
        print("  阶段 %-5s  等级 %-3s  经验 %-6s  金币 %-4s  棋子 %s" % (
            r["阶段"], r["等级"], r["经验"], r["金币"], r["棋子"]["数量"]))
        print("  商店 %s" % r["商店"])
        if r.get("玩家排名"):
            print("  玩家排名（血量降序）：")
            for p in r["玩家排名"]:
                mark = "  ←我" if p["is_self"] else ""
                print("     #%d  %-14s %3d%s" % (p["rank"], p["name"] or "?", p["hp"], mark))
            print("  我的血量 %s" % r.get("我的血量"))
        if r.get("单位"):
            print("  棋盘单位 %d 个：" % len(r["单位"]))
            for i, u in enumerate(r["单位"], 1):
                it = "、".join(x["name"] for x in u["items"]) or "无装备"
                nm = u.get("name")
                sc = u.get("name_score")
                head = ("%s%s " % (nm, ("(%.2f)" % sc) if sc else "")) if nm else ""
                print("     #%d  %s%d★  %s%s" % (i, head, u["star"] or 0,
                                                "棋盘" if u["area"] == "board" else "备战席", it))
        if r.get("羁绊"):
            print("  羁绊：" + "  ".join(
                "%s%d(%s)" % (t["name"], t["count"], t["tiers"]) for t in r["羁绊"]))
        if r.get("装备栏"):
            print("  最左侧装备栏：" + "  ".join(
                "%s(%.2f)" % (x["name"], x["score"]) for x in r["装备栏"]))
        if r.get("强化符文"):
            for i, aug in enumerate(r["强化符文"], 1):
                if aug.get("reliable") and aug.get("name"):
                    print("  强化符文#%d：%s（%.3f）" % (i, aug["name"], aug["score"]))
                else:
                    cand = " / ".join("%s %.2f" % (t["name"], t["score"])
                                      for t in (aug.get("top") or [])[:3])
                    print("  强化符文#%d：未知（候选 %s）" % (i, cand))
        print("  来源 %s" % r["_来源"])
        t = r["_耗时"]
        print("  耗时 ocr=%dms vlm=%dms total=%dms" % (
            t["ocr_ms"], t["vlm_ms"], t["total_ms"]))
        for w in r["_告警"]:
            print("  [!] " + w)

    payload = out[0] if len(out) == 1 else out
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("\n[已写入]", a.json)
    else:
        print("\n" + json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
