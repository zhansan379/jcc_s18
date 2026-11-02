# -*- coding: utf-8 -*-
"""
当前局面 vs S18 阵容模板
========================
输入：scan.py --json 产生的字典（中文键）
输出：Top N 候选、缺失单位、羁绊/装备/商店匹配情况

这是一个可解释的规则评分器，不是「正确答案」：
权重在 config/strategy_rules.json 里，可用真实对局标注后调整。
"""
from collections import Counter

from comp_index import canonical, clean

DEFAULT_WEIGHTS = {
    "core_units": 0.30,
    "units": 0.15,
    "traits": 0.20,
    "items": 0.08,
    "shop": 0.10,
    "meta": 0.08,
    "economy": 0.04,
    "augments": 0.05,
}


def _clean(s):
    return str(s or "").replace("（", "(").replace("）", ")").strip()


def _state_units(state, idx):
    units = []
    named = 0
    for u in state.get("单位") or []:
        raw = u.get("name")
        name = canonical(idx, raw)
        if name:
            named += 1
        units.append({
            "name": name,
            "raw_name": raw,
            "star": u.get("star"),
            "area": u.get("area") or "board",
            "items": [x.get("name") for x in (u.get("items") or []) if isinstance(x, dict)],
        })
    total = len(units)
    return units, named, total


def _state_traits(state, units, idx):
    out = {}
    for t in state.get("羁绊") or []:
        n = _clean(t.get("name") if isinstance(t, dict) else t)
        c = t.get("count") if isinstance(t, dict) else None
        if n and isinstance(c, int):
            out[n] = max(out.get(n, 0), c)

    if out:
        return out

    # 没有羁绊面板时，用已命名的单位反推（只算不重复英雄）
    for name in {u["name"] for u in units if u["name"]}:
        h = idx["hero_by_name"].get(name) or {}
        for t in h.get("traits") or []:
            n = _clean(t.get("name") if isinstance(t, dict) else t)
            if n:
                out[n] = out.get(n, 0) + 1
    return out


def _state_items(state, units):
    names = []
    for u in units:
        names.extend(u["items"])
    for x in state.get("装备栏") or []:
        if isinstance(x, dict) and x.get("name"):
            names.append(x["name"])
    return [n for n in names if n]


def _state_shop(state, idx):
    out = []
    for x in state.get("商店") or []:
        n = canonical(idx, x)
        if n:
            out.append(n)
    return out


def _state_augments(state, idx):
    """只使用已识别且可信的符文；返回 [{name, meta, styles}]。"""
    out = []
    for a in state.get("强化符文") or []:
        if not isinstance(a, dict):
            continue
        if a.get("reliable") is False:
            continue
        name = clean(a.get("name"))
        if not name:
            top = a.get("top") or []
            if top and isinstance(top[0], dict):
                name = clean(top[0].get("name"))
        if not name:
            continue
        meta = idx["augment_by_name"].get(name)
        out.append({"name": name, "meta": meta, "styles": _augment_styles(name, meta)})
    return out


def _augment_styles(name, meta):
    text = name
    if meta:
        text += " " + str(meta.get("desc") or "")
        text += " " + " ".join(meta.get("typeZh") or [])
    styles = set()
    if any(k in text for k in ("刷新", "商店")):
        styles.add("reroll")
    if any(k in text for k in ("金币", "利息")):
        styles.add("econ")
    if any(k in text for k in ("经验", "人口")):
        styles.add("level")
    if meta and "经济" in (meta.get("typeZh") or []):
        styles.add("econ")
    return styles


def _augment_fit(comp, augments):
    """经济/刷新类符文偏慢 D 阵容；经验类偏运营。返回 (0~1, 命中列表)。"""
    if not augments:
        return 0.5, []
    best, hits = 0.5, []
    for aug in augments:
        styles = aug["styles"]
        fit = 0.5
        if comp.get("style") == "reroll" and "reroll" in styles:
            fit = 1.0
        elif comp.get("style") == "level" and "level" in styles:
            fit = 0.9
        elif comp.get("style") == "reroll" and "econ" in styles:
            fit = 0.8
        elif comp.get("style") == "level" and "econ" in styles:
            fit = 0.4
        if fit >= best:
            best = fit
            hits.append({"name": aug["name"], "fit": round(fit, 2)})
    return best, hits


def _score_comp(comp, ctx, weights):
    owned = ctx["owned"]
    owned_set = set(owned)
    state_traits = ctx["traits"]
    state_items = set(ctx["items"])
    shop = ctx["shop"]
    augment_score, augment_hits = _augment_fit(comp, ctx.get("augments") or [])

    units = comp["units"]
    present = [u for u in units if u in owned_set]
    core = comp["core_units"]
    core_present = [u for u in core if u in owned_set]

    unit_score = len(present) / len(units) if units else 0.0
    core_score = len(core_present) / len(core) if core else unit_score

    trait_total = sum(comp["traits"].values())
    trait_hit = 0.0
    trait_gaps = []
    for name, target in comp["traits"].items():
        cur = state_traits.get(name, 0)
        trait_hit += min(cur, target)
        if cur < target:
            trait_gaps.append({"name": name, "current": cur, "target": target})
    trait_score = trait_hit / trait_total if trait_total else 0.0

    preferred = comp["preferred_items"]
    item_hits = sorted(state_items & preferred) if preferred else []
    item_score = min(1.0, len(item_hits) / max(2, min(6, len(state_items)))) if state_items else 0.0

    shop_hits = [s for s in shop if s in set(units)]
    shop_score = len(shop_hits) / len(shop) if shop else 0.0

    stats = comp.get("stats") or {}
    try:
        top4 = float(stats.get("top4Rate") or 0) / 100.0
        win = float(stats.get("winRate") or 0) / 100.0
    except Exception:
        top4 = win = 0.0
    meta_score = 0.55 * comp["tier_score"] + 0.30 * top4 + 0.15 * win

    try:
        diff = int(comp.get("difficulty") or 1)
    except Exception:
        diff = 1
    econ_score = max(0.3, 1.0 - 0.15 * (diff - 1))

    score = (
        weights["core_units"] * core_score
        + weights["units"] * unit_score
        + weights["traits"] * trait_score
        + weights["items"] * item_score
        + weights["shop"] * shop_score
        + weights["meta"] * meta_score
        + weights["economy"] * econ_score
        + weights["augments"] * augment_score
    )

    missing_units = [u for u in units if u not in owned_set]
    missing_core = [u for u in core if u not in owned_set]

    reasons = []
    if core:
        reasons.append("核心 %d/%d 已有" % (len(core_present), len(core)))
    if units:
        reasons.append("单位 %d/%d 已有" % (len(present), len(units)))
    if trait_total:
        reasons.append("目标羁绊覆盖 %d/%d" % (int(round(trait_hit)), trait_total))
    if item_hits:
        reasons.append("装备命中 %s" % "、".join(item_hits[:3]))
    if shop_hits:
        reasons.append("商店有 %s" % "、".join(shop_hits))
    if augment_hits:
        reasons.append("符文契合：%s" % "、".join(
            "%s(%.1f)" % (h["name"], h["fit"]) for h in augment_hits))

    return {
        "id": comp["id"],
        "title": comp["title"],
        "tier": comp["tier"],
        "style": comp.get("style") or "mixed",
        "score": round(score, 4),
        "score_parts": {
            "core_units": round(core_score, 3),
            "units": round(unit_score, 3),
            "traits": round(trait_score, 3),
            "items": round(item_score, 3),
            "shop": round(shop_score, 3),
            "meta": round(meta_score, 3),
            "economy": round(econ_score, 3),
            "augments": round(augment_score, 3),
        },
        "main": comp["main"],
        "carries": comp["carries"],
        "core_units": core,
        "matched_units": present,
        "missing_units": missing_units,
        "missing_core": missing_core,
        "trait_gaps": trait_gaps,
        "shop_hits": shop_hits,
        "item_hits": item_hits,
        "augment_hits": augment_hits,
        "augment_fit": round(augment_score, 3),
        "preferred_items": sorted(preferred)[:12],
        "stats": stats,
        "difficulty": comp.get("difficulty"),
        "tags": comp.get("tags") or [],
        "reasons": reasons,
        "early": comp.get("early") or "",
        "mid": comp.get("mid") or "",
        "final": comp.get("final") or "",
    }


def recommend(state, idx, rules=None, top=3):
    """返回 {"candidates": [...], "state": {...}, "warnings": [...]}"""
    rules = rules or {}
    weights = dict(DEFAULT_WEIGHTS)
    weights.update(rules.get("weights") or {})

    units, named, total = _state_units(state, idx)
    traits = _state_traits(state, units, idx)
    items = _state_items(state, units)
    shop = _state_shop(state, idx)
    augments = _state_augments(state, idx)
    owned = [u["name"] for u in units if u["name"]]
    owned_counts = Counter(owned)

    named_ratio = (named / total) if total else 0.0
    ctx = {
        "units": units,
        "owned": owned,
        "owned_counts": owned_counts,
        "traits": traits,
        "items": items,
        "shop": shop,
        "augments": augments,
    }

    candidates = [_score_comp(c, ctx, weights) for c in idx["comps"]]
    candidates.sort(key=lambda x: (-x["score"], x["title"]))
    top_candidates = candidates[:max(1, int(top))]

    # 置信度：名字覆盖率 + 绝对匹配分 + 与第二名的差距
    for i, c in enumerate(top_candidates):
        margin = c["score"] - top_candidates[i + 1]["score"] if i + 1 < len(top_candidates) else 0.0
        conf = (
            0.15
            + 0.35 * named_ratio
            + 0.35 * c["score"]
            + 0.15 * min(1.0, max(0.0, margin) * 5)
        )
        if named_ratio < 0.35:
            conf = min(conf, 0.35)
        c["confidence"] = round(max(0.0, min(1.0, conf)), 3)

    warnings = []
    if named_ratio >= 0.6 and top_candidates and top_candidates[0]["score"] < 0.45:
        warnings.append(
            "最高候选分仅 %.2f：当前棋盘与主流阵容差距较大，候选更适合当转型参考"
            % top_candidates[0]["score"]
        )
    if total == 0:
        warnings.append("没有读到单位；只能做经济建议，无法匹配阵容")
    elif named == 0:
        warnings.append("单位没有名字（%d/%d）：阵容候选仅供参考；建议先跑 --labels 或 --names" % (named, total))
    elif named < total:
        warnings.append("有 %d/%d 个单位没有名字，阵容匹配置信度下降" % (total - named, total))
    if not shop:
        warnings.append("商店没有可识别的英雄名")
    raw_augments = [x for x in (state.get("强化符文") or []) if isinstance(x, dict)]
    if raw_augments and not augments:
        warnings.append("强化符文未识别或不可信，未参与评分")
    if not candidates:
        warnings.append("没有可用阵容数据，请检查 data/s18db/comps.json")

    for w in idx.get("warnings") or []:
        if w not in warnings:
            warnings.append(w)

    return {
        "candidates": top_candidates,
        "state": {
            "stage": state.get("阶段"),
            "level": state.get("等级"),
            "exp": state.get("经验"),
            "gold": state.get("金币"),
            "hp": state.get("我的血量"),
            "units": len(units),
            "named_units": named,
            "named_ratio": round(named_ratio, 3),
            "shop": shop,
            "traits": traits,
            "items": items,
            "augments": [a["name"] for a in augments],
            "augment_styles": sorted({s for a in augments for s in a["styles"]}),
            "owned_counts": dict(owned_counts),
        },
        "warnings": warnings,
    }
