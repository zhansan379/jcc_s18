# -*- coding: utf-8 -*-
"""
固定工作流编排：截图 → 识别 → 规则推荐 → 数据补充 → LLM 教练
==============================================================
一次 analyze() 把两个标签页要的东西全算完（同一份局面，不重复识别）。

耗时预算（1919×1097 截图，本机实测）：
    识别 scan(...labels)   ~4.0s（冷启动；OCR/模板预热后 ~2.5s）
    规则推荐 comp_match    ~0.05s
    s18db 补充             ~0.1s
    LLM 建议 qwen-flash    ~0.7~2.0s（硬超时 5s，失败回落规则文案）
    ---- 合计 ~5s，缓存命中 0.05s

对外：
    warm()                          预热模型与静态数据
    analyze(path, ...)              -> dict（见文件末 build_* 的字段）
"""
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, ROOT)                                  # scan.py 在仓库根

from PIL import Image                                     # noqa: E402

import databook                                           # noqa: E402
import llm as llm_mod                                     # noqa: E402

# 规则链路（和 recommend.py 用的是同一套）
from comp_index import load_index                         # noqa: E402
import comp_match                                         # noqa: E402
import economy                                            # noqa: E402

TIER_W = {"S": 1.0, "A": 0.8, "B": 0.6, "C": 0.4, "D": 0.2}
AUG_ROUNDS = ["2-1", "3-2", "4-2"]


# ------------------------------------------------------------------ 预热
def warm(verbose=False):
    """把首次调用的固定开销提前付掉（OCR 模型、图标库、静态 JSON）"""
    t0 = time.perf_counter()
    steps = []

    def step(name, fn):
        t = time.perf_counter()
        try:
            fn()
        except BaseException as e:              # 预热失败不该拦住主流程（含 SystemExit）
            steps.append((name, round((time.perf_counter() - t) * 1000), "ERR %s" % e))
            return
        steps.append((name, round((time.perf_counter() - t) * 1000), "ok"))

    step("静态数据", databook.warm)
    step("阵容索引", load_index)
    step("OCR 模型", _warm_ocr)
    step("棋子/装备模板", _warm_units)
    step("英雄标注库", _warm_labels)
    step("符文模板", _warm_augments)
    if verbose:
        for n, ms, st in steps:
            print("  %-12s %5dms  %s" % (n, ms, st))
    return {"total_ms": round((time.perf_counter() - t0) * 1000), "steps": steps}


def _warm_ocr():
    from ocr_extract import get_ocr
    get_ocr()


def _warm_units():
    import board_units
    board_units._load_refs()


def _warm_labels():
    import hero_match
    hero_match.load_index()


def _warm_augments():
    import augments
    augments._load_refs()
    augments._shape_refs()


# ------------------------------------------------------------------ 工具
def _stage_key(stage):
    try:
        a, b = str(stage or "").replace(" ", "").split("-")
        return int(a), int(b)
    except Exception:
        return None


def next_augment_round(stage):
    key = _stage_key(stage)
    if not key:
        return None
    for r in AUG_ROUNDS:
        rk = _stage_key(r)
        if rk and rk > key:
            return r
    return None


def _fmt_s(sec):
    return "%.1fs" % sec if sec >= 0.1 else "%.0fms" % (sec * 1000)


# ------------------------------------------------------------------ 符文候选
def augment_pool(state, top, limit=8):
    """规则初筛：回合 + 评级 + 阵容契合，交给 LLM 复排"""
    tiers = databook.augment_tiers()
    owned = {(a.get("name") if isinstance(a, dict) else a)
             for a in (state.get("强化符文") or [])}
    owned = {n for n in owned if n}
    nxt = next_augment_round(state.get("阶段"))
    units = set((top or {}).get("missing_units") or []) | set((top or {}).get("matched_units") or [])
    traits = {g["name"] for g in (top or {}).get("trait_gaps") or []}
    style = (top or {}).get("style")

    rows = []
    for name, a in tiers.items():
        if name in owned:
            continue
        rounds = a.get("rounds") or []
        if nxt and rounds and nxt not in rounds:
            continue
        desc = a.get("desc") or ""
        typed = a.get("typeZh") or []
        tw = TIER_W.get(str(a.get("tier") or "").upper(), 0.45)
        hit_units = [u for u in units if u and u in desc]
        hit_traits = [t for t in traits if t and t in desc]
        score = 1.6 * tw
        if nxt and nxt in rounds:
            score += 0.35
        score += 0.35 * min(2, len(hit_units)) + 0.25 * min(2, len(hit_traits))
        if style == "reroll" and ("经济" in typed or "商店" in desc or "刷新" in desc):
            score += 0.3
        if style == "level" and ("经验" in desc or "人口" in desc):
            score += 0.25
        score += 0.1 * min(2, len(typed))
        rows.append({"name": name, "tier": a.get("tier"), "rarityZh": a.get("rarityZh"),
                     "typeZh": typed, "rounds": rounds,
                     "desc": desc[:110], "score": round(score, 3),
                     "hit": hit_units + hit_traits})

    rows.sort(key=lambda d: (-d["score"], d["name"]))
    out = rows[:limit]
    for r in out:
        r.pop("score", None)
    return out


# ------------------------------------------------------------------ 单阵容补充
def enrich_candidate(c, state):
    """把 comp_match 的候选补成 UI 能直接渲染的结构"""
    cid = c.get("id")
    comp = databook.comp_full(cid)
    st = state.get("state") or {}
    owned = set((st.get("owned_counts") or {}).keys()) or set(c.get("matched_units") or [])
    board = databook.comp_board(cid)
    for u in board:
        u["owned"] = u["name"] in owned
        u["cost"] = databook.hero_cost(u["name"])
        u["traits"] = [t.get("name") for t in (databook.hero(u["name"]).get("traits") or [])]
    early = databook.comp_early_board(cid)
    for u in early:
        u["owned"] = u["name"] in owned
        u["cost"] = databook.hero_cost(u["name"])

    core = c.get("core_units") or []
    missing = sorted([u for u in (c.get("missing_units") or [])],
                     key=lambda n: (databook.hero_cost(n), n))
    shop = [x for x in (state.get("商店") or []) if x]
    board_names = [u["name"] for u in board]
    shop_rows = []
    for name in shop:
        shop_rows.append({
            "name": name, "cost": databook.hero_cost(name),
            "buy": name in board_names, "core": name in core,
            "traits": [t.get("name") for t in (databook.hero(name).get("traits") or [])],
        })

    c2 = dict(c)
    # 装备：手上散件能立刻合成的 2 件成装 + 阵容指定装
    comps_owned = [x.get("name") for x in (state.get("装备栏") or []) if x.get("name")]
    components = [n for n in comps_owned if databook.is_component(n)]
    plans = databook.comp_equip_plans(cid)
    c2["detail"] = {
        "tier": c.get("tier"),
        "avgPlace": (c.get("stats") or {}).get("avgPlace"),
        "top4Rate": (c.get("stats") or {}).get("top4Rate"),
        "winRate": (c.get("stats") or {}).get("winRate"),
        "playRate": (c.get("stats") or {}).get("playRate"),
        "difficulty": c.get("difficulty"),
        "tags": c.get("tags") or [],
        "core_text": comp.get("core") or "",
        "open_text": comp.get("open") or "",
        "early": c.get("early") or "",
        "mid": c.get("mid") or "",
        "final": c.get("final") or "",
        "early_board": early,
        "board": board,
        "equip_plans": plans,
        "components": components,
        "bench_items": comps_owned,
        "item_plan": databook.plan_items(components, plans),
        "conditions": databook.comp_conditions(cid),
        "code": databook.comp_code(cid),
        "main": comp.get("mainHeroName") or c.get("main"),
        "shop_rows": shop_rows,
        "missing_sorted": missing,
    }
    c2["missing_sorted"] = missing
    c2["shop_rows"] = shop_rows
    return c2


# ------------------------------------------------------------------ 标注重建
def _abs_box(W, H, box):
    return [int(round(box[0])), int(round(box[1])), int(round(box[2])), int(round(box[3]))]


def _tight_box(W, H, region, tb):
    """REGIONS 分区 + 分区内部比例框 → 整图绝对像素框"""
    l, t, r, b = region
    x0 = (l + tb[0] * (r - l)) * W
    y0 = (t + tb[1] * (b - t)) * H
    x1 = (l + tb[2] * (r - l)) * W
    y1 = (t + tb[3] * (b - t)) * H
    return [int(x0), int(y0), int(x1), int(y1)]


def build_annotations(img, state):
    """把每个识别结果变成 {box, 标签, 来源}，供 Tab2 在图上画"""
    import importlib
    vbs = importlib.import_module("vlm_board_scan")
    traits_mod = importlib.import_module("traits")
    player_mod = importlib.import_module("player_hp")
    try:                                        # OCR 没装时 ocr_extract 会 SystemExit
        ocr_mod = importlib.import_module("ocr_extract")
        tg = ocr_mod.TIGHT
    except BaseException:
        ocr_mod, tg = None, None

    W, H = img.size
    src = state.get("_来源") or {}
    out = []

    def add(gid, group, label, value, box, source, conf=None):
        box = [max(0, min(W - 1, box[0])), max(0, min(H - 1, box[1])),
               max(0, min(W, box[2])), max(0, min(H, box[3]))]
        out.append({"id": gid, "group": group, "label": label, "value": value,
                    "box": box, "source": source, "conf": conf})

    # ---- 文本字段（REGIONS + TIGHT）
    reg = vbs.REGIONS
    l, t, r, b = reg["stage"]["box"]
    add("txt:stage", "文本", "阶段", str(state.get("阶段") or "未识别"),
        _tight_box(W, H, reg["stage"]["box"], tg["stage"][0]) if tg
        else [int((l + 0.6 * (r - l)) * W), int((t + 0.1 * (b - t)) * H),
              int((l + 0.99 * (r - l)) * W), int((t + 0.7 * (b - t)) * H)],
        src.get("阶段", "-"))

    l, t, r, b = reg["level_exp"]["box"]
    box_lv = (_tight_box(W, H, reg["level_exp"]["box"], tg["level_exp"][0]) if tg
              else [int((l + 0.1 * (r - l)) * W), int((t + 0.45 * (b - t)) * H),
                    int((l + 0.30 * (r - l)) * W), int((t + 0.83 * (b - t)) * H)])
    box_ex = (_tight_box(W, H, reg["level_exp"]["box"], tg["level_exp"][1]) if tg
              else [int((l + 0.59 * (r - l)) * W), int((t + 0.58 * (b - t)) * H),
                    int((l + 0.80 * (r - l)) * W), int((t + 0.80 * (b - t)) * H)])
    add("txt:level", "文本", "等级", "%s 级" % (state.get("等级") if state.get("等级") is not None else "?"),
        box_lv, src.get("等级", "-"))
    add("txt:exp", "文本", "经验", str(state.get("经验") or "?"),
        box_ex, src.get("经验", "-"))

    l, t, r, b = reg["gold"]["box"]
    add("txt:gold", "文本", "金币", str(state.get("金币") if state.get("金币") is not None else "?"),
        _tight_box(W, H, reg["gold"]["box"], tg["gold"][0]) if tg
        else [int((l + 0.42 * (r - l)) * W), int((t + 0.50 * (b - t)) * H),
              int((l + 0.64 * (r - l)) * W), int((t + 0.78 * (b - t)) * H)],
        src.get("金币", "-"))

    shop = state.get("商店") or []
    sl, st_, sr, sb = reg["shop"]["box"]
    for i in range(5):
        name = shop[i] if i < len(shop) else None
        if tg:
            box = _tight_box(W, H, reg["shop"]["box"], tg["shop"][i])
        else:
            f0, f1 = [(0.0, 0.185), (0.185, 0.375), (0.375, 0.565),
                      (0.565, 0.750), (0.750, 0.90)][i]
            box = [int((sl + f0 * (sr - sl)) * W), int((st_ + 0.735 * (sb - st_)) * H),
                   int((sl + f1 * (sr - sl)) * W), int((st_ + 0.88 * (sb - st_)) * H)]
        add("shop:%d" % i, "商店", "%d·%s" % (i + 1, name or "空"), name or "空",
            box, src.get("商店", "-"))

    # ---- 单位
    for i, u in enumerate(state.get("单位") or [], 1):
        name = u.get("name") or "未命名"
        area = "棋盘" if u.get("area") == "board" else "备战席"
        items = "、".join(x.get("name") for x in (u.get("items") or []) if x.get("name"))
        add("unit:%d" % i, "单位", "#%d %s %d★" % (i, name, u.get("star") or 0),
            "%s · %s%s" % (area, name, (" · " + items) if items else ""),
            _abs_box(W, H, u["box"]), src.get("单位", "-"), u.get("name_score"))
        for k, it in enumerate(u.get("items") or [], 1):
            b = it.get("box") or []
            if len(b) == 4:
                add("unit:%d:item:%d" % (i, k), "单位", "%s 装备 %d" % (name, k),
                    it.get("name"), [b[0] * W, b[1] * H, b[2] * W, b[3] * H],
                    "cv", it.get("score"))

    # ---- 羁绊（面板是固定栅格，按 traits.py 的常量反推）
    tr = state.get("羁绊") or []
    if tr:
        cfg = traits_mod.LAYOUTS[traits_mod.pick_layout(img.size)]
        pl, pt = int(cfg["box"][0] * W), int(cfg["box"][1] * H)
        nx0, nx1, ny0, _ = cfg["name"]
        for k, t in enumerate(tr):
            y = cfg["y0"] + k * cfg["pitch"]
            box = [pl + nx0, pt + y + ny0, pl + nx1, pt + y + ny0 + 26]
            add("trait:%d" % k, "羁绊", t.get("name"),
                "%s%s" % (t.get("count"), ("/" + str(t.get("tiers"))) if t.get("tiers") else ""),
                box, src.get("羁绊", "-"))

    # ---- 装备栏
    for i, it in enumerate(state.get("装备栏") or [], 1):
        add("bench:%d" % i, "装备栏", it.get("name") or ("装备栏 %d" % i),
            "%s（匹配度 %.2f）" % (it.get("name"), it.get("score") or 0),
            _abs_box(W, H, it["box"]), src.get("装备栏", "-"), it.get("score"))

    # ---- 强化符文
    for i, a in enumerate(state.get("强化符文") or [], 1):
        name = a.get("name") or "未识别"
        add("aug:%d" % i, "强化符文", "符文 %d" % i,
            "%s（%.2f%s）" % (name, a.get("score") or 0,
                              "" if a.get("reliable", True) else " 不可信"),
            _abs_box(W, H, a["box"]), src.get("强化符文", "-"), a.get("score"))

    # ---- 玩家列表（行带按 player_hp 自己的规则重算，数量对得上才画）
    players = state.get("玩家排名") or []
    if players:
        try:
            cfg = player_mod.LAYOUTS[player_mod.pick_layout(img.size)]
            l, t, r, b = cfg["box"]
            strip = img.crop((int(l * W), int(t * H), int(r * W), int(b * H)))
            bands = player_mod._row_bands(strip, cfg)
            if len(bands) == len(players):
                for p, (y0, y1) in zip(players, bands):
                    add("player:%d" % p["rank"], "玩家", "#%d %s" % (p["rank"], p["name"]),
                        "血量 %s%s" % (p["hp"], " ← 我" if p.get("is_self") else ""),
                        [int(l * W), int(t * H) + y0, int(r * W), int(t * H) + y1],
                        src.get("玩家排名", "-"))
        except Exception:
            pass

    return out


# ------------------------------------------------------------------ 主入口
def analyze(path, backend="ocr", use_llm=True, top=3, budget=3.0, progress=None):
    """一次完整分析。progress(msg) 用来回传进度，可传 None。"""
    def say(msg):
        if progress:
            progress(msg)

    t_all = time.perf_counter()
    tm = {}

    say("读取截图…")
    img = Image.open(path).convert("RGB")

    # ---- 1) 识别
    say("识别中（OCR / CV，约 2~4s）…")
    t0 = time.perf_counter()
    import scan as scan_mod
    state = scan_mod.scan(path, backend=backend, budget=budget,
                          with_labels=True, with_units=True, with_traits=True,
                          with_items=True, with_augments=True, with_players=True)
    tm["scan"] = time.perf_counter() - t0

    # ---- 2) 规则推荐
    say("匹配阵容…")
    t0 = time.perf_counter()
    idx = load_index()
    rules = economy.load_rules()
    match = comp_match.recommend(state, idx, rules=rules, top=top)
    actions = economy.make_actions(state, match, rules)
    tm["match"] = time.perf_counter() - t0

    # ---- 3) 数据补充
    say("整理变阵 / 装备 / 符文…")
    t0 = time.perf_counter()
    candidates = [enrich_candidate(c, state) for c in (match.get("candidates") or [])]
    top_c = candidates[0] if candidates else None
    pool = augment_pool(state, top_c, limit=8) if top_c else []
    tm["enrich"] = time.perf_counter() - t0

    # ---- 4) LLM
    coach = None
    if use_llm and top_c:
        say("LLM 教练生成建议…")
        t0 = time.perf_counter()
        coach = llm_mod.narrate(match, top_c, actions, pool)
        tm["llm"] = time.perf_counter() - t0
        if not coach.get("data"):
            coach["data"] = llm_mod.rule_fallback(match, top_c, actions, pool)
            coach["fallback"] = True
    elif top_c:
        coach = {"data": llm_mod.rule_fallback(match, top_c, actions, pool),
                 "fallback": True, "error": "disabled", "elapsed": 0}
        tm["llm"] = 0.0

    # ---- 5) 标注
    say("生成标注…")
    t0 = time.perf_counter()
    try:
        annotations = build_annotations(img, state)
    except Exception as e:
        annotations = []
        state.setdefault("_告警", []).append("标注生成失败: %s" % e)
    tm["annotate"] = time.perf_counter() - t0

    tm["total"] = time.perf_counter() - t_all
    return {
        "ok": True,
        "image": path,
        "image_size": list(img.size),
        "state": state,
        "match": {k: v for k, v in match.items() if k != "candidates"},
        "candidates": candidates,
        "top": top_c,
        "actions": actions,
        "augment_pool": pool,
        "next_augment_round": next_augment_round(state.get("阶段")),
        "coach": coach,
        "annotations": annotations,
        "timings": {k: round(v, 3) for k, v in tm.items()},
        "timings_text": " · ".join(
            "%s %s" % (name, _fmt_s(tm[k])) for k, name in
            (("scan", "识别"), ("match", "推荐"), ("enrich", "整理"),
             ("llm", "LLM"), ("total", "合计")) if k in tm),
    }


def safe_analyze(path, **kw):
    try:
        return analyze(path, **kw)
    except Exception as e:
        return {"ok": False, "image": path,
                "error": "%s: %s" % (type(e).__name__, e),
                "trace": traceback.format_exc()[-2000:]}


if __name__ == "__main__":
    # 命令行自检：python advisor/pipeline.py 图.png
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    import json
    args = [a for a in sys.argv[1:]]
    path = args[0] if args else r"D:\Download\00a5a489-ca7a-4216-bef0-81821a313981.png"
    print("[warm]", warm(verbose=True))
    r = safe_analyze(path, use_llm="--no-llm" not in args)
    if not r.get("ok"):
        print(r["error"])
        print(r.get("trace"))
        sys.exit(1)
    print("\n[timing]", r["timings_text"])
    top = r["top"]
    print("[top]", top["title"], top["tier"], top["score"], "缺:", top.get("missing_units"))
    print("[coach]", json.dumps((r.get("coach") or {}).get("data"), ensure_ascii=False)[:600])
    print("[augments]", [a["name"] + "/" + str(a.get("tier")) for a in r["augment_pool"]])
    print("[annotations]", len(r["annotations"]))
