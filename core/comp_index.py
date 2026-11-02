# -*- coding: utf-8 -*-
"""
S18 静态数据 -> 推荐器运行时索引
================================
只读 data/s18db/ 下的 JSON，不改任何数据。

对外：
    idx = load_index()
    comp_index.canonical(idx, "翠神")  # -> "艾翁"
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.dirname(HERE), "data", "s18db")

TIER_SCORE = {"S": 1.0, "A": 0.8, "B": 0.6, "C": 0.4, "D": 0.2}

_index = None


def _load(name):
    with open(os.path.join(DB, name), encoding="utf-8") as f:
        return json.load(f)


def clean(s):
    """去掉空白和常见引号/括号，用于名字对齐。"""
    s = str(s or "").strip()
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"\s+", "", s)
    return s.strip("「」\"'()")


def canonical(idx, raw):
    """把 VLM / OCR 的名字对齐到 heroes.json 的标准名；对不上返回 None。"""
    s = clean(raw)
    if not s:
        return None
    if s in idx["hero_by_name"]:
        return s
    return idx["alias"].get(s)


def _hero_traits(hero):
    out = []
    for t in (hero or {}).get("traits") or []:
        n = clean(t.get("name") if isinstance(t, dict) else t)
        if n:
            out.append(n)
    return out


def _hero_cost(hero):
    try:
        return int((hero or {}).get("cost") or 0)
    except Exception:
        return 0


def _item_name(item, idx):
    if isinstance(item, dict):
        raw = item.get("name") or item.get("id")
    else:
        raw = item
    if raw is None:
        return None
    name = idx["item_name_by_id"].get(str(raw))
    if name:
        return name
    s = clean(raw)
    return s or None


def load_index(force=False):
    global _index
    if _index is not None and not force:
        return _index

    heroes = _load("heroes.json")
    if isinstance(heroes, dict):
        heroes = heroes.get("heroes") or heroes.get("data") or []
    hero_by_name, alias, hero_by_id = {}, {}, {}
    for h in heroes:
        if not isinstance(h, dict):
            continue
        name = clean(h.get("name"))
        if not name:
            continue
        hero_by_name[name] = h
        hero_by_id[str(h.get("id"))] = h
        title = clean(h.get("title"))
        if title and title != name:
            alias.setdefault(title, name)

    items_doc = _load("items.json")
    items = items_doc.get("items") if isinstance(items_doc, dict) else items_doc
    item_name_by_id = {}
    for it in items or []:
        if isinstance(it, dict) and it.get("id") is not None:
            item_name_by_id[str(it["id"])] = clean(it.get("name"))

    traits_doc = _load("traits.json")
    traits = traits_doc.get("traits") if isinstance(traits_doc, dict) else traits_doc
    trait_by_name = {clean(t.get("name")): t for t in (traits or []) if isinstance(t, dict)}

    augments_doc = _load("augments.json")
    augments = augments_doc.get("augments") if isinstance(augments_doc, dict) else augments_doc
    augment_by_name = {
        clean(a.get("name")): a for a in (augments or [])
        if isinstance(a, dict) and clean(a.get("name"))
    }

    idx = {
        "heroes": heroes or [],
        "hero_by_name": hero_by_name,
        "hero_by_id": hero_by_id,
        "alias": alias,
        "traits": trait_by_name,
        "item_name_by_id": item_name_by_id,
        "augments": augments or [],
        "augment_by_name": augment_by_name,
    }
    idx["comps"] = _build_comps(idx)
    idx["warnings"] = list(idx.get("warnings", []))
    _index = idx
    return idx


def _build_comps(idx):
    doc = _load("comps.json")
    rows = doc.get("comps") if isinstance(doc, dict) else doc
    out = []
    warnings = idx.setdefault("warnings", [])

    for c in rows or []:
        if not isinstance(c, dict):
            continue
        board = c.get("board") or {}
        raw_units = board.get("units") or []

        units, main, is_main = [], None, False
        for u in raw_units:
            name = canonical(idx, u.get("name"))
            if not name:
                name = clean(u.get("name"))
                if name:
                    warnings.append("阵容 %s 的单位未对齐：%s" % (c.get("title"), name))
            if name and name not in units:
                units.append(name)
            if u.get("isMain") and name:
                main, is_main = name, True

        main = main or canonical(idx, c.get("mainHeroName"))

        carries = []
        for opt in c.get("equipOptions") or []:
            if not isinstance(opt, dict):
                continue
            h = idx["hero_by_id"].get(str(opt.get("heroId")))
            n = clean(h.get("name")) if h else None
            if n and n not in carries:
                carries.append(n)
        if main and main not in carries:
            carries.insert(0, main)
        if not carries:
            # 没有装备方案时退化为「非 1 费单位」或主 C
            ranked = sorted(
                [u for u in units if u in idx["hero_by_name"]],
                key=lambda n: _hero_cost(idx["hero_by_name"].get(n)),
                reverse=True,
            )
            carries = ranked[:2]

        # 阵容目标羁绊：按不重复单位计数
        trait_count = {}
        for u in units:
            for t in _hero_traits(idx["hero_by_name"].get(u)):
                trait_count[t] = trait_count.get(t, 0) + 1

        # 装备偏好：equipOptions + recommendedEquips
        preferred = set()
        for opt in c.get("equipOptions") or []:
            if isinstance(opt, dict):
                for build in opt.get("equips") or []:
                    for item in build or []:
                        n = _item_name(item, idx)
                        if n:
                            preferred.add(n)
        for u in units:
            h = idx["hero_by_name"].get(u) or {}
            for item in (h.get("recommendedEquips") or []) + (h.get("roleRecommendedEquips") or []):
                n = _item_name(item, idx)
                if n:
                    preferred.add(n)

        stats = c.get("stats") or {}
        tier = str(c.get("tier") or "").upper()
        tags = [clean(x) for x in (c.get("tags") or []) if clean(x)]
        tag_text = " ".join(tags)
        if any(k in tag_text for k in ("追三星", "赌狗")):
            style = "reroll"
        elif any(k in tag_text for k in ("运营", "8级", "9级")):
            style = "level"
        else:
            style = "mixed"

        out.append({
            "id": c.get("id"),
            "title": c.get("title") or "未命名阵容",
            "tier": tier,
            "tier_score": TIER_SCORE.get(tier, 0.5),
            "difficulty": c.get("difficulty") or 1,
            "tags": tags,
            "style": style,
            "main": main,
            "carries": carries,
            "core_units": carries or ([main] if main else []),
            "units": units,
            "traits": trait_count,
            "preferred_items": preferred,
            "stats": stats,
            "early": c.get("earlyDesc") or "",
            "mid": c.get("midDesc") or "",
            "final": c.get("finalDesc") or "",
            "tip_count": len(c.get("tips") or []),
            "is_main_carry": is_main,
        })

    return out
