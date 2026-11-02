"""抓取 dataj.cc 的强化符文资料：图鉴（图标/名称） + 战绩统计。

数据源：
  1. 图鉴/全量：GET https://www.dataj.cc/api/web/gamedata?setId=18   → data.hex[268]
     字段：id, name, descText, icon(img.dataj.cc), level(1~3), setId, version
  2. 统计：https://www.dataj.cc/hex 页面 RSC 里的 initialRows[235]
     字段：hexId, name, icon, sampleCount, playRate, avgPlacement, top4Rate, topRate, rounds, roundStats

输出：
  data/s18db/augment_stats.json            统计（按我们的 augment hexId 对齐）
  data/s18db/images/augments/<hexId>.png    图标（以我们的 key 命名，256 个目标）

用法：
  python tools/fetch_dataj_hex.py            # 抓取 + 下载缺失图标
  python tools/fetch_dataj_hex.py --no-images
"""
import argparse
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "data", "s18db")
RAW = os.path.join(DST, "raw")
IMG_DIR = os.path.join(DST, "images", "augments")

STATS_PAGE = "https://www.dataj.cc/hex"
CATALOG_API = "https://www.dataj.cc/api/web/gamedata?setId=18"
GTIMG = "https://game.gtimg.cn/images/lol/act/jkzlk/gamedata/hex/{name}.png"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/131.0 Safari/537.36")
CTX = ssl.create_default_context()

# 两站译名不一致、且图标也不同名的情况
ALIASES = {
    "一一二三": "一，二，三",
    "灵活": "灵活摇摆",
}
# dataj 叫法 → 我们的叫法（用于统计行匹配）
REV_ALIASES = {
    "纹章树": "羁绊树",
    "纹章树+": "羁绊树+",
    "嘀嘀街区加强版": "DD街区+",
    "秘法帮派": "窃贼帮派",
    "秘法帮派 II": "窃贼帮派 II",
    "秘法帮派 II+": "窃贼帮派 II+",
    "秘法帮派 II++": "窃贼帮派 II++",
    "一，二，三": "一一二三",
    "灵活摇摆": "灵活",
    "嘀嘀街区": "DD街区",
    "嘀个痛快！ I": "D个痛快！",
    "金鳞精粹": "金鳞精萃",
    "8级嘀干的传说": "8级D干的传说",
    "核心位的觉悟": "C位的觉悟",
    "拼盘天梯": "羁绊天梯",
    "并肩作战 I": "联合作战",
}


def http_get(url, tries=5, binary=False):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.dataj.cc/"})
            with urllib.request.urlopen(req, timeout=45, context=CTX) as r:
                data = r.read()
                return data if binary else data.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.2 * (i + 1))
    raise last


def norm(s):
    s = (s or "").lower()
    for a, b in [("！", ""), ("，", ""), ("Ⅲ", "iii"), ("Ⅱ", "ii"), ("Ⅰ", "i"),
                 (" ", ""), (",", ""), ("·", "")]:
        s = s.replace(a, b)
    return s


def slug(v):
    """图标名规范化：去扩展名/DA 前缀/_数字后缀/.TFT_SetNN，只留字母数字。"""
    s = (v or "").rsplit("/", 1)[-1]
    s = re.sub(r"\.(png|webp|jpg)$", "", s, flags=re.I)
    s = re.sub(r"\.TFT_Set\d+$", "", s, flags=re.I)
    s = re.sub(r"[^a-z0-9]", "", s.lower())
    s = re.sub(r"^(da18|da)(?=[a-z])", "", s)
    return re.sub(r"\d+$", "", s)


def parse_stats(html):
    parts = []
    for s in re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html, re.S):
        try:
            parts.append(json.loads(s))
        except ValueError:
            continue
    flight = "".join(parts)
    i = flight.find('"initialRows":')
    if i < 0:
        raise SystemExit("没找到 initialRows，/hex 页面结构可能变了")
    start = flight.index("[", i)
    depth, instr, esc = 0, False, False
    for j in range(start, len(flight)):
        c = flight[j]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c in "[{":
                depth += 1
            elif c in "]}":
                depth -= 1
                if depth == 0:
                    return json.loads(flight[start:j + 1])


def fetch_cached(url, path, binary=False):
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return open(path, "rb").read() if binary else open(path, encoding="utf-8").read()
    data = http_get(url, binary=binary)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if binary else "w", encoding=None if binary else "utf-8") as f:
        f.write(data)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-images", action="store_true")
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    catalog = json.loads(fetch_cached(CATALOG_API, os.path.join(RAW, "dataj_gamedata18.json")))
    hexes = catalog["data"]["hex"]
    html = fetch_cached(STATS_PAGE, os.path.join(RAW, "dataj_hex.html"))
    rows = parse_stats(html)

    ours = json.load(open(os.path.join(DST, "augments.json"), encoding="utf-8"))["augments"]

    by_name, by_slug = {}, {}
    for x in hexes:
        by_name.setdefault(norm(x["name"]), []).append(x)
        by_slug.setdefault(slug(x["icon"]), []).append(x)

    mapped, how = {}, {}
    for a in ours:
        cand = by_name.get(norm(a["name"])) or by_name.get(norm(ALIASES.get(a["name"], "")))
        if cand:
            mapped[a["hexId"]] = cand[0]; how[a["hexId"]] = "name"; continue
        s = slug(a.get("img") or "")
        cand = by_slug.get(s)
        if cand:
            mapped[a["hexId"]] = cand[0]; how[a["hexId"]] = "slug"; continue
        mapped[a["hexId"]] = None; how[a["hexId"]] = "none"

    # 统计行：按 name（+别名）+ 图标 slug 分配到我们的条目，避免同名多单位被合并
    used = set()
    stats_by_ours = {}
    stats_unmatched = []

    def match_row(name, icon):
        n = norm(name)
        cands = [a for a in ours if norm(a["name"]) == n]
        if not cands:
            alias = REV_ALIASES.get(name) or ALIASES.get(name)
            if alias:
                cands = [a for a in ours if norm(a["name"]) == norm(alias)]
        if not cands:
            return None
        s = slug(icon)
        for a in cands:
            if s and slug(a.get("img") or "") == s:
                return a
        return cands[0]

    for r in rows:
        a = match_row(r["name"], r.get("icon") or "")
        if not a:
            stats_unmatched.append(r["name"])
            continue
        used.add(a["hexId"])
        stats_by_ours.setdefault(a["hexId"], []).append(r)

    # 图标
    os.makedirs(IMG_DIR, exist_ok=True)
    icon_ok, icon_fail = 0, []
    if not args.no_images:
        for a in ours:
            key = a["hexId"]
            path = os.path.join(IMG_DIR, "%s.png" % key)
            entry = mapped.get(key)
            urls = []
            if entry:
                urls.append(entry["icon"])
            s = slug(a.get("img") or "")
            if s:
                urls.append(GTIMG.format(name=s + str(a.get("augmentTier") or 1)))
            if a.get("img"):
                urls.append("https://static.datatft.com/images/hex2/%s.png" % a["img"])
            if os.path.exists(path) and os.path.getsize(path) > 500:
                icon_ok += 1
                continue
            done = False
            for u in urls:
                try:
                    blob = http_get(u, binary=True, tries=1)
                    with open(path, "wb") as f:
                        f.write(blob)
                    icon_ok += 1
                    done = True
                    break
                except Exception:  # noqa: BLE001
                    continue
            if not done:
                icon_fail.append((key, a["name"], urls))
            time.sleep(0.1)

    # 清理旧的数字命名文件（来自上一版脚本）
    removed = 0
    for f in os.listdir(IMG_DIR):
        if re.fullmatch(r"\d+\.png", f):
            os.remove(os.path.join(IMG_DIR, f))
            removed += 1

    stats_out = []
    for a in ours:
        rs = stats_by_ours.get(a["hexId"]) or []
        entry = mapped.get(a["hexId"])
        row = (rs[0] if rs else {})
        stats_out.append({
            "augmentHexId": a["hexId"],
            "name": a["name"],
            "datajHexId": row.get("hexId") or (int(entry["id"]) if entry and entry["id"].isdigit() else None),
            "datajName": entry["name"] if entry else None,
            "icon": entry["icon"] if entry else None,
            "iconFile": "images/augments/%s.png" % a["hexId"] if os.path.exists(os.path.join(IMG_DIR, a["hexId"] + ".png")) else None,
            "matchedBy": how.get(a["hexId"]),
            "sampleCount": row.get("sampleCount"),
            "playRate": row.get("playRate"),
            "avgPlacement": row.get("avgPlacement"),
            "top4Rate": row.get("top4Rate"),
            "topRate": row.get("topRate"),
            "rounds": row.get("rounds") or [],
            "roundStats": row.get("roundStats") or [],
        })

    json.dump({
        "meta": {
            "statsSource": STATS_PAGE,
            "catalogSource": CATALOG_API,
            "statsRows": len(rows),
            "catalogRows": len(hexes),
            "matchedCatalog": sum(1 for v in mapped.values() if v),
            "statsMatched": sum(1 for s in stats_out if s["sampleCount"]),
            "icons": icon_ok,
            "iconFail": [(k, n) for k, n, _ in icon_fail],
            "statsUnmatched": stats_unmatched,
            "removedNumericIcons": removed,
            "note": "图标统一按我们的 augment hexId 命名；来源优先 dataj 图鉴，其次 game.gtimg.cn。",
        },
        "stats": stats_out,
    }, open(os.path.join(DST, "augment_stats.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("catalog", len(hexes), "stats rows", len(rows))
    print("matched by", {k: sum(1 for v in how.values() if v == k) for k in ("name", "slug", "none")})
    print("icons", icon_ok, "fail", len(icon_fail), icon_fail[:5])
    print("stats matched", sum(1 for s in stats_out if s["sampleCount"]), "unmatched rows", len(stats_unmatched))


def _match_by_catalog(entry, ours, by_name, by_slug):
    for a in ours:
        if norm(a["name"]) == norm(entry["name"]):
            return a["hexId"]
    s = slug(entry["icon"])
    for a in ours:
        if slug(a.get("img") or "") == s:
            return a["hexId"]
    return None


if __name__ == "__main__":
    main()
