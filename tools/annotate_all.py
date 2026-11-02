# -*- coding: utf-8 -*-
"""
全量标注：把 scan 识别到的每一项都画到原图上
------------------------------------------------
阶段 / 等级 / 经验 / 金币 / 商店 5 张 / 玩家排名 / 我的血量 / 棋盘单位 / 羁绊
"""
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = r"D:\Project\tmp\jcc_s18"
OUT = os.path.join(HERE, "output")

# 各区域框（与 core/vlm_board_scan.py 的 REGIONS 保持一致）
REGIONS = {
    "stage":     (0.325, 0.005, 0.385, 0.045, "阶段"),
    "level_exp": (0.170, 0.750, 0.280, 0.820, "等级/经验"),
    "gold":      (0.462, 0.750, 0.548, 0.820, "金币"),
    "shop":      (0.290, 0.826, 0.868, 1.000, "商店"),
    "traits":    (0.050, 0.075, 0.190, 0.580, "羁绊"),
    "players":   (0.820, 0.030, 1.000, 0.800, "玩家列表"),
}


def box_px(img, frac):
    l, t, r, b = frac
    W, H = img.size
    return [int(l*W), int(t*H), int(r*W), int(b*H)]


def label(d, xy, text, color, font, bg=(8, 8, 12, 230)):
    x, y = xy
    tw = d.textlength(text, font=font)
    d.rounded_rectangle([x, y, x+tw+12, y+28], radius=6, fill=bg, outline=color+(255,), width=2)
    d.text((x+6, y+3), text, font=font, fill=color+(255,))


def annotate_all(img, r, units, traits_list, players, out_path):
    base = img.convert("RGBA")
    ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 20)
    small = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16)
    big = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 24)

    C = {"stage": (255, 120, 120), "level_exp": (255, 200, 60), "gold": (255, 215, 0),
         "shop": (120, 255, 140), "traits": (150, 200, 255), "players": (255, 140, 220),
         "board": (0, 255, 120), "bench": (90, 190, 255), "items": (0, 230, 230),
         "augment": (255, 150, 60)}

    # ---- 强化符文 ----
    augs = r.get("强化符文") or []
    for i, a in enumerate(augs, 1):
        bx = a["box"]
        ok = a.get("reliable")
        col = C["augment"] if ok else (200, 120, 60)
        d.rectangle(bx, outline=col+(255,), width=3)
        top3 = a.get("top") or []
        if ok and a.get("name"):
            tag = "符文#%d %s %.2f" % (i, a["name"][:8], a["score"])
        else:
            cand = " / ".join("%s%.2f" % ((t.get("name") or "?")[:6], t["score"]) for t in top3[:3])
            tag = "符文#%d 未知（%s）" % (i, cand)
        lx, ly = bx[0]-10, bx[3]+6
        if ly > base.height-30:
            ly = bx[1]-30
        tw = d.textlength(tag, font=small)
        d.rounded_rectangle([lx, ly, lx+tw+12, ly+24], radius=5, fill=(8, 8, 12, 232))
        d.text((lx+6, ly+2), tag, font=small, fill=col+(255,))

    # ---- 最左侧装备栏 ----
    items = r.get("装备栏") or []
    if items:
        for i, it in enumerate(items, 1):
            bx = it["box"]
            d.rectangle(bx, outline=C["items"]+(255,), width=3)
            d.rounded_rectangle([bx[0]+2, bx[1]+2, bx[0]+26, bx[1]+24], radius=4,
                                fill=(8, 8, 12, 235))
            d.text((bx[0]+6, bx[1]+3), str(i), font=small, fill=C["items"]+(255,))
        # 图例放在羁绊面板下方空白处
        lx, ly = 24, int(base.height*0.60)
        label(d, (lx, ly-30), "最左侧装备栏 %d 件" % len(items), C["items"], font)
        for i, it in enumerate(items, 1):
            yy = ly + (i-1)*27
            d.rounded_rectangle([lx, yy, lx+230, yy+25], radius=5, fill=(8, 8, 12, 225))
            d.text((lx+6, yy+3), "%d. %s  %.2f" % (i, it["name"], it["score"]),
                   font=small, fill=C["items"]+(255,))

    # ---- 文本字段区域框 ----
    vals = {"stage": "%s" % r["阶段"], "level_exp": "%s级  %s" % (r["等级"], r["经验"]),
            "gold": "%s" % r["金币"]}
    for k in ("stage", "level_exp", "gold"):
        l, t, rr, b, name = REGIONS[k]
        bx = box_px(base, (l, t, rr, b))
        d.rectangle(bx, outline=C[k]+(255,), width=3)
        label(d, (bx[0], max(0, bx[1]-32)), "%s: %s" % (name, vals[k]), C[k], font)

    # ---- 商店 ----
    l, t, rr, b, name = REGIONS["shop"]
    sbox = box_px(base, (l, t, rr, b))
    d.rectangle(sbox, outline=C["shop"]+(255,), width=3)
    label(d, (sbox[0], max(0, sbox[1]-32)), "商店（%d 张）" % sum(1 for x in (r["商店"] or []) if x), C["shop"], font)
    w5 = (sbox[2]-sbox[0]) / 5.0
    for i, nm in enumerate(r["商店"] or []):
        cx = int(sbox[0] + w5*i)
        d.line([(cx, sbox[1]), (cx, sbox[3])], fill=C["shop"]+(120,), width=1)
        if nm:
            label(d, (cx+4, sbox[3]-30), str(nm)[:6], C["shop"], small)

    # ---- 羁绊 ----
    l, t, rr, b, name = REGIONS["traits"]
    tbox = box_px(base, (l, t, rr, b))
    d.rectangle(tbox, outline=C["traits"]+(255,), width=3)
    label(d, (tbox[0], max(0, tbox[1]-32)), "羁绊 %d 条" % len(traits_list), C["traits"], font)
    for i, tr in enumerate(traits_list):
        label(d, (tbox[2]+8, tbox[1] + i*30),
              "%s %s" % (tr["name"], tr["count"]), C["traits"], small)

    # ---- 玩家列表 ----
    l, t, rr, b, name = REGIONS["players"]
    pbox = box_px(base, (l, t, rr, b))
    d.rectangle(pbox, outline=C["players"]+(255,), width=3)
    label(d, (pbox[0]-150, max(0, pbox[1]-32)),
          "玩家排名 %d 人／我 %s" % (len(players), r["我的血量"]), C["players"], font)

    # ---- 棋盘单位 ----
    nb = sum(1 for u in units if u["area"] == "board")
    nn = len(units) - nb
    for i, u in enumerate(units, 1):
        x0, y0, x1, y1 = u["box"]
        c = C[u["area"]]
        d.rectangle([x0-2, y0-2, x1+1, y1+1], outline=c+(255,), width=2)
        nm = u.get("name")
        sc = u.get("name_score")
        mark = {"cache": "", "vlm": "*"}.get(u.get("name_src"), "")
        if nm:
            tag = "#%d %s%.2f %d★%s%s" % (i, nm + " ", sc if sc is not None else 0,
                                          u["star"] or 0,
                                          "棋" if u["area"] == "board" else "备", mark)
            box_col = (90, 255, 160)
        else:
            top = u.get("name_top") or []
            if top:
                tag = "#%d 判不出（最像%s %.2f）" % (i, top[0]["name"], top[0]["score"])
            else:
                tag = "#%d 未匹配" % i
            box_col = (150, 150, 150)
        tw = d.textlength(tag, font=small)
        lift = 28 + (i % 2)*22
        ly = y0 - lift
        if ly < 4:
            ly = y1 + 4
        lx = min(max(2, x0-6), base.size[0] - int(tw) - 16)
        d.rounded_rectangle([lx, ly, lx+tw+12, ly+24], radius=5,
                            fill=(8, 8, 12, 232),
                            outline=((90, 255, 160) if nm else (120, 120, 120)) + (200,))
        d.text((lx+5, ly+2), tag, font=small, fill=c+(255,))

    label(d, (14, 14), "棋盘 %d ／ 备战席 %d（共 %d）"
          % (nb, nn, len(units)), C["board"], big)
    n_named = sum(1 for u in units if u.get("name"))
    if n_named:
        srcs = {u.get("name_src") for u in units if u.get("name")}
        if "label" in srcs:
            note = "来自 data/hero_labels 人工标注，本地匹配"
        else:
            note = "* = 本次现问 VLM，其余来自缓存"
        label(d, (14, 46), "英雄名 %d/%d（%s）" % (n_named, len(units), note),
              (90, 255, 160), small)

    Image.alpha_composite(base, ov).convert("RGB").save(out_path)
    return out_path


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(OUT, "status.json"), help="scan 输出的 JSON")
    ap.add_argument("--image", default=r"D:\Download\00a5a489-ca7a-4216-bef0-81821a313981.png")
    ap.add_argument("--out", default=os.path.join(OUT, "全量标注.png"))
    a = ap.parse_args()
    data = json.load(open(a.json, encoding="utf-8"))
    img = Image.open(a.image).convert("RGB")
    p = annotate_all(img, data, data["单位"], data["羁绊"], data.get("玩家排名") or [],
                     a.out)
    print("saved", p)


if __name__ == "__main__":
    main()
