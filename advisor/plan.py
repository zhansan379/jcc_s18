# -*- coding: utf-8 -*-
"""
把「局面 + 规则推荐 + 静态库」压成一份**说人话的作战计划**
=========================================================
界面只负责把这里产出的内容渲染出来，不再展示一堆复述截图的字段。

产出结构：
    {
      "title": "日蚀骑士韦鲁斯", "tier": "S", "meta": "均名 4.36 · 前四 53%",
      "reason": "为什么是这套（HTML）",
      "pivot": {...},                                # 变阵（最重要，单独强调）
      "augments": [ {name,tier,icon,tooltip} ],
      "board": [...],                                # 站位（含装备与角色）
      "others": [ {index,title,tier,score} ],
      "footer": {...},
    }

所有结论都是算出来的（阵容模板 / 装备配方 / 概率表 / 局内金币经验），不是模板硬编码。
LLM 的文案不进入这里——这里是可复现的规则结论。
"""
import html
import re

import databook

# 和 app.py 保持一致的配色
C_ACC = "#4a90e2"
C_OK = "#5bd67a"
C_WARN = "#e8b23a"
C_BAD = "#e2604a"
C_PUR = "#c89bf5"
C_MUT = "#8b93a3"
C_TX = "#dde4f0"
TIER_COLOR = {"S": "#ff6b6b", "A": "#c89bf5", "B": "#5bd67a", "C": "#7fb3ff", "D": "#8b93a3"}


def _e(s):
    return html.escape(str(s if s is not None else ""))


def hl(s, color=None, bold=True):
    """高亮一个词（会转义）"""
    return '<span style="color:%s;%s">%s</span>' % (
        color or C_TX, "font-weight:700;" if bold else "", _e(s))


_AUG_SUFFIX = re.compile(r"[ 　]*(I{1,3}|IV|V|\+|＋|＋I)$")


def _aug_base(name):
    """「纵深 II」→「纵深」，用于把同族符文合并展示"""
    return _AUG_SUFFIX.sub("", str(name or "")).strip()


TANK_ITEMS = {
    "石像鬼石板甲", "狂徒铠甲", "振奋盔甲", "日炎斗篷", "薄暮法袍", "冕卫",
    "圣盾使的誓约", "巨龙之爪", "棘刺背心", "离子火花", "泰坦的坚决", "水银",
    "大亨之铠", "黎明圣盾", "顽强不屈", "光盾徽章",
}


def _is_tank_build(build):
    """一套装备里有两件以上肉装 → 这个英雄是主坦"""
    return sum(1 for b in (build or []) if b in TANK_ITEMS) >= 2


MODE_RULES = [
    (r"4\s*/\s*5\s*级追三星", dict(kind="reroll", roll_level=5, start="3-1", push="5-1")),
    (r"6\s*(/\s*7)?\s*级追三星", dict(kind="reroll", roll_level=6, start="3-2", push="5-1")),
    (r"7\s*/\s*8\s*级追三星", dict(kind="reroll", roll_level=7, start="4-1", push="5-5")),
    (r"速升\s*8\s*级", dict(kind="level", roll_level=8, start="4-1", push="5-1")),
]
# 「3-1启动小D」「4-2拉8人口大D」这类句子里的开 D 回合
_START_RE = re.compile(r"(\d-\d)[^。；，]{0,14}?(启动|开D|开d|小D|大D|大d|小d)")
_LV_RE = re.compile(r"(\d)(?:\s*/\s*(\d))?\s*级追三星")


def _mode_of(tags, mid=""):
    """打法（reroll/level）+ 开 D 回合 + 目标等级

    目标等级：tags 里写死的「4/5级追三星」→ 5
    开 D 回合：站点 midDesc 里「3-1启动小D」→ 3-1；抽不到才用 MODE_RULES 的默认值
    """
    text = " ".join(tags or [])
    if "追三星" in text:
        kind = "reroll"
    elif "速升" in text:
        kind = "level"
    else:
        kind = "mixed"

    roll_lv = None
    m = _LV_RE.search(text)
    if m:
        roll_lv = int(m.group(2) or m.group(1))
    elif kind == "level":
        m = re.search(r"速升\s*(\d)", text) or re.search(r"(\d)\s*级", text)
        roll_lv = int(m.group(1)) if m else 8

    base = next((cfg for pat, cfg in MODE_RULES if re.search(pat, text)), None)
    hit = _START_RE.search(mid or "")
    start = hit.group(1) if hit else (base or {}).get("start")
    if roll_lv is None:
        roll_lv = (base or {}).get("roll_level")
    return dict(kind=kind,
                roll_level=roll_lv or 7,
                start=start or "4-1",
                push=(base or {}).get("push", "5-1"),
                start_src=("阵容中期说明" if hit else ("打法标签" if base else "默认")),
                tag=text)


# ------------------------------------------------------------------ 主类
class Plan:
    def __init__(self, res, sel=0):
        self.res = res or {}
        self.st = self.res.get("state") or {}
        self.cands = self.res.get("candidates") or []
        self.sel = max(0, min(sel, len(self.cands) - 1)) if self.cands else 0
        self.top = self.cands[self.sel] if self.cands else {}
        self.d = self.top.get("detail") or {}

        self.stage = self.st.get("阶段")
        self.level = self.st.get("等级")
        self.gold = self.st.get("金币")
        self.hp = (self.res.get("match") or {}).get("state", {}).get("hp")
        self.exp = self.st.get("经验")
        self.shop = [x for x in (self.st.get("商店") or []) if x]

        self.units = [u for u in (self.st.get("单位") or []) if u.get("name")]
        self.board = [u for u in self.units if u.get("area") == "board"]
        self.bench = [u for u in self.units if u.get("area") != "board"]

        self.comp_units = [u["name"] for u in (self.d.get("board") or [])]
        self.comp_cost = {u["name"]: u.get("cost") or databook.hero_cost(u["name"])
                          for u in (self.d.get("board") or [])}
        self.comp_set = set(self.comp_units)
        self.owned = {}
        for u in self.units:
            self.owned[u["name"]] = self.owned.get(u["name"], 0) + 1

        self.mode = _mode_of(self.top.get("tags"), self.d.get("mid") or "")

    # ------------------------------------------------------------- 工具
    def _owned_star(self, name):
        best = 0
        for u in self.units:
            if u["name"] == name:
                best = max(best, u.get("star") or 0)
        return best

    def pivot_section(self):
        cur = set(self.comp_set)
        best, best_score = None, -1
        for i, c in enumerate(self.cands):
            if i == self.sel:
                continue
            units = {u["name"] for u in ((c.get("detail") or {}).get("board") or [])}
            overlap = len(units & set(self.owned)) * 2 + len(units & cur)
            score = overlap + (c.get("score") or 0) * 3
            if score > best_score:
                best, best_score = c, score
        if not best:
            return {"html": '<span style="color:%s">数据里没有可替换的备选阵容。</span>' % C_MUT}

        bu = {u["name"] for u in ((best.get("detail") or {}).get("board") or [])}
        mine = set(self.owned)
        keep = sorted(mine & bu, key=lambda n: -databook.hero_cost(n))[:5]
        sell = sorted(mine - bu, key=lambda n: -databook.hero_cost(n))[:4]
        need = [n for n in (best.get("missing_sorted") or []) if n not in mine][:4]

        triggers = list(self.d.get("conditions") or [])
        miss_core = self.top.get("missing_core") or []
        if miss_core:
            triggers.insert(0, "%s 到 %s 还没二星" % (hl(self.mode["start"], C_ACC),
                                                      "、".join(hl(x, C_OK) for x in miss_core[:2])))

        refund = 0
        for n in sell:
            st = self._owned_star(n)
            refund += databook.hero_cost(n) * (3 if st >= 2 else 1)

        rows = []
        trig = []
        for t in (self.d.get("conditions") or [])[:2]:
            trig.append('<span style="color:%s">%s</span>' % (C_ACC, _e(t)))
        miss_core = self.top.get("missing_core") or []
        if miss_core:
            trig.insert(0, "到 %s 还凑不齐 %s"
                        % (hl(self.mode["start"], C_ACC),
                           "、".join(hl(x, C_OK) for x in miss_core[:2])))
        if trig:
            rows.append('<span style="color:%s">什么时候转：</span>%s'
                        % (C_MUT, "；".join(trig[:2])))
        rows.append('<span style="color:%s">转去：</span><b style="color:%s">%s</b>'
                    '　<span style="color:%s">%s 级 · 均名 %s · 前四 %s%%</span>'
                    % (C_MUT, C_TX, _e(best.get("title")), C_MUT, best.get("tier") or "?",
                       (best.get("stats") or {}).get("avgPlace"),
                       (best.get("stats") or {}).get("top4Rate")))
        if keep:
            rows.append('<span style="color:%s">留着：</span>%s　<span style="color:%s">'
                        '（两套都用，不用重买）</span>'
                        % (C_MUT, "、".join(hl(x, C_OK) for x in keep), C_MUT))
        if sell:
            rows.append('<span style="color:%s">到时候卖：</span>%s　<span style="color:%s">'
                        '（回收约 %d 金）</span>'
                        % (C_MUT, "、".join(hl(x, C_BAD) for x in sell), C_MUT, refund))
        if need:
            rows.append('<span style="color:%s">去找：</span>%s'
                        % (C_MUT, "、".join('%s<span style="color:%s;font-size:11px">%d费</span>'
                                           % (hl(n, C_WARN), C_MUT, databook.hero_cost(n))
                                           for n in need)))
        return {"head": "变阵（最该记住的一条）", "html": "<br>".join(rows),
                "to": best.get("title"), "idx": self.cands.index(best)}

    # ------------------------------------------------------------- 符文 / 装备
    def augments(self, limit=6):
        out, seen = [], set()
        why = {}
        for a in ((self.res.get("coach") or {}).get("data") or {}).get("augments") or []:
            why[a.get("name")] = a.get("why")
        for a in (self.res.get("augment_pool") or []):
            base = _aug_base(a["name"])
            if base in seen:                    # 「纵深 I/II/III」这类同族只留一个
                continue
            seen.add(base)
            tip = ["%s ｜ %s级" % (a["name"], a.get("tier") or "?")]
            if a.get("typeZh"):
                tip.append("/".join(a["typeZh"]))
            if a.get("desc"):
                tip.append(a["desc"])
            if a.get("hit"):
                tip.append("契合：%s" % "、".join(a["hit"]))
            if why.get(a["name"]):
                tip.append("教练：%s" % why[a["name"]])
            out.append({"name": a["name"], "tier": a.get("tier"),
                        "icon": databook.icon_augment(a["name"]),
                        "tooltip": "\n".join(tip)})
            if len(out) >= limit:
                break
        return out

    def _role_map(self):
        """主C / 主坦 / 副C"""
        main = self.d.get("main") or self.top.get("main")
        out = {}
        if main:
            out[main] = "主C"
        plans = self.d.get("equip_plans") or []
        tank = next((x["hero"] for x in plans
                     if x["hero"] != main and _is_tank_build(x["builds"][0])), None)
        if tank:
            out[tank] = "主坦"
        for x in plans:
            out.setdefault(x["hero"], "副C")
        return out

    # ------------------------------------------------------------- 为什么是这套
    def reason_text(self):
        """把「为什么推荐这套」写成一句人话，只列真的成立的理由"""
        items = []
        roles = self._role_map()

        # 1) 手上已有的牌（命中最多的一条）
        matched = self.top.get("matched_units") or []
        if matched:
            def fmt(n):
                r = roles.get(n)
                return hl(n, C_OK) + ("（%s）" % r if r else "")
            txt = "你手上已经有 " + "、".join(fmt(x) for x in matched[:4])
            items.append((3.0 + len(matched) * 0.2, txt))

        # 2) 强化符文契合
        for h in (self.top.get("augment_hits") or [])[:1]:
            if (h.get("fit") or 0) >= 0.8:
                style = "慢 D" if self.mode["kind"] == "reroll" else "运营"
                items.append((2.6, "%s 提供免费刷新，正好配这套 %s 打法"
                              % (hl(h["name"], C_PUR), style)))

        # 3) 手上散件能直接合它的核心装
        comps = list(dict.fromkeys(self.d.get("components") or []))
        if comps:
            for pl in self.d.get("equip_plans") or []:
                ordered = databook.rank_build(pl["hero"], self.top.get("id"), pl["builds"][0])
                if not ordered:
                    continue
                ok, used = databook.craft_from(comps, ordered[0])
                if ok:
                    items.append((2.4, "手上的 %s 能直接合出它的 %s（给 %s）"
                                  % (hl("+".join(used), C_WARN),
                                     hl(ordered[0], C_OK), hl(pl["hero"], C_OK))))
                    break

        # 4) 这一刷商店就有体系牌
        shop_hit = list(dict.fromkeys([x for x in self.shop if x in self.comp_set]))
        if shop_hit:
            items.append((2.2, "这一刷里就有 %s，拿了不亏"
                          % "、".join(hl(x, C_WARN) for x in shop_hit[:2])))

        # 5) 等级节奏对得上
        lv = int(self.level or 4)
        roll_lv = int(self.mode["roll_level"] or 7)
        if self.mode["kind"] == "reroll":
            if lv == roll_lv:
                items.append((2.0, "这套要 %s 级追三星，你现在正好 %d 级" % (hl(roll_lv, C_ACC), lv)))
            elif lv < roll_lv:
                items.append((1.6, "这套要 %s 级追三星，你现在 %d 级，还差 %d 级"
                              % (hl(roll_lv, C_ACC), lv, roll_lv - lv)))

        # 6) 站点数据兜底
        stats = self.top.get("stats") or {}
        if stats.get("top4Rate"):
            items.append((1.2, "站点 %s 级，前四 %s%%、均名 %.2f"
                          % (hl(self.top.get("tier") or "?", TIER_COLOR.get(self.top.get("tier") or "", C_MUT)),
                             stats.get("top4Rate"), stats.get("avgPlace") or 0)))

        items.sort(key=lambda x: -x[0])
        picks = [t for _, t in items[:3]]
        if not picks:
            return ""
        return "为什么是这套：" + "；".join(picks) + "。"

    # ------------------------------------------------------------- 其它
    def footer(self):
        st = self.st
        src = st.get("_来源") or {}
        tips = list((self.res.get("match") or {}).get("warnings") or [])
        tips += list(st.get("_告警") or [])
        return {"timings": self.res.get("timings_text") or "",
                "source": "；".join("%s=%s" % (k, v) for k, v in src.items()),
                "warnings": tips[:4]}


def build(res, sel=0):
    p = Plan(res, sel)
    if not p.cands:
        return {"title": "没有可用阵容", "pivot": {}, "augments": [], "board": [],
                "others": [], "footer": {}}
    others = [{"index": i, "title": c.get("title"), "tier": c.get("tier"),
               "score": c.get("score")}
              for i, c in enumerate(p.cands)]
    stats = p.top.get("stats") or {}

    # 站位上的每个单位带上「按重要性排好的装备」和角色（主C/副C/主坦）
    board = []
    role_map = p._role_map()
    for u in p.d.get("board") or []:
        eq = [e for e in (u.get("equips") or []) if e]
        ranked = databook.rank_build(u["name"], p.top.get("id"), eq) if eq else []
        ranked = ranked or eq
        board.append(dict(u, equips=ranked, equip_core=(ranked[0] if ranked else None),
                          role=role_map.get(u["name"])))

    return {
        "title": p.top.get("title"),
        "tier": p.top.get("tier"),
        "meta": "均名 %.2f · 前四 %s%% · 登场 %s%%" % (stats.get("avgPlace") or 0,
                                                      stats.get("top4Rate"), stats.get("playRate")),
        "stage": p.stage, "level": p.level, "gold": p.gold,
        "reason": p.reason_text(),
        "pivot": p.pivot_section(),
        "augments": p.augments(),
        "board": board,
        "others": others,
        "footer": p.footer(),
        "main": p.d.get("main") or p.top.get("main"),
        "code": p.d.get("code") or "",
    }
