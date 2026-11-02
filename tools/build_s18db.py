"""把已提取的 S18 数据源整理进 data/s18db/（只读静态数据）。

数据来源：
  - jcc.datatft.com（金铲铲大数据）导出的 HTML + 站点数据包 h5-data-cn-18.json
运行：python tools/build_s18db.py
（阵容 comps.json 由 tools/fetch_jcc_comps.py 单独生成）
"""
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trait_effects import parse as parse_effects  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = r"D:\Download\browserDownload"
DST = os.path.join(ROOT, "data", "s18db")
RAW = os.path.join(DST, "raw")


def load(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return json.load(f)


def save(name, obj):
    path = os.path.join(DST, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return os.path.getsize(path)


# 属性标记：【AD】+10%（装备） / 12%【AD】（羁绊）
STAT_ALIASES = {
    "AD": "attackDamage", "AP": "abilityPower", "HP": "health",
    "ARMOR": "armor", "MR": "magicResist", "AS": "attackSpeed",
    "DR": "damageReduction", "CRIT": "critChance", "MANA": "mana",
    "MANAREGEN": "manaRegen", "CRITMULT": "critDamage",
    "DA": "damageAmp", "SV": "omnivamp",
}
ITEM_STAT_RE = re.compile(r"【([A-Z]{2,8})】\s*([+-]?\d+(?:\.\d+)?)\s*(%?)")
TRAIT_STAT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(%?)\s*((?:【[A-Z]{2,8}】)+)")


def parse_item_stats(text):
    out = []
    for m in ITEM_STAT_RE.finditer(text or ""):
        tag = m.group(1)
        if tag == "DIST":
            continue
        out.append({"stat": tag, "statKey": STAT_ALIASES.get(tag, tag.lower()),
                    "value": float(m.group(2)), "percent": bool(m.group(3))})
    return out


def enrich_items(items, pack_site, old_equipment):
    """给装备补 stats（来自 effectAttr / effect）和 recipe（来自项目原有 EquipmentData.json）。"""
    by_id = {e["equipId"]: e for e in pack_site["equips18"]}
    name_idx = {}
    for e in pack_site["equips18"]:
        for n in [e.get("name"), e.get("jccname")] + list(e.get("otherNames") or []):
            if n:
                name_idx.setdefault(n, e["equipId"])

    recipes = {}
    for r in old_equipment:
        if not r.get("SyntheticPathway"):
            continue
        eid = name_idx.get(r["Name"])
        if not eid:
            continue
        recipes[eid] = [{"name": c, "id": name_idx.get(c)} for c in r["SyntheticPathway"]]

    stat_hit = 0
    for it in items["items"]:
        e = by_id.get(it["id"], {})
        stats = parse_item_stats(e.get("effectAttr")) or parse_item_stats(e.get("effect"))
        it["stats"] = stats
        if stats:
            stat_hit += 1
        rec = recipes.get(it["id"])
        if rec:
            it["recipe"] = rec
    items["meta"]["statNote"] = "stats 由站点 effectAttr（成装）或 effect（散件）里的【AD】+10% 标记解析"
    items["meta"]["statParsed"] = stat_hit
    items["meta"]["recipeNote"] = "recipe 来自项目原有 data/EquipmentData.json，按中文名/别名对齐到站点 equipId"
    items["meta"]["recipeCount"] = len(recipes)
    return stat_hit, len(recipes)


def parse_trait_stats(traits):
    """从档位文本里抽出「数值 + 属性标记」，抽不出来就返回空数组（不猜）。"""
    hit = 0
    for t in traits["traits"]:
        for bp in t["breakpoints"]:
            text = bp.get("effect") or ""
            eff = parse_effects(text, t.get("key"), bp.get("unitCount"))
            bp["effects"] = eff
            bp["stats"] = [{"stat": e["stat"], "statKey": e["statKey"],
                            "value": e["value"], "percent": e["percent"]}
                           for e in eff if e["kind"] == "stat"]
            if eff:
                hit += 1
    return hit


def split_skill_growth(heroes):
    """把 skill.breakdown 里的 [1/2/3/(4)] 数组拆成 {星级: 值}。

    1~2 费有 4 个值（4 星系统），3 费以上 3 个值。
    """
    hit = 0
    for h in heroes["heroes"]:
        sk = h.get("skill") or {}
        rows = []
        for b in sk.get("breakdown") or []:
            arr = b.get("array") or ""
            m = re.search(r"\[([^\]]+)\]", arr)
            if not m:
                continue
            parts = [p.strip() for p in re.split(r"[/／]", m.group(1)) if p.strip()]
            vals, pct = [], False
            for p in parts:
                is_pct = p.endswith("%")
                pct = pct or is_pct
                try:
                    vals.append(float(p.rstrip("%")))
                except ValueError:
                    vals.append(None)
            if not vals or any(v is None for v in vals):
                continue
            label = re.sub(r"[：:].*$", "", b.get("label") or "").strip()
            rows.append({
                "label": label,
                "percent": pct,
                "starCount": len(vals),
                "byStar": {str(i + 1): vals[i] for i in range(min(len(vals), 4))},
            })
            hit += 1
        sk["starScaling"] = rows
    heroes["meta"]["starScalingNote"] = (
        "skill.starScaling[].byStar 为各星级数值；1~2 费数组长度 4（含 4 星），3 费以上长度 3。"
        "由 skill.breakdown 的 [x/y/z] 原文拆分，未做插值。")
    heroes["meta"]["starScalingRows"] = hit
    return hit


def merge_augment_stats(augments):
    """把 dataj 的样本量/名次/分阶段表现 + 图标合并进 augments.json。"""
    path = os.path.join(DST, "augment_stats.json")
    if not os.path.exists(path):
        return 0
    rows = json.load(open(path, encoding="utf-8"))["stats"]
    by_hex = {r["augmentHexId"]: r for r in rows if r.get("augmentHexId")}
    hit = 0
    for a in augments["augments"]:
        r = by_hex.get(a["hexId"])
        if not r:
            continue
        if r.get("sampleCount") is not None:
            a["stats"] = {
                "sampleCount": r.get("sampleCount"),
                "playRate": r.get("playRate"),
                "avgPlacement": r.get("avgPlacement"),
                "top4Rate": r.get("top4Rate"),
                "topRate": r.get("topRate"),
                "rounds": r.get("rounds"),
                "roundStats": r.get("roundStats"),
            }
            hit += 1
        a["datajHexId"] = r.get("datajHexId")
        a["datajName"] = r.get("datajName")
        icon = r.get("iconFile")
        if icon and os.path.exists(os.path.join(DST, icon)):
            a["iconFile"] = icon
        elif os.path.exists(os.path.join(DST, "images", "augments", "%s.png" % a["hexId"])):
            a["iconFile"] = "images/augments/%s.png" % a["hexId"]
    augments["meta"]["statsNote"] = ("stats 来自 dataj.cc/hex（样本量/出场率/平均名次/前四率/吃鸡率 + 3-2、4-2 分阶段）；"
                                     "iconFile 指向 images/augments/<hexId>.png")
    augments["meta"]["statsCount"] = hit
    augments["meta"]["iconCount"] = sum(1 for a in augments["augments"] if a.get("iconFile"))
    return hit


def flush_trait_effects(traits):
    for t in traits["traits"]:
        for bp in t["breakpoints"]:
            bp["stats"] = [{"stat": e["stat"], "statKey": e["statKey"],
                            "value": e["value"], "percent": e["percent"]}
                           for e in bp.get("effects", []) if e["kind"] == "stat"]
    return traits


def main():
    os.makedirs(DST, exist_ok=True)
    os.makedirs(RAW, exist_ok=True)

    heroes = load("jcc_s18_heroes.json")
    growth_rows = split_skill_growth(heroes)
    wisps = load("jcc_s18_augments.json")   # 这 181 条实际是「仙灵」(charms)，不是强化符文
    traits = load("jcc_s18_traits.json")
    stat_hits = parse_trait_stats(traits)
    traits["meta"]["statParseNote"] = "breakpoints[].stats 由文本中的【AD】【AP】等标记解析而来，抽不出就为空数组"
    traits["meta"]["statParsedBreakpoints"] = stat_hits
    items = load("jcc_s18_items.json")
    old_equipment = json.load(open(os.path.join(ROOT, "data", "EquipmentData.json"), encoding="utf-8"))
    site_pack = json.load(open(os.path.join(RAW, "site-data-cn.json"), encoding="utf-8"))
    item_stat_hit, recipe_hit = enrich_items(items, site_pack, old_equipment)
    wisp_rules = load("jcc_wisp_rules.json")
    pack = load("h5-data-cn-18.json")

    sizes = {}
    sizes["heroes.json"] = save("heroes.json", heroes)
    sizes["wisps.json"] = save("wisps.json", {
        "meta": {
            "source": "jcc.datatft.com/database#charm（站点「仙灵」tab）+ h5-data-cn-18.json#charms18",
            "count": len(wisps["augments"]),
            "note": "仙灵（charms）。注意：这与「强化符文」是两套数据，别混用。",
        },
        "wisps": wisps["augments"],
    })
    sizes["traits.json"] = save("traits.json", traits)
    sizes["items.json"] = save("items.json", items)
    sizes["wisp_rules.json"] = save("wisp_rules.json", wisp_rules)
    augments = json.load(open(os.path.join(DST, "augments.json"), encoding="utf-8"))
    stat_hits_aug = merge_augment_stats(augments)
    sizes["augments.json"] = save("augments.json", augments)
    augments_tier = json.load(open(os.path.join(DST, "augments_tier.json"), encoding="utf-8"))
    # comps.json / comps_summary.json 由 tools/fetch_jcc_comps.py 直接生成（金铲铲阵容榜单）
    comps = json.load(open(os.path.join(DST, "comps.json"), encoding="utf-8"))

    # ---- 商店概率：9 级 × 5 费，按等级优先排列 ----
    flat = pack["rates18"]
    rows = [flat[i * 5:(i + 1) * 5] for i in range(9)]
    shop = {
        "meta": {
            "source": "h5-data-cn-18.json#rates18（45 = 9 级 × 5 费，行优先）",
            "set": "S18",
            "note": "每行是一个等级下 1~5 费的出现概率，单位为 %；每行合计 100。",
        },
        "poolSizeByCost": dict(zip(["1", "2", "3", "4", "5"], pack["quantitys18"])),
        "shopSlots": 5,
        "byLevel": [
            {"level": i + 1,
             "oddsPct": {(c + 1): (None if rows[i][c] == "-" else float(rows[i][c].rstrip("%"))) for c in range(5)},
             "oddsRaw": {str(c + 1): rows[i][c] for c in range(5)}}
            for i in range(9)
        ],
    }
    sizes["shop_odds.json"] = save("shop_odds.json", shop)

    # ---- 经济 / 伤害表 ----
    exp = pack["exps18"]
    economy = {
        "meta": {"source": "h5-data-cn-18.json + jcc_rate_tables.json", "set": "S18"},
        "levelUpExp": [{"fromLevel": i + 1, "toLevel": i + 2, "exp": v} for i, v in enumerate(exp)],
        "roundGold": [
            {"round": r, "gold": g} for r, g in zip(
                ["1-1", "1-2", "1-3", "1-4", "2-1", "2-2"],
                ["-", "+2", "+2", "+3", "+4", "+5"])
        ],
        "interest": [{"goldRange": k, "interest": v} for k, v in
                     [("0-9", "-"), ("10-19", "+1"), ("20-29", "+2"),
                      ("30-39", "+3"), ("40-49", "+4"), ("50+", "+5")]],
        "streakGold": [{"streak": i + 1, "gold": v} for i, v in enumerate(pack["golds18"])],
        "roundGoldNote": "站点只公开 1-1~2-2 六回合，之后回合金币未在数据源中出现。",
        "stageBaseDamage": [{"stage": i + 1, "damage": v} for i, v in enumerate(pack["hps18"])],
        "survivorDamage": [{"units": i + 1, "damage": v} for i, v in enumerate(pack["damages18"])],
        "goldStreakRaw": pack["golds18"],
    }
    sizes["economy.json"] = save("economy.json", economy)

    # ---- 原始包 ----
    shutil.copyfile(os.path.join(SRC, "h5-data-cn-18.json"), os.path.join(RAW, "h5-data-cn-18.json"))
    shutil.copyfile(os.path.join(SRC, "jcc_rate_tables.json"), os.path.join(RAW, "jcc_rate_tables.json"))

    # ---- 装备合成路径（沿用项目原有数据，名称体系与 items.json 有差异）----
    old = json.load(open(os.path.join(ROOT, "data", "EquipmentData.json"), encoding="utf-8"))
    recipes = [e for e in old if e.get("SyntheticPathway")]
    sizes["item_recipes.json"] = save("item_recipes.json", {
        "meta": {
            "source": "data/EquipmentData.json（项目原有数据）",
            "totalItems": len(old), "withRecipe": len(recipes),
            "note": "与 items.json 的装备名称有约 13 处翻译差异（如 暴风大剑/暴风之剑、饮血剑/汲取剑），尚未按 id 合并，使用时需先对齐名称。",
        },
        "recipes": recipes,
    })

    manifest = {
        "set": "S18",
        "built_from": [
            "https://jcc.datatft.com/database（金铲铲大数据，18.5c / 2026-10-29）",
            "https://jcc.datatft.com/wisp-rules（仙灵互斥规则，LittleBuddyBot）",
            "https://jcc.datatft.com/rate（概率表）",
            "https://jcc.datatft.com/comp/rank（金铲铲阵容榜单，api.datatft.com/team/rank，18.5b / 2026-10-24）",
            "https://jcc.datatft.com/augment/tier（强化果实评级，api.datatft.com/augment-tier/config，18.4）",
        ],
        "files": {k: os.path.getsize(os.path.join(DST, k)) for k in sizes},
        "counts": {
            "heroes": len(heroes["heroes"]),
            "traits": len(traits["traits"]),
            "items": len(items["items"]),
            "augments": len(augments["augments"]),
            "augments": len(augments["augments"]),
            "comps": len(comps["comps"]),
            "wisps": len(wisps["augments"]),
            "wisp_rules": len(wisp_rules["rules"]),
            "augments_rated": len(augments_tier["levels"]),
        },
        "caveat": "全部数据来自金铲铲（datatft）。阵容强度为站点榜单口径，未按段位分桶。",
    }
    sizes["manifest.json"] = save("manifest.json", manifest)
    print(json.dumps({"dir": DST, "counts": manifest["counts"], "files": sizes},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
