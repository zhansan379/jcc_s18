"""把羁绊档位文本解析成结构化 effects 列表。

只做「有明确数字/对象」的抽取，抽不出来就留空（不猜）。
特殊机制（悬赏令、月相、种子、兽灵赐福…）用 OVERRIDES 手工补。

effect 结构：
  {"kind":"stat","stat":"AD","statKey":"attackDamage","value":12,"percent":true}
  {"kind":"dot","type":"burn","value":1,"percent":true}
  {"kind":"debuff","type":"wound","value":33,"percent":true}
  {"kind":"debuff","type":"shred_mr","value":30,"percent":true,"duration":4}
  {"kind":"gold","value":4}
  {"kind":"unit","name":"石皮树"}          # 获得/召唤的单位
  {"kind":"slot","scope":"shop","value":2} # 引燃商店栏位
  {"kind":"teamSize","value":12}
  {"kind":"execute","interval":3.5}
  {"kind":"resource","name":"魔女精粹","value":2}
  {"kind":"mechanic","key":"bounty","note":"悬赏令进度"}
"""
import re

STAT_ALIASES = {
    "AD": "attackDamage", "AP": "abilityPower", "HP": "health",
    "ARMOR": "armor", "MR": "magicResist", "AS": "attackSpeed",
    "DR": "damageReduction", "CRIT": "critChance", "MANA": "mana",
    "MANAREGEN": "manaRegen", "CRITMULT": "critDamage",
    "DA": "damageAmp", "SV": "omnivamp",
}

# 特殊机制：按 (trait key, 档位人数) 精确补（目前全部可由文本规则覆盖，保留扩展位）
OVERRIDES = {}


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse(text, trait_key=None, unit_count=None):
    """返回 effects 列表。"""
    t = (text or "").replace("<br>", " ").replace("|", "｜")
    out = []

    # 1) 「数值 + 【属性】」标记（最常见）：12%【AD】【AP】 / 25 【ARMOR】【MR】 / +3%【AS】
    for m in re.finditer(r"([+-]?\d+(?:\.\d+)?)\s*(%?)\s*((?:【[A-Z]{2,8}】\s*)+)", t):
        value, pct, tags = _num(m.group(1)), bool(m.group(2)), m.group(3)
        scope = "per_instance" if "每次" in t[max(0, m.start() - 12):m.start()] else None
        for tag in re.findall(r"【([A-Z]{2,8})】", tags):
            if tag == "DIST":
                continue
            eff = {"kind": "stat", "stat": tag, "statKey": STAT_ALIASES.get(tag, tag.lower()),
                   "value": value, "percent": pct}
            if scope:
                eff["scope"] = scope
            out.append(eff)

    for m in re.finditer(r"(\d+(?:\.\d+)?)%\s*灼烧", t):
        out.append({"kind": "dot", "type": "burn", "value": _num(m.group(1)), "percent": True})
    for m in re.finditer(r"(\d+(?:\.\d+)?)%\s*重伤", t):
        out.append({"kind": "debuff", "type": "wound", "value": _num(m.group(1)), "percent": True})
    for m in re.finditer(r"(\d+(?:\.\d+)?)%\s*魔抗击碎", t):
        out.append({"kind": "debuff", "type": "shred_mr", "value": _num(m.group(1)), "percent": True,
                    "duration": 4 if "持续4秒" in t else None})
    for m in re.finditer(r"(\d+(?:\.\d+)?)%\s*(?:护甲击碎|护甲削减)", t):
        out.append({"kind": "debuff", "type": "shred_armor", "value": _num(m.group(1)), "percent": True,
                    "duration": 4 if "持续4秒" in t else None})
    for m in re.finditer(r"引燃\s*(\d+)\s*个商店栏位", t):
        out.append({"kind": "slot", "scope": "shop", "value": int(m.group(1))})
    for m in re.finditer(r"(\d+)\s*最大队伍规模", t):
        out.append({"kind": "teamSize", "value": int(m.group(1))})
    for m in re.finditer(r"获得\s*(\d+)\s*金币", t):
        out.append({"kind": "gold", "value": int(m.group(1))})
    for m in re.finditer(r"(\d+(?:\.\d+)?)%\s*(额外伤害|伤害增幅)", t):
        out.append({"kind": "stat", "stat": "DA", "statKey": "damageAmp",
                    "value": _num(m.group(1)), "percent": True})
    for m in re.finditer(r"(\d+(?:\.\d+)?)%\s*伤害减免", t):
        out.append({"kind": "stat", "stat": "DR", "statKey": "damageReduction",
                    "value": _num(m.group(1)), "percent": True})
    for m in re.finditer(r"(\d+(?:\.\d+)?)%\s*暴击几率", t):
        out.append({"kind": "stat", "stat": "CRIT", "statKey": "critChance",
                    "value": _num(m.group(1)), "percent": True})
    for m in re.finditer(r"(\d+(?:\.\d+)?)%\s*最大生命值", t):
        out.append({"kind": "stat", "stat": "HP", "statKey": "health",
                    "value": _num(m.group(1)), "percent": True, "scope": "max"})
    for m in re.finditer(r"(\d+(?:\.\d+)?)%\s*(攻击速度|全能吸血|法术加成|物理加成)", t):
        label = m.group(2)
        key = {"攻击速度": ("AS", "attackSpeed"), "全能吸血": ("SV", "omnivamp"),
               "法术加成": ("AP", "abilityPower"), "物理加成": ("AD", "attackDamage")}[label]
        out.append({"kind": "stat", "stat": key[0], "statKey": key[1],
                    "value": _num(m.group(1)), "percent": True})
    for m in re.finditer(r"(\d+)\s*(?:护甲和魔法抗性|护甲和魔抗|护甲与魔抗)", t):
        out.append({"kind": "stat", "stat": "ARMOR", "statKey": "armor", "value": _num(m.group(1)), "percent": False})
        out.append({"kind": "stat", "stat": "MR", "statKey": "magicResist", "value": _num(m.group(1)), "percent": False})
    for m in re.finditer(r"(\d+)\s*【MANAREGEN】", t):
        out.append({"kind": "stat", "stat": "MANAREGEN", "statKey": "manaRegen",
                    "value": _num(m.group(1)), "percent": False})
    for m in re.finditer(r"(?:获得一棵|第二棵|以及|获得)\s*【([^】]+)】", t):
        out.append({"kind": "unit", "name": m.group(1)})
    if "处决" in t and not any(e["kind"] == "execute" for e in out):
        out.append({"kind": "execute", "interval": None})

    # 2) 资源 / 机制类
    for m in re.finditer(r"每次击杀\s*\+?(\d+)\s*【魔女精粹】", t):
        out.append({"kind": "resource", "name": "魔女精粹", "value": int(m.group(1)), "trigger": "kill"})
    for m in re.finditer(r"每次失败\s*\+?(\d+)\s*【魔女精粹】", t):
        out.append({"kind": "resource", "name": "魔女精粹", "value": int(m.group(1)), "trigger": "loss"})
    for m in re.finditer(r"植物升至\s*(\d+)\s*星", t):
        out.append({"kind": "mechanic", "key": "plant_star", "value": int(m.group(1))})
    for m in re.finditer(r"施加\s*(\d+(?:\.\d+)?)%\s*真实伤害", t):
        out.append({"kind": "dot", "type": "true", "value": _num(m.group(1)), "percent": True})
    if "流血" in t:
        if "触发" not in t:
            out.append({"kind": "dot", "type": "bleed", "note": "敌人流血，3 秒内受到额外真实伤害"})
    for m in re.finditer(r"(\d+(?:\.\d+)?)%\s*治疗强度", t):
        out.append({"kind": "stat", "stat": "HEALPOWER", "statKey": "healPower",
                    "value": _num(m.group(1)), "percent": True})
    if "种子" in t:
        out.append({"kind": "mechanic", "key": "seed_planting", "note": "获得种子，培育格子提供加成"})
    if "悬赏令" in t:
        out.append({"kind": "mechanic", "key": "bounty_contract", "note": "选择悬赏令，德莱文推进进度"})
    if "大元素使" in t:
        out.append({"kind": "mechanic", "key": "elementalist_convert", "note": "商店大元素使转换为同一羁绊"})
    if "兽灵赐福" in t:
        out.append({"kind": "mechanic", "key": "spirit_blessing", "note": "选择兽灵赐福"})
    if "宿敌" in t:
        out.append({"kind": "mechanic", "key": "rival_rule", "note": "宿敌收集参与击杀数，互相提供技能加成"})
    if "月相" in t:
        out.append({"kind": "mechanic", "key": "moon_phase", "note": "施放推进月相，改变团队增益"})
    if "配对" in t:
        out.append({"kind": "mechanic", "key": "partner_binding", "note": "把友军拖到塔里克身上配对"})
    if "召唤" in t and "强化" in t:
        out.append({"kind": "mechanic", "key": "summon_buff", "note": "强化召唤物"})
    m = re.search(r"每种效果加成提升\s*(\d+(?:\.\d+)?)%", t)
    if m:
        out.append({"kind": "stat", "stat": "SUMMON", "statKey": "summonEffect",
                    "value": _num(m.group(1)), "percent": True})
    if "阿尔法印记" in t:
        out.append({"kind": "mechanic", "key": "alpha_mark", "note": "为峡谷野怪提供独特霸符"})
    for m in re.finditer(r"(\d+)\s*个不包含.{0,20}商店栏位会被引燃", t):
        out.append({"kind": "slot", "scope": "shop", "value": int(m.group(1))})
    if "商店会被" in t and "占领" in t:
        m = re.search(r"每过\s*(\d+)\s*场对战", t)
        out.append({"kind": "mechanic", "key": "shop_occupy",
                    "value": int(m.group(1)) if m else None,
                    "note": "商店被峡谷野怪占领"})
    for m in re.finditer(r"(\d+)\s*法力(?!回复)", t):
        out.append({"kind": "stat", "stat": "MANA", "statKey": "mana", "value": _num(m.group(1)), "percent": False})
    for m in re.finditer(r"获得\s*(\d+)\s*永久最大生命值", t):
        out.append({"kind": "stat", "stat": "HP", "statKey": "health", "value": _num(m.group(1)),
                    "percent": False, "permanent": True})
    for m in re.finditer(r"占用\s*(\d+)\s*个弈子栏位", t):
        out.append({"kind": "slot", "scope": "board", "value": int(m.group(1))})
    for m in re.finditer(r"提供\s*\+?(\d+)\s*【([^】]+)】\s*羁绊", t):
        out.append({"kind": "counter", "trait": m.group(2), "value": int(m.group(1))})
    m = re.search(r"每\s*(\d+(?:\.\d+)?)\s*秒重复", t)
    if m:
        for e in out:
            if e["kind"] == "execute":
                e["interval"] = _num(m.group(1))

    for e in OVERRIDES.get((trait_key, unit_count), []):
        out.append(dict(e))

    # 去重（同 kind+type+value）
    seen, uniq = set(), []
    for e in out:
        k = (e["kind"], e.get("type"), e.get("stat"), e.get("value"), e.get("name"), e.get("key"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)
    return uniq
