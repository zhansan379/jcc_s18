"""抓取金铲铲大数据（jcc.datatft.com）的阵容榜单与阵容详情。

数据接口（已实测，无需登录）：
  POST https://api.datatft.com/team/rank          body {"season":"18"}
  POST https://api.datatft.com/team/strategy      body {"id": <阵容id>}
  POST https://api.datatft.com/team/strategy/extra body {"id": <阵容id>}

详情里的 teamUrl 是自定义编码的棋盘，按站点前端 decrypt 逻辑还原出
每个棋子的格子位置(index) / 星级 / 装备，以及强化果实(hexs)。

用法：
  python tools/fetch_jcc_comps.py            # 抓取并写入 data/s18db/
  python tools/fetch_jcc_comps.py --no-tips  # 跳过社区 tips（省一半请求）
"""
import argparse
import json
import os
import re
import ssl
import time
import urllib.request
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "data", "s18db")
RAW = os.path.join(DST, "raw", "jcc_comps")
API = "https://api.datatft.com"
SEASON = "18"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
CTX = ssl.create_default_context()

MAPCHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!<>."
MAP = {c: i for i, c in enumerate(MAPCHARS)}

# 站点把无 code 的特殊单位按顺序分配 zA,zB,...；S18 的 extras 表见 staticAssets：
# [9977, 9978, 999001, 999002, 999003, 999004] → 目标假人/魔像/未命名占位
EXTRA_IDS = {"zA": 9977, "zB": 9978, "zC": 999001, "zD": 999002, "zE": 999003, "zF": 999004}
EXTRA_NAMES = {9977: "目标假人", 9978: "魔像"}


def post(path, payload, tries=6):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                API + path,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "User-Agent": UA,
                         "Origin": "https://jcc.datatft.com",
                         "Referer": "https://jcc.datatft.com/"},
                method="POST")
            with urllib.request.urlopen(req, timeout=45, context=CTX) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


def decode_team(url, hero_map, equip_map):
    """还原 teamUrl 编码的棋盘。index 为 0~27 的格子号（row = index // 7, col = index % 7）。"""
    if not url:
        return {"units": [], "extras": [], "hexs": [], "error": None}
    hero_map = dict(hero_map)
    for code, hid in EXTRA_IDS.items():
        hero_map.setdefault(code, hid)
    e = re.sub(r"^https://(www|jcc)\.datatft\.com/(team-builder|simulator)/", "", url, flags=re.I)
    e = e.replace("%7C", "|").replace(" ", "")
    if e.endswith("."):
        e = e[:-1]
    m = re.search(r"s(\d{1,2})$", e)
    if m:
        e = e[: -(len(m.group(1)) + 1)]
    e = unquote(e)
    if not e:
        return {"units": [], "hexs": [], "error": None}

    slots = [None] * 56
    hexs, err, i = [], None, 0
    while i < len(e):
        if e[i] == "|":
            i += 1
            while i < len(e):
                hexs.append(e[i:i + 2])
                i += 2
            break
        mc = e[i]
        i += 1
        if mc not in MAP:
            err = "map char %r" % mc
            break
        idx = MAP[mc]
        hc = e[i:i + 2]
        i += 2
        if hc not in hero_map:
            err = "hero code %r" % hc
            break
        u = {"id": hero_map[hc], "index": idx, "row": idx // 7, "col": idx % 7}
        if i < len(e) and e[i].isdigit():
            n = int(e[i]); i += 1
            eqs = []
            for _ in range(n):
                ec = e[i:i + 2]; i += 2
                if ec in equip_map:
                    eqs.append(equip_map[ec])
            u["equips"] = eqs
        if i < len(e) and e[i] == "~":
            i += 1
            n = int(e[i]); i += 1
            i += 3 * n
        if i < len(e) and e[i] == "*":
            i += 1
            u["stars"] = int(e[i]); i += 1
        if i < len(e) and e[i] == "_":
            i += 1
            u["replaceId"] = hero_map.get(e[i:i + 2]); i += 2
        while i < len(e) and e[i] == "^":
            i += 2
        if i < len(e) and e[i] == "-":
            i += 1
            i += 1
            u["isMain"] = True
        slots[idx] = u
    return {"units": [s for s in slots if s and s["id"] < 999000],
            "extras": [s for s in slots if s and s["id"] >= 999000],
            "hexs": hexs, "error": err}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-tips", action="store_true", help="不抓 /team/strategy/extra")
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    pack = json.load(open(os.path.join(DST, "raw", "h5-data-cn-18.json"), encoding="utf-8"))
    heroes = {h["chessId"]: h for h in pack["heros18"]}
    hero_code = {h["code"]: h["chessId"] for h in pack["heros18"]}
    equip_code = {e["code"]: e["equipId"] for e in pack["equips18"]}
    equip_name = {e["equipId"]: (e.get("jccname") or e.get("name")) for e in pack["equips18"]}
    hero_name = {h["chessId"]: h["displayName"] for h in pack["heros18"]}

    rank_path = os.path.join(RAW, "rank.json")
    if os.path.exists(rank_path):
        rank = json.load(open(rank_path, encoding="utf-8"))
    else:
        rank = post("/team/rank", {"season": SEASON})
        json.dump(rank, open(rank_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    data = rank["data"]
    lst = data["list"]

    # /team/list：同一批阵容，但带 score / tftCode / strategyId，以及全局样本量 count
    tl_path = os.path.join(RAW, "team_list.json")
    if os.path.exists(tl_path):
        tl = json.load(open(tl_path, encoding="utf-8"))
    else:
        tl = post("/team/list", {"season": SEASON})
        json.dump(tl, open(tl_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    tl_data = (tl or {}).get("data") or {}
    team_list = {c["id"]: c for c in (tl_data.get("list") or [])}
    sample_count = int(tl_data.get("count") or 0)
    print("rank comps:", len(lst), "version:", data.get("version"),
          "update:", data.get("updateTime"), "team_list:", len(team_list), "sample:", sample_count)

    comps = []
    for n, item in enumerate(lst, 1):
        cid = item["id"]
        sp = os.path.join(RAW, "strategy_%s.json" % cid)
        if os.path.exists(sp):
            strat = json.load(open(sp, encoding="utf-8"))
        else:
            strat = post("/team/strategy", {"id": cid})
            json.dump(strat, open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            time.sleep(0.4)
        s = (strat or {}).get("data") or {}
        if not s or not s.get("teamUrl"):
            print(" ", n, cid, "skip (no strategy data)")
            continue

        tips = []
        if not args.no_tips:
            ep = os.path.join(RAW, "extra_%s.json" % cid)
            if os.path.exists(ep):
                extra = json.load(open(ep, encoding="utf-8"))
            else:
                extra = post("/team/strategy/extra", {"id": cid})
                json.dump(extra, open(ep, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                time.sleep(0.4)
            tips = ((extra or {}).get("data") or {}).get("tips") or []

        board = decode_team(s.get("teamUrl"), hero_code, equip_code)
        early = decode_team(s.get("earlyTeamUrl"), hero_code, equip_code)

        def unit_out(u):
            return {
                "id": u["id"],
                "name": hero_name.get(u["id"]) or str(u["id"]),
                "slot": u["index"], "row": u["row"], "col": u["col"],
                "stars": u.get("stars"),
                "isMain": bool(u.get("isMain")),
                "equips": [{"id": e, "name": equip_name.get(e, str(e))} for e in u.get("equips", [])],
            }

        comps.append({
            "id": cid,
            "tier": item.get("tier"),
            "title": item.get("title") or s.get("title"),
            "titleApi": item.get("titleApi") or s.get("titleApi"),
            "mainHeroId": item.get("heroId"),
            "mainHeroName": hero_name.get(int(item["heroId"])) if str(item.get("heroId", "")).isdigit() else None,
            "emblemTrait": item.get("equipId"),
            "stats": {
                "playRate": s.get("playRate"),
                "winRate": s.get("won"),
                "top4Rate": s.get("top4"),
                "avgPlace": s.get("place"),
            },
            "difficulty": s.get("difficulty"),
            "tags": s.get("tags") or [],
            "core": s.get("core"),
            "open": s.get("open"),
            "earlyDesc": s.get("earlyDesc"),
            "midDesc": s.get("midDesc"),
            "finalDesc": s.get("finalDesc"),
            "board": {"units": [unit_out(u) for u in sorted(board["units"], key=lambda x: x["index"])],
                      "extras": [{"id": e["id"], "slot": e["index"]} for e in board["extras"]],
                      "hexs": board["hexs"], "error": board["error"]},
            "earlyBoard": {"units": [unit_out(u) for u in sorted(early["units"], key=lambda x: x["index"])],
                           "hexs": early["hexs"], "error": early["error"]},
            "equipOptions": s.get("equips") or [],
            "jccCode": s.get("jccCode"),
            "score": (team_list.get(cid) or {}).get("score"),
            "tftCode": (team_list.get(cid) or {}).get("tftCode"),
            "strategyId": (team_list.get(cid) or {}).get("strategyId"),
            "conditions": s.get("conditions"),
            "updateTime": s.get("updateTime"),
            "tips": [{"desc": t.get("description"), "type": t.get("type"),
                      "tags": t.get("type2"), "author": t.get("author"),
                      "like": t.get("like"), "time": t.get("updateTime")} for t in tips],
        })
        print(" ", n, cid, item.get("tier"), comps[-1]["title"], "units:", len(comps[-1]["board"]["units"]),
              "tips:", len(tips), "err:", board["error"])

    order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
    comps.sort(key=lambda c: (order.get(c["tier"], 9), -(c["stats"]["top4Rate"] or 0)))

    out = {
        "meta": {
            "source": "https://api.datatft.com/team/rank + /team/strategy（金铲铲大数据）",
            "page": "https://jcc.datatft.com/comp/rank",
            "season": SEASON,
            "version": data.get("version"),
            "updateTime": data.get("updateTime"),
            "compCount": len(comps),
            "sampleCount": sample_count,
            "sampleNote": "站点 /team/list 返回的 count，为统计窗口内的对局总数；每套阵容的估算场次 = playRate × sampleCount。",
            "extracted": time.strftime("%Y-%m-%d"),
            "boardNote": "board.units[].slot 为 0~27 的格子编号，row = slot // 7，col = slot % 7（玩家半场 4 行 × 7 列）。",
        },
        "comps": comps,
    }
    json.dump(out, open(os.path.join(DST, "comps.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    summary = [{
        "id": c["id"], "tier": c["tier"], "title": c["title"],
        "mainHero": c["mainHeroName"], "emblemTrait": c["emblemTrait"],
        "units": [u["name"] for u in c["board"]["units"]],
        "avgPlace": round(c["stats"]["avgPlace"], 2) if c["stats"]["avgPlace"] is not None else None,
        "top4": c["stats"]["top4Rate"], "win": c["stats"]["winRate"], "pick": c["stats"]["playRate"],
        "difficulty": c["difficulty"], "tags": c["tags"],
    } for c in comps]
    json.dump({"meta": out["meta"], "comps": summary},
              open(os.path.join(DST, "comps_summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("saved", len(comps), "comps")


if __name__ == "__main__":
    main()
