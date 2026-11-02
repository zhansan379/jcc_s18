# -*- coding: utf-8 -*-
"""
经济与行动建议
==============
只做「根据阶段/等级/金币/血量给出候选动作」，不承诺唯一正确。

阈值来自 config/strategy_rules.json（可调，不是 s18db 数据事实）：
  level_timing / hp_danger / roll_gold / interest_cap / min_named_ratio
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_RULES = os.path.join(ROOT, "config", "strategy_rules.json")


def load_rules(path=None):
    path = path or DEFAULT_RULES
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _stage_key(stage):
    m = re.search(r"(\d+)\s*-\s*(\d+)", str(stage or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def target_level(stage, rules):
    key = _stage_key(stage)
    if key is None:
        return None
    best = None
    for row in rules.get("level_timing") or []:
        k = _stage_key(row.get("stage"))
        if k is not None and k <= key:
            best = row.get("level")
    return best


def _add(actions, kind, priority, why, target=None):
    item = {"type": kind, "priority": priority, "why": why}
    if target:
        item["target"] = target
    for a in actions:
        if a["type"] == kind and a.get("target") == target:
            return
    actions.append(item)


def make_actions(state, match, rules):
    """state: scan JSON；match: comp_match.recommend() 的返回；rules: 配置。"""
    actions = []
    level = state.get("等级")
    gold = state.get("金币")
    hp = state.get("我的血量")
    stage = state.get("阶段")
    named_ratio = (match.get("state") or {}).get("named_ratio", 0.0)
    top = (match.get("candidates") or [None])[0]

    target = target_level(stage, rules)
    danger = rules.get("hp_danger", 35)
    roll_gold = rules.get("roll_gold", 30)
    min_named = rules.get("min_named_ratio", 0.6)

    if hp is not None and hp < danger:
        _add(actions, "stabilize", 1,
             "血量 %s 低于 %s，优先稳住血量/搜牌，不要盲目存钱" % (hp, danger))

    if isinstance(level, int) and isinstance(target, int) and level < target:
        _add(actions, "level", 1,
             "阶段 %s 目标等级 %s，当前 %s；先补人口" % (stage, target, level))

    if top and named_ratio >= min_named:
        missing_core = top.get("missing_core") or []
        shop_hits = top.get("shop_hits") or []
        for name in shop_hits:
            is_core = name in (top.get("core_units") or [])
            _add(actions, "buy", 1 if is_core else 2,
                 "商店有%s%s" % (name, "，是候选阵容核心" if is_core else "，可补候选阵容"), name)

        if (isinstance(gold, int) and gold >= roll_gold
                and isinstance(level, int) and isinstance(target, int)
                and level >= target and missing_core):
            why = ("金币 %s≥%s，候选阵容还缺核心 %s；可在 Lv%s 搜牌"
                   % (gold, roll_gold, "、".join(missing_core[:3]), level))
            augs = [h["name"] for h in top.get("augment_hits") or []]
            if augs:
                why += "；%s 适合慢D，优先用免费刷新" % "、".join(augs)
            _add(actions, "roll", 2, why)

    if isinstance(gold, int) and (hp is None or hp >= danger):
        interest = min(gold // 10, rules.get("interest_cap", 5))
        if gold >= 10:
            why = "金币 %s，当前利息 +%s；血量安全时优先存钱" % (gold, interest)
        else:
            why = "金币 %s，先攒到 10 吃利息" % gold
        augs = [h["name"] for h in (top or {}).get("augment_hits") or []]
        if augs and (top or {}).get("style") == "reroll":
            why += "；%s 提供免费刷新，适合慢D" % "、".join(augs)
        _add(actions, "save", 3, why)

    actions.sort(key=lambda a: (a["priority"], a["type"], a.get("target") or ""))
    return actions
