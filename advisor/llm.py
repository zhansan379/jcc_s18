# -*- coding: utf-8 -*-
"""
LLM 文本建议（百炼 OpenAI 兼容接口，纯文本，不带图）
====================================================
定位：规则推荐已经给出「阵容 / 缺牌 / 装备 / 符文候选」，
LLM 只负责把这些数据翻译成一段教练口吻的建议，并给符文排个序。

为什么能压在 2s 内：
  * 只发文本（不发图），prompt 控制在 ~1.2k token
  * max_tokens 卡死 600，temperature 0.2
  * 硬 deadline：超时立刻返回 None，UI 回落到规则文案（不阻塞界面）

key 来源：环境变量 DASHSCOPE_API_KEY（本项目不内置任何 key）。没设时 `available()`
返回 False，UI 自动回落规则文案。
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "core"))

API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("JCC_LLM_MODEL", "qwen-flash")
DEFAULT_TIMEOUT = float(os.environ.get("JCC_LLM_TIMEOUT", "3.5"))

_mem = {}
_mem_order = []
_KEY = [None]


def api_key():
    if _KEY[0] is None:
        k = os.environ.get("DASHSCOPE_API_KEY")
        if not k:
            try:
                import vlm_board_scan as _v
                k = _v.API_KEY
            except Exception:
                k = None
        _KEY[0] = k or ""
    return _KEY[0]


def available():
    return bool(api_key())


def _post(payload, timeout):
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + api_key(),
                 "Content-Type": "application/json"}, method="POST")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    dt = time.perf_counter() - t0
    txt = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return txt.strip(), dt


def chat(system, user, max_tokens=600, timeout=None, model=None):
    """返回 (text, elapsed, err)。err 非空表示失败，调用方要回落。

    timeout 是**整段墙钟时间**的硬上限：请求放在子线程里跑，join 不到就直接返回，
    保证 UI 的「≤10s」不会被一次慢请求拖垮。
    """
    if not available():
        return "", 0.0, "no-key"
    timeout = timeout or DEFAULT_TIMEOUT
    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    box = {}

    def run():
        try:
            box["ok"] = _post(payload, timeout)
        except urllib.error.HTTPError as e:
            box["err"] = "HTTP%d %s" % (e.code, e.read().decode("utf-8", "ignore")[:120])
        except Exception as e:
            box["err"] = "%s: %s" % (type(e).__name__, str(e)[:100])

    t = threading.Thread(target=run, daemon=True)
    t0 = time.perf_counter()
    t.start()
    t.join(timeout)
    dt = time.perf_counter() - t0
    if t.is_alive():
        return "", dt, "timeout(%.1fs)" % timeout
    if box.get("err"):
        return "", dt, box["err"]
    txt, _ = box.get("ok") or ("", 0.0)
    return txt, dt, None


def _parse_json(text):
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```")[1]
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    for a, b in (("{", "}"), ("[", "]")):
        i, j = s.find(a), s.rfind(b)
        if i >= 0 and j > i:
            try:
                return json.loads(s[i:j + 1])
            except Exception:
                pass
    return None


SYSTEM = (
    "你是金铲铲之战 S18 的教练。只根据用户给的数据回答，严禁编造英雄名或符文名。\n"
    "输出必须是单个 JSON 对象（不要 markdown、不要多余文字），字段固定为：\n"
    "summary: 一句话本局判断，不超过 40 字\n"
    "roll: 该不该搜牌或升人口，不超过 25 字\n"
    "streak: 以「连胜」「连败」「稳血」之一开头，后面跟不超过 20 字的理由\n"
    "augments: 数组，1~4 项，每项 {name, why}，name 必须逐字取自用户给的「可选强化符文」\n"
    "keep: 字符串数组，2~6 个牌名，必须来自用户给的「现有棋子」或「还缺」\n"
    "所有字段都要写具体结论，不要照抄字段说明。"
)

_PLACEHOLDER = ("字内", "该不该搜牌或升人口", "选一个", "不超过", "...", "…")


def _is_placeholder(s):
    s = str(s or "").strip()
    return (not s) or any(t in s for t in _PLACEHOLDER)


def _fmt_state(state, top, actions, aug_pool):
    st = state.get("state") or {}
    detail = top.get("detail") or {}
    lines = []
    lines.append("阶段 %s | 等级 %s | 经验 %s | 金币 %s | 血量 %s | 棋盘单位 %s"
                 % (st.get("stage"), st.get("level"), st.get("exp"), st.get("gold"),
                    st.get("hp"), st.get("units")))
    if st.get("shop"):
        lines.append("商店：%s" % "、".join(x for x in st["shop"] if x))
    if st.get("augments"):
        lines.append("已有强化符文：%s" % "、".join(st["augments"]))
    if st.get("traits"):
        lines.append("当前羁绊：%s" % "、".join("%s%d" % (k, v) for k, v in
                                              list(st["traits"].items())[:10]))
    if top:
        lines.append("主推阵容：%s（%s级，平均排名 %s，前四率 %s%%，打法 %s）"
                     % (top.get("title"), top.get("tier"), (top.get("stats") or {}).get("avgPlace"),
                        (top.get("stats") or {}).get("top4Rate"), top.get("style")))
        if top.get("matched_units"):
            lines.append("现有棋子（在阵容里）：%s" % "、".join(top["matched_units"]))
        if top.get("missing_units"):
            lines.append("还缺：%s" % "、".join(top["missing_units"]))
        if top.get("trait_gaps"):
            lines.append("羁绊差距：%s" % "、".join(
                "%s %d/%d" % (g["name"], g["current"], g["target"]) for g in top["trait_gaps"][:8]))
        if detail.get("components"):
            lines.append("手上散件：%s" % "、".join(detail["components"]))
        if detail.get("item_plan"):
            lines.append("散件可立刻合成：%s" % "、".join(
                "%s(%s+%s)" % (i["item"], i["from"][0], i["from"][1])
                for i in detail["item_plan"]))
        for label, key in (("前期", "early"), ("中期", "mid"), ("后期", "final")):
            if top.get(key):
                lines.append("%s打法：%s" % (label, top[key][:120]))
    if actions:
        lines.append("规则给出的动作：%s" % "；".join(a.get("why", "")[:40] for a in actions[:3]))
    try:
        import economy as _eco
        lv_target = _eco.target_level(st.get("stage"), _eco.load_rules())
        if lv_target:
            lines.append("本阶段目标等级：%s（当前 %s）" % (lv_target, st.get("level")))
    except Exception:
        pass
    if aug_pool:
        lines.append("可选强化符文（augments.name 只能从这里选）：")
        for a in aug_pool:
            lines.append("- %s（%s级/%s）：%s" % (
                a["name"], a.get("tier") or "?", "/".join(a.get("typeZh") or []) or "-",
                (a.get("desc") or "")[:40]))
    return "\n".join(lines)


def _validate(data, top, pool):
    """把模型输出钉死在真实数据上：符文名、牌名都必须来自给定集合"""
    allowed_aug = [a["name"] for a in (pool or [])]
    board = [u["name"] for u in ((top or {}).get("detail") or {}).get("board") or []]
    allowed_keep = set(board) | set((top or {}).get("matched_units") or []) \
        | set((top or {}).get("missing_units") or [])

    def s(v, n):
        return str(v or "").strip()[:n]

    out = {"summary": s(data.get("summary"), 90),
           "roll": s(data.get("roll"), 60),
           "streak": s(data.get("streak"), 60)}
    for k in ("summary", "roll", "streak"):
        if _is_placeholder(out[k]):
            out[k] = ""
    if not (out["summary"] or out["roll"] or out["streak"]):
        return None
    augs, seen = [], set()
    for a in data.get("augments") or []:
        if not isinstance(a, dict):
            continue
        n = str(a.get("name") or "").strip()
        if n in allowed_aug and n not in seen:
            seen.add(n)
            why = s(a.get("why"), 40)
            augs.append({"name": n, "why": "" if _is_placeholder(why) else why})
        if len(augs) >= 4:
            break
    out["augments"] = augs
    keep = []
    for k in data.get("keep") or []:
        k = str(k or "").strip()
        if k and k in allowed_keep and k not in keep:
            keep.append(k)
    out["keep"] = keep[:6]
    out["dropped"] = {"augments": len(data.get("augments") or []) - len(augs),
                      "keep": len(data.get("keep") or []) - len(keep)}
    return out


def narrate(state, top, actions, aug_pool, timeout=None):
    """返回 {'data': {...}, 'elapsed': s, 'error': str|None, 'model': str}"""
    key = json.dumps([top.get("title") if top else None, state.get("state"),
                      [a["name"] for a in (aug_pool or [])]], ensure_ascii=False, sort_keys=True)
    if key in _mem:
        hit = dict(_mem[key])
        hit["cached"] = True
        return hit

    user = _fmt_state(state, top, actions, aug_pool)
    txt, dt, err = chat(SYSTEM, user, max_tokens=520, timeout=timeout)
    raw = _parse_json(txt) if not err else None
    if raw is None and not err:
        err = "unparsable"
    data = _validate(raw, top, aug_pool) if isinstance(raw, dict) else None
    if data is not None and not (data.get("summary") or data.get("roll")
                                 or data.get("augments") or data.get("keep")):
        data, err = None, "empty"
    out = {"data": data,
           "elapsed": round(dt, 2),
           "error": err,
           "model": DEFAULT_MODEL,
           "raw": (txt or "")[:600]}
    if out["data"]:
        _mem[key] = dict(out)
        _mem_order.append(key)
        while len(_mem_order) > 200:
            _mem.pop(_mem_order.pop(0), None)
    return out


def rule_fallback(state, top, actions, pool=None):
    """LLM 不可用时用规则拼一份等价结构的文案"""
    st = state.get("state") or {}
    gold = st.get("gold") or 0
    hp = st.get("hp")
    names = [a["name"] for a in (pool or [])][:3]
    roll = "金币 %s，血量 %s：先别搜空，卡利息" % (gold, hp)
    if hp is not None and hp < 35:
        roll = "血量 %s 已经危险，优先搜牌稳血" % hp
    return {
        "summary": "规则结果：跟随主推阵容补齐缺失单位",
        "roll": roll,
        "streak": "血量 40 以上吃利息，低于 40 转稳血",
        "augments": [{"name": n, "why": "评级高且与打法契合"} for n in names],
        "keep": (top or {}).get("missing_units", [])[:5],
        "from_rules": True,
    }
