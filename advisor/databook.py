# -*- coding: utf-8 -*-
"""
S18 静态数据只读访问层（advisor 用）
====================================
只读 data/ 与 data/s18db/，不写任何文件。

和 core/comp_index.py 的区别：
  * comp_index 只保留评分需要的字段（units / traits / preferred_items）；
  * 这里额外暴露 UI 需要的东西：站位(row/col)、备选装备、过渡棋盘、
    阵容码、符文评级、图标路径。

用法：
    import databook
    databook.warm()                      # 预热（后台线程调用）
    h = databook.hero("韦鲁斯")
    c = databook.comp_full(16223)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
DB = os.path.join(DATA, "s18db")

ICON_HERO = os.path.join(DATA, "heroicons_s18")
ICON_AUG = os.path.join(DATA, "augmenticons_s18")
ICON_AUG_INGAME = os.path.join(DATA, "augmenticons_ingame")
ICON_ITEM = os.path.join(DATA, "equipment_s18")

_cache = {}
_icon_cache = {}


def _read(name):
    if name not in _cache:
        with open(os.path.join(DB, name), encoding="utf-8") as f:
            _cache[name] = json.load(f)
    return _cache[name]


def _rows(doc, key):
    if isinstance(doc, dict):
        return doc.get(key) or []
    return doc or []


# ------------------------------------------------------------------ 基础表
def heroes():
    if "heroes" not in _cache:
        rows = _rows(_read("heroes.json"), "heroes")
        _cache["heroes"] = rows
        _cache["hero_by_name"] = {h["name"]: h for h in rows if h.get("name")}
        _cache["hero_by_id"] = {str(h["id"]): h for h in rows if h.get("id") is not None}
    return _cache["heroes"]


def hero(name):
    heroes()
    return _cache["hero_by_name"].get(name) or {}


def hero_cost(name):
    try:
        return int(hero(name).get("cost") or 0)
    except Exception:
        return 0


def items_by_id():
    if "items_by_id" not in _cache:
        rows = _rows(_read("items.json"), "items")
        _cache["items_by_id"] = {str(i["id"]): i for i in rows if i.get("id") is not None}
        _cache["item_by_name"] = {i["name"]: i for i in rows if i.get("name")}
    return _cache["items_by_id"]


def item_name(item_id):
    it = items_by_id().get(str(item_id)) or {}
    return it.get("name")


def item_recipes():
    """[{'name': 成装名, 'parts': [散件, 散件]}]，名称已对齐 items.json"""
    if "item_recipes" not in _cache:
        rows = _rows(_read("items.json"), "items")
        out = []
        for it in rows:
            parts = it.get("recipe") or []
            if len(parts) == 2:
                names = [p.get("name") for p in parts]
                if all(names):
                    out.append({"name": it["name"], "parts": names,
                                "typeRaw": it.get("typeRaw")})
        _cache["item_recipes"] = out
    return _cache["item_recipes"]


def recipe_by_name():
    if "recipe_by_name" not in _cache:
        _cache["recipe_by_name"] = {r["name"]: r["parts"] for r in item_recipes()}
    return _cache["recipe_by_name"]


def recipe_of(item_name):
    """成装 → 两个散件；不是合成装返回 []"""
    return list(recipe_by_name().get(item_name) or [])


def craft_from(pool, item_name):
    """pool 里够不够合出 item_name。返回 (能否, 用掉哪几件)"""
    parts = list(recipe_of(item_name))
    if not parts:
        return False, []
    tmp = list(pool)
    used = []
    for p in parts:
        if p in tmp:
            tmp.remove(p)
            used.append(p)
        else:
            return False, []
    return True, used


def split_parts(pool, item_name):
    """把成装的配方拆成「手上已有」和「还缺」（同名散件按张数算）"""
    parts = list(recipe_of(item_name))
    tmp = list(pool)
    have, lack = [], []
    for p in parts:
        if p in tmp:
            tmp.remove(p)
            have.append(p)
        else:
            lack.append(p)
    return have, lack


def missing_for(pool, item_name):
    """还缺哪几件散件（返回列表；空列表表示现在就能合）"""
    return split_parts(pool, item_name)[1]


COMPONENTS = {"暴风大剑", "反曲之弓", "无用大棒", "女神之泪", "锁子甲",
              "负极斗篷", "巨人腰带", "拳套", "金铲铲", "金锅锅"}


def is_component(name):
    return (name or "") in COMPONENTS


def plan_items(components, equip_plans, limit=3):
    """手上散件 → 能合成的成装，按阵容契合度排序。

    components: ['反曲之弓', '暴风大剑', ...]
    equip_plans: databook.comp_equip_plans() 的结果
    """
    prefer = {}                      # 装备名 -> 需要的英雄
    for plan in equip_plans or []:
        for build in plan.get("builds") or []:
            for n in build:
                prefer.setdefault(n, plan["hero"])

    pool = list(components)
    cands = {}
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            a, b = pool[i], pool[j]
            for r in item_recipes():
                p = r["parts"]
                if (p[0] == a and p[1] == b) or (p[0] == b and p[1] == a):
                    cands.setdefault(r["name"], {"item": r["name"], "from": [a, b],
                                                 "typeRaw": r.get("typeRaw")})
    out = []
    for name, c in cands.items():
        target = prefer.get(name)
        c["target"] = target
        c["in_plan"] = bool(target)
        out.append(c)
    out.sort(key=lambda d: (0 if d["in_plan"] else 1, d["item"]))
    return out[:limit]


# ------------------------------------------------------------------ 概率 / 节奏
# 等级 → 各费用出现概率（%）。取自游戏内 Lv4=55/30/15/0/0 的实测锚点，
# 站点 shop_odds.json 的 level 编号与游戏内可能错位一档，所以这里内置优先。
GAME_SHOP_ODDS = {
    1: [100, 0, 0, 0, 0],
    2: [100, 0, 0, 0, 0],
    3: [75, 25, 0, 0, 0],
    4: [55, 30, 15, 0, 0],
    5: [45, 33, 20, 2, 0],
    6: [30, 40, 25, 5, 0],
    7: [19, 30, 35, 15, 1],
    8: [18, 25, 36, 18, 3],
    9: [10, 20, 25, 35, 10],
}
SHOP_SLOTS = 5
POOL_PER_COST = {1: 30, 2: 25, 3: 18, 4: 10, 5: 9}
LEVEL_UP_EXP = {1: 2, 2: 6, 3: 10, 4: 20, 5: 36, 6: 56, 7: 68, 8: 68, 9: 84}


def hero_count_by_cost():
    if "hero_count_by_cost" not in _cache:
        out = {}
        for h in heroes():
            c = int(h.get("cost") or 0)
            if c:
                out[c] = out.get(c, 0) + 1
        _cache["hero_count_by_cost"] = out
    return _cache["hero_count_by_cost"]


def shop_odds(level):
    """该等级每个格子的各费概率（0~1 的小数）"""
    row = GAME_SHOP_ODDS.get(int(level or 1)) or GAME_SHOP_ODDS[4]
    return {i + 1: row[i] / 100.0 for i in range(5)}


def find_chance(level, cost, owned=0, copies=1):
    """一次刷新（5 格）至少出现 1 张目标牌的概率，以及期望刷数。

    owned 是你已持有的张数（会从卡池里扣掉，粗略处理）。
    """
    odds = shop_odds(level).get(int(cost or 1), 0.0)
    n = hero_count_by_cost().get(int(cost or 1), 1) or 1
    pool = max(1, POOL_PER_COST.get(int(cost or 1), 20) - int(owned or 0))
    per_hero = (POOL_PER_COST.get(int(cost or 1), 20)) / float(n)     # 平均每英雄份数
    share = min(1.0, pool / float(POOL_PER_COST.get(int(cost or 1), 20)))
    p_slot = odds / float(n) * share
    p_shop = 1.0 - (1.0 - p_slot) ** SHOP_SLOTS
    return {"p_shop": p_shop,
            "rolls_to_one": (1.0 / p_shop) if p_shop > 0 else 999,
            "p_slot": p_slot,
            "per_hero": per_hero}


def level_up_exp(level):
    return LEVEL_UP_EXP.get(int(level or 1), 60)


def gold_to_level(level, exp_text):
    """还差多少经验 / 多少金币买经验升下一级（1 金 = 1 经验）

    优先用截图里读到的 "当前/上限"，读不到才退回内置表。
    """
    try:
        cur, cap = [int(x) for x in str(exp_text).split("/")]
    except Exception:
        cur, cap = 0, level_up_exp(level)
    gap = max(0, cap - cur)
    return {"exp_gap": gap, "gold": gap, "cap": cap, "cur": cur}


def core_override():
    """config/equip_core.json：人工钉死的核心装 {英雄: 装备}"""
    if "core_override" not in _cache:
        p = os.path.join(os.path.dirname(HERE), "config", "equip_core.json")
        data = {}
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    data = {k: v for k, v in json.load(f).items()
                            if isinstance(v, str) and not k.startswith("_")}
            except Exception:
                data = {}
        _cache["core_override"] = data
    return _cache["core_override"]


def rank_build(hero_name, comp_id, build):
    """判断一套三神装里的件内优先级，返回按重要性排序的列表（第一个 = 核心）

    四个来源各自按「第 1/2/3 位」计分，累加：
      成型棋盘 board.units[].equips  → 站点的最终方案
      本阵容 equipOptions[0]          → 这套打法的第一选择
      heroes.recommendedEquips        → 该英雄的通用三神装
      heroes.roleRecommendedEquips    → 职业模板（更像「机制需求」）
    只有本阵容 build 里出现的件参与排序。
    """
    build = [b for b in (build or []) if b]
    if not build:
        return []
    # 人工覆盖优先
    fixed = core_override().get(hero_name)
    if fixed and fixed in build:
        return [fixed] + [b for b in build if b != fixed]
    comp = comp_full(comp_id) or {}
    board_equips = []
    for u in (comp.get("board") or {}).get("units") or []:
        if u.get("name") == hero_name:
            board_equips = [e.get("name") for e in (u.get("equips") or []) if e.get("name")]
    h = hero(hero_name) or {}
    rec = [x.get("name") for x in (h.get("recommendedEquips") or []) if x.get("name")]
    role = [x.get("name") for x in (h.get("roleRecommendedEquips") or []) if x.get("name")]

    weights = (2.0, 1.0, 0.5)
    role_weights = (2.5, 1.0, 0.5)      # 职业模板更贴「机制需求」，第 1 位加权
    score, firsts = {}, {}

    def add(names, w=weights):
        for i, n in enumerate(names[:len(w)]):
            score[n] = score.get(n, 0.0) + w[i]
            if i == 0:
                firsts[n] = firsts.get(n, 0) + 1

    add(board_equips, (3.0, 1.5, 0.6))     # 成型棋盘最权威
    add(build, (2.0, 1.4, 0.6))
    add(rec, (2.0, 1.0, 0.5))
    add(role, role_weights)

    def key(n):
        board_i = board_equips.index(n) if n in board_equips else 99
        role_i = role.index(n) if n in role else 99
        # 分数 → 被几个来源排第 1 → 职业模板里的位置 → 棋盘位置
        return (-score.get(n, 0.0), -firsts.get(n, 0), role_i, board_i, build.index(n))

    return sorted(build, key=key)


def traits_by_name():
    if "traits_by_name" not in _cache:
        rows = _rows(_read("traits.json"), "traits")
        _cache["traits_by_name"] = {t["name"]: t for t in rows if t.get("name")}
    return _cache["traits_by_name"]


def trait_breakpoints(name):
    t = traits_by_name().get(name) or {}
    return [int(b.get("unitCount") or 0) for b in (t.get("breakpoints") or [])]


def trait_next(name, count):
    """当前 count 的下一个档位（没有就返回 None）"""
    for n in trait_breakpoints(name):
        if n > (count or 0):
            return n
    return None


# ------------------------------------------------------------------ 阵容
def comps_raw():
    if "comps_raw" not in _cache:
        rows = _rows(_read("comps.json"), "comps")
        _cache["comps_raw"] = {c.get("id"): c for c in rows}
    return _cache["comps_raw"]


def comp_full(comp_id):
    return comps_raw().get(comp_id) or {}


def comp_board(comp_id):
    """成型棋盘：[{name,row,col,stars,isMain,equips:[名字]}]"""
    comp = comp_full(comp_id)
    out = []
    for u in (comp.get("board") or {}).get("units") or []:
        equips = []
        for e in u.get("equips") or []:
            n = e.get("name") if isinstance(e, dict) else None
            n = n or item_name(e.get("id") if isinstance(e, dict) else e)
            if n and n not in equips:
                equips.append(n)
        out.append({"name": u.get("name"), "row": u.get("row"), "col": u.get("col"),
                    "slot": u.get("slot"), "stars": u.get("stars"),
                    "isMain": bool(u.get("isMain")), "equips": equips})
    return out


def comp_early_board(comp_id):
    comp = comp_full(comp_id)
    out = []
    for u in (comp.get("earlyBoard") or {}).get("units") or []:
        out.append({"name": u.get("name"), "row": u.get("row"), "col": u.get("col"),
                    "stars": u.get("stars"), "isMain": bool(u.get("isMain"))})
    return out


def comp_equip_plans(comp_id):
    """[{'hero': 名字, 'builds': [[装备名×3], [备选], ...]}]"""
    comp = comp_full(comp_id)
    heroes()                                    # 确保 hero_by_id 已建好
    heroes_by_id = _cache.get("hero_by_id") or {}
    out = []
    for opt in comp.get("equipOptions") or []:
        h = heroes_by_id.get(str(opt.get("heroId"))) or {}
        builds = []
        for build in opt.get("equips") or []:
            names = [item_name(x) for x in build or []]
            names = [n for n in names if n]
            if names:
                builds.append(names)
        if h.get("name") and builds:
            out.append({"hero": h["name"], "builds": builds,
                        "cost": int(h.get("cost") or 0)})
    return out


def comp_conditions(comp_id):
    """把站点 conditions 里的筛选条件翻译成人话：变阵触发条件"""
    comp = comp_full(comp_id)
    raw = comp.get("conditions")
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return []
    out = []
    for f in data.get("filterOptionResults") or []:
        if not f.get("switchVal"):
            continue
        kind = "英雄" if f.get("type") == "hero" else (
            "羁绊" if f.get("type") == "trait" else str(f.get("type") or "条件"))
        bits = [f.get("name") or "?"]
        if f.get("levelValue") and f["levelValue"] != "任意":
            bits.append("%s星" % f["levelValue"])
        if f.get("equipValue") and f["equipValue"] != "任意":
            bits.append("装备 %s" % f["equipValue"])
        if f.get("attackEquipValue") and f["attackEquipValue"] != "任意":
            bits.append("攻击装 %s" % f["attackEquipValue"])
        if f.get("traitLevelText"):
            bits.append("%s 人口档" % f["traitLevelText"])
        out.append("%s：%s" % (kind, " · ".join(bits)))
    for f in data.get("exclusionFilterOptionResults") or []:
        if f.get("switchVal"):
            out.append("排除：%s" % (f.get("name") or "?"))
    return out


def comp_code(comp_id):
    comp = comp_full(comp_id)
    return comp.get("jccCode") or comp.get("tftCode") or ""


# ------------------------------------------------------------------ 强化符文
def augment_tiers():
    """{名字: {tier, rarityZh, rounds, typeZh, desc, hexId}}"""
    if "augment_tiers" not in _cache:
        rows = _rows(_read("augments_tier.json"), "levels")
        out = {}
        for r in rows:
            n = r.get("name")
            if n and n not in out:
                out[n] = r
        _cache["augment_tiers"] = out
    return _cache["augment_tiers"]


def augments_by_name():
    if "augments_by_name" not in _cache:
        rows = _rows(_read("augments.json"), "augments")
        _cache["augments_by_name"] = {a["name"]: a for a in rows if a.get("name")}
    return _cache["augments_by_name"]


def augment_info(name):
    t = dict(augment_tiers().get(name) or {})
    a = augments_by_name().get(name) or {}
    for k in ("hexId", "rarity", "desc", "rounds"):
        if not t.get(k) and a.get(k):
            t[k] = a[k]
    if not t.get("tier"):
        t["tier"] = None
    return t


# ------------------------------------------------------------------ 图标
# equipment_s18 是按旧版翻译建的图库，个别新译名要做映射
ITEM_ICON_ALIAS = {"巨人捕手": "巨人杀手", "锐利之刃": "死亡之刃", "汲取剑": "饮血剑"}


def _icon(dir_path, name):
    if not name:
        return None
    if (dir_path, name) in _icon_cache:
        return _icon_cache[(dir_path, name)]
    path = None
    for ext in (".png", ".jpg"):
        p = os.path.join(dir_path, name + ext)
        if os.path.exists(p):
            path = p
            break
    _icon_cache[(dir_path, name)] = path
    return path


def icon_hero(name):
    return _icon(ICON_HERO, name)


def icon_item(name):
    return _icon(ICON_ITEM, ITEM_ICON_ALIAS.get(name, name)) or _icon(ICON_ITEM, name)


def icon_augment(name):
    return _icon(ICON_AUG_INGAME, name) or _icon(ICON_AUG, name)


def warm():
    """后台预热：只做 IO，PyQt 那边调用前先跑它可以把首屏压到 0.2s 内"""
    heroes()
    items_by_id()
    traits_by_name()
    comps_raw()
    augment_tiers()
    augments_by_name()
