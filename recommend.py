# -*- coding: utf-8 -*-
"""
根据 scan.py 的局面 JSON 推荐阵容与下一步行动
================================================
用法：
    python recommend.py output/sample_state.json
    python recommend.py state.json --top 3 --json plan.json
    python recommend.py state.json --rules config/strategy_rules.json

    # 一条命令完成「扫描 + 推荐」，只输出摘要
    python recommend.py --image 图.png --brief

输入是 `python scan.py 图.png --labels --json state.json` 的输出；
`--image` 会内部调用 `scan.scan(..., with_labels=True)`。
默认只做规则匹配与行动建议，不联网、不调用 VLM。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "core"))

from comp_index import load_index          # noqa: E402
import comp_match                          # noqa: E402
import economy                             # noqa: E402


def _load_state(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        if len(data) == 1:
            data = data[0]
        else:
            raise ValueError("输入是多张图的数组；请先用 --json 单图输出，或手动取其中一项")
    if not isinstance(data, dict):
        raise ValueError("输入 JSON 顶层必须是对象")
    return data


def _print_brief(payload):
    """只输出决策所需：局面、Top1、缺失核心、行动、告警。"""
    st = payload["state"]
    recs = payload.get("recommendations") or []
    print("阶段 %s | Lv%s | 金币 %s | 血量 %s | 单位 %d（有名字 %d）"
          % (st.get("stage"), st.get("level"), st.get("gold"), st.get("hp"),
             st.get("units", 0), st.get("named_units", 0)))
    if recs:
        c = recs[0]
        print("主推：%s [%s] score=%.2f confidence=%.2f"
              % (c["title"], c.get("tier") or "?", c["score"], c["confidence"]))
        if c.get("missing_core"):
            print("缺核心：%s" % "、".join(c["missing_core"]))
        if c.get("augment_hits"):
            print("符文契合：%s" % "、".join(
                "%s(%.1f)" % (h["name"], h["fit"]) for h in c["augment_hits"]))
    else:
        print("主推：无（检查 data/s18db/comps.json）")
    actions = payload.get("actions") or []
    print("行动：" + ("；".join(
        "[%d] %s%s" % (a["priority"], a["type"],
                       (" " + a["target"]) if a.get("target") else "")
        for a in actions) or "无"))
    for w in payload.get("warnings") or []:
        print("[!] " + w)


def _print_human(payload):
    st = payload["state"]
    print("\n=== 局面 ===")
    print("阶段 %s | Lv%s | 金币 %s | 血量 %s | 单位 %d（有名字 %d）"
          % (st.get("stage"), st.get("level"), st.get("gold"), st.get("hp"),
             st.get("units", 0), st.get("named_units", 0)))

    print("\n=== 候选阵容 ===")
    recs = payload.get("recommendations") or []
    if not recs:
        print("（无；检查 data/s18db/comps.json）")
    for i, c in enumerate(recs, 1):
        print("%d. %s [%s]  score=%.2f  confidence=%.2f"
              % (i, c["title"], c.get("tier") or "?", c["score"], c["confidence"]))
        if c.get("missing_core"):
            print("   缺核心：%s" % "、".join(c["missing_core"]))
        if c.get("missing_units"):
            print("   缺单位：%s" % "、".join(c["missing_units"]))
        if c.get("trait_gaps"):
            print("   羁绊差：%s" % "、".join(
                "%s %d/%d" % (g["name"], g["current"], g["target"]) for g in c["trait_gaps"]))
        if c.get("reasons"):
            print("   依据：%s" % "；".join(c["reasons"]))

    print("\n=== 下一步 ===")
    actions = payload.get("actions") or []
    if not actions:
        print("（没有足够信息给出行动；先补单位名字或检查截图）")
    for a in actions:
        target = (" " + a["target"]) if a.get("target") else ""
        print("[%d] %-9s%s  %s" % (a["priority"], a["type"], target, a["why"]))

    warnings = payload.get("warnings") or []
    if warnings:
        print("\n=== 告警 ===")
        for w in warnings:
            print("[!] " + w)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="根据 scan.py 局面推荐 S18 阵容与行动")
    ap.add_argument("state", nargs="?", help="scan.py --json 生成的文件")
    ap.add_argument("--image", help="直接扫描截图（内部调用 scan.scan，带 --labels）")
    ap.add_argument("--backend", default="ocr", choices=["ocr", "vlm", "hybrid"],
                    help="配合 --image；默认 ocr，不联网")
    ap.add_argument("--save-state", help="配合 --image：把局面 JSON 也写出来")
    ap.add_argument("--brief", action="store_true", help="只输出 Top1 + 行动摘要")
    ap.add_argument("--top", type=int, default=3, help="候选数量，默认 3")
    ap.add_argument("--json", help="把完整建议写到这个 JSON")
    ap.add_argument("--rules", help="策略参数文件，默认 config/strategy_rules.json")
    a = ap.parse_args()

    if bool(a.state) == bool(a.image):
        ap.error("请提供 state JSON，或者用 --image 扫描截图（二选一）")

    try:
        if a.image:
            import scan as scan_mod
            state = scan_mod.scan(a.image, backend=a.backend, with_labels=True)
            state_file = os.path.basename(a.image)
            if a.save_state:
                with open(a.save_state, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
        else:
            state = _load_state(a.state)
            state_file = os.path.basename(a.state)
        idx = load_index()
        rules = economy.load_rules(a.rules)
    except Exception as e:
        print("加载失败：%s" % e, file=sys.stderr)
        return 2

    match = comp_match.recommend(state, idx, rules=rules, top=a.top)
    actions = economy.make_actions(state, match, rules)
    payload = {
        "state_file": state_file,
        "top": a.top,
        "state": match["state"],
        "recommendations": match["candidates"],
        "actions": actions,
        "warnings": match["warnings"],
    }

    (_print_brief if a.brief else _print_human)(payload)

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("\n[已写入] %s" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
