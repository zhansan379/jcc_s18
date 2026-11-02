"""强化符文（站点数据库里叫「强化果实」，hexs）入库 + 评级。

结论先行：站点的「强化符文」tab（#augment）和「强化评级」页是同一套数据 —— hexs18，
游戏内/评级页口语叫「强化果实」。与「仙灵」（charms，181 条）是两套不同的东西。

数据来源：
  - 条目与描述：raw/site-data-cn.json#hexs18（银 71 / 金 114 / 棱彩 71）
  - 评级：GET https://api.datatft.com/augment-tier/config?platform=jcc&season=18
          返回「评级码」，只有 2 字符编号，名称要靠 hexs18 对齐
  - S/A/B/C/D 归属：raw/augment_tier/dom.tsv（渲染后的页面导出：rarity/tier/名称/图标）

用法：python tools/fetch_augment_tier.py
"""
import json
import os
import re
import ssl
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "data", "s18db")
RAW = os.path.join(DST, "raw", "augment_tier")
API = "https://api.datatft.com/augment-tier/config?platform=jcc&season=18"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
CTX = ssl.create_default_context()

RARITY_ZH = {"silver": "白银", "gold": "黄金", "prismatic": "棱彩"}
TIER_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
TYPE_ZH = {1: "经济", 2: "战力", 3: "装备", 4: "羁绊", 5: "专属", 6: "其他"}


def fetch_config():
    os.makedirs(RAW, exist_ok=True)
    path = os.path.join(RAW, "config_jcc.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))["data"]
    req = urllib.request.Request(API, headers={"User-Agent": UA, "Origin": "https://jcc.datatft.com"})
    with urllib.request.urlopen(req, timeout=45, context=CTX) as r:
        data = json.loads(r.read().decode("utf-8"))
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return data["data"]


def icon_key(src):
    base = src.rsplit("/", 1)[-1]
    base = re.sub(r"\.(png|jpg|jpeg)$", "", base, flags=re.I)
    base = re.sub(r"\.TFT_Set\d+$", "", base, flags=re.I)
    return re.sub(r"_\d_?$", "", base)


def build_augments():
    data = json.load(open(os.path.join(DST, "raw", "site-data-cn.json"), encoding="utf-8"))
    groups = data["hexs18"]
    out = []
    for rarity, group in zip(["silver", "gold", "prismatic"], groups):
        for h in group:
            key = re.sub(r"_\d_?$", "", h.get("img") or "")
            out.append({
                "hexId": h.get("hexId"),
                "code": h.get("code"),
                "key": key,
                "name": h.get("name"),
                "rarity": rarity,
                "rarityZh": RARITY_ZH[rarity],
                "rounds": h.get("round") or [],
                "type": h.get("type") or [],
                "typeZh": [TYPE_ZH.get(t, t) for t in (h.get("type") or [])],
                "desc": h.get("desc"),
                "img": h.get("img"),
                "tier": None,
            })
    return out


def main():
    cfg = fetch_config()
    augments = build_augments()
    by_rarity_name = {}
    for a in augments:
        by_rarity_name.setdefault((a["rarity"], a["name"]), []).append(a)

    rows = [l.split("\t") for l in open(os.path.join(RAW, "dom.tsv"), encoding="utf-8")
            .read().splitlines() if l.strip()]

    levels, unmatched, used = [], [], set()
    for rarity, tier, name, icon in rows:
        k = icon_key(icon)
        pool = [a for a in by_rarity_name.get((rarity, name), [])]
        cand = None
        if len(pool) == 1:
            cand = pool[0]
        elif len(pool) > 1:
            # 同名多单位（如图标相同）时按图标 key 和「未使用」消歧
            cand = next((h for h in pool if h["key"] == k and h["hexId"] not in used), None) \
                or next((h for h in pool if h["hexId"] not in used), None) \
                or next((h for h in pool if h["key"] == k), pool[0])
        if cand is None:
            cand = next((h for h in augments if h["rarity"] == rarity and h["key"] == k), None)
        if cand is None:
            unmatched.append(name)
            levels.append({"name": name, "tier": tier, "rarity": rarity,
                           "rarityZh": RARITY_ZH.get(rarity), "hexId": None})
            continue
        used.add(cand["hexId"])
        cand["tier"] = tier
        levels.append({
            "name": name, "tier": tier, "rarity": rarity,
            "rarityZh": RARITY_ZH.get(rarity),
            "hexId": cand["hexId"], "key": cand["key"],
            "rounds": cand["rounds"], "typeZh": cand["typeZh"], "desc": cand["desc"],
        })

    levels.sort(key=lambda e: (list(RARITY_ZH).index(e["rarity"]), TIER_ORDER.get(e["tier"], 9), e["name"]))
    meta = {
        "source": "https://jcc.datatft.com/augment/tier（评级 api.datatft.com/augment-tier/config）",
        "platform": "jcc", "season": cfg.get("season"),
        "configVersion": cfg.get("version"),
        "ratingNote": cfg.get("ratingTextZh"),
        "authors": [{"name": a.get("nameZh"), "weight": a.get("weight"), "enabled": a.get("enabled")}
                    for a in cfg.get("authors", [])],
        "extracted": "2026-11-02",
    }

    json.dump({"meta": dict(meta, count=len(augments),
                            note="强化符文，即站点「强化符文」tab；评级页口语称「强化果实」。与「仙灵」(charms) 是两套数据。"),
               "augments": augments},
              open(os.path.join(DST, "augments.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    json.dump({"meta": dict(meta, count=len(levels)),
               "levels": levels},
              open(os.path.join(DST, "augments_tier.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    from collections import Counter
    print("augments", len(augments), "| rated", len(levels), "| unmatched", len(unmatched), unmatched[:5])
    print("by rarity", Counter(a["rarity"] for a in augments))
    print("by tier", Counter(e["tier"] for e in levels))


if __name__ == "__main__":
    main()
