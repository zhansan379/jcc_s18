"""生成英雄技能语义标签（LLM 初稿，需人工抽检）。

输出：data/s18db/hero_skills_tags.json（独立文件，不改 heroes.json）

字段：
  damageType : magic / physical / true / mixed / none
  targeting  : single / aoe / line / multi / self / ally / summon
  cc[]       : {type, value?, duration?}
  utility[]  : shield / heal / buff_as / buff_ad / buff_ap / damage_reduction /
               cleanse / untargetable / execute / mana_regen
  summon     : 是否召唤单位
  scaling    : AP / AD / HP / none
  tags[]     : 检索用关键词
  note       : 一句话概括
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "data", "s18db")


def T(dt, tg, cc=None, util=None, summon=False, scale="AP", tags=None, note=""):
    return {
        "damageType": dt,
        "targeting": tg,
        "cc": [dict(type=t[0], value=t[1], duration=t[2]) for t in (cc or [])],
        "utility": util or [],
        "summon": summon,
        "scaling": scale,
        "tags": tags or [],
        "note": note,
    }


TAGS = {
    918043: T("magic", "single", [("slow", 30, 2)], [], False, "AP", ["单体", "AOE", "持续伤害", "减速"], "拴锁目标+范围爆发"),
    918045: T("magic", "single", [], ["execute"], False, "AP", ["单体", "条件增伤"], "低血增伤，击杀叠法强"),
    918083: T("physical", "single", [("taunt", None, None)], ["heal"], True, "AD", ["召唤", "治疗", "坦克"], "阵亡召唤嘲讽幽灵"),
    918084: T("physical", "single", [], [], False, "AD", ["单体", "条件增伤"], "对灼烧目标额外伤害"),
    918089: T("magic", "single", [("stun", None, 1.5)], ["shield"], False, "AP", ["单体", "控制", "坦度"], "眩晕+开场双抗"),
    918110: T("physical", "line", [], [], False, "AD", ["直线", "AOE", "穿透"], "穿透直线，逐目标衰减"),
    918164: T("physical", "single", [], ["shield"], False, "AD", ["单体", "护盾"], "单体伤害+2秒护盾"),
    918421: T("magic", "aoe", [("stun", None, 1.0)], ["heal"], False, "AP", ["AOE", "控制", "回复"], "邻格眩晕+被动回血"),
    918497: T("none", "ally", [], ["shield", "buff_as"], False, "none", ["护盾", "增益", "辅助"], "护盾+友军攻速"),
    918498: T("physical", "single", [("shred_armor", 2, None)], ["buff_as"], False, "AD", ["单体", "破甲", "攻速"], "5次强化普攻削甲"),
    918516: T("magic", "aoe", [], ["shield"], False, "AP", ["AOE", "护盾", "锥形"], "锥形伤害+护盾，任务攒神器"),
    918954: T("magic", "single", [], ["heal"], False, "AP", ["单体", "治疗"], "持续回血+强化普攻"),
    918989: T("magic", "single", [("shred_mr", 3, None)], [], False, "AP", ["单体", "持续伤害", "破魔抗"], "引导激光，持续削魔抗"),
    918990: T("physical", "single", [("wound", 20, 4), ("burn", 1, None)], [], False, "AD", ["单体", "重伤", "灼烧"], "五叶聚拢，附重伤灼烧"),
    918007: T("magic", "single", [], [], False, "AP", ["单体", "AOE", "复制"], "主目标+邻格溅射，可复制友军"),
    918010: T("magic", "aoe", [("shred_mr", 20, 2)], ["buff_as"], False, "AP", ["持续", "AOE", "成长"], "四次飞升逐步解锁效果"),
    918012: T("magic", "single", [("stun", None, 1.5)], ["heal", "cleanse"], False, "AP", ["单体", "控制", "治疗"], "群疗+净化+眩晕"),
    918017: T("magic", "multi", [], [], False, "AP", ["多目标", "单体", "资源"], "蘑菇AOE+巨型蘑菇，可采集"),
    918019: T("physical", "single", [], ["heal", "buff_as"], False, "AD", ["单体", "吸血", "攻速"], "撕咬+吸血+永久攻速"),
    918051: T("physical", "single", [], [], False, "AD", ["单体", "被动"], "每第三击爆头"),
    918060: T("magic", "single", [], ["heal", "buff_as"], False, "AP", ["单体", "变身", "治疗"], "变身加血+回血+攻速"),
    918098: T("magic", "ally", [], ["shield", "buff_as"], False, "AP", ["护盾", "增益", "辅助"], "自身与友军护盾+攻速"),
    918113: T("magic", "aoe", [], ["shield"], False, "AP", ["AOE", "护盾", "直线"], "锥形+直线双段"),
    918804: T("physical", "single", [], [], False, "AD", ["单体", "分裂"], "法球分裂2目标"),
    918991: T("magic", "single", [], [], False, "AP", ["单体", "AOE", "持续伤害"], "毒泡爆炸+范围持续"),
    918992: T("physical", "single", [], ["buff_as"], False, "AD", ["单体", "突进", "攻速"], "跃向低血目标+强化普攻"),
    918994: T("physical", "aoe", [], ["heal", "damage_reduction"], False, "AD", ["AOE", "减伤", "治疗"], "邻格伤害+钻地回复"),
    918009: T("magic", "multi", [("shred_mr", 10, None)], ["heal"], False, "AP", ["多目标", "吸血", "破魔抗"], "三目标汲取生命"),
    918011: T("physical", "single", [], ["buff_as"], False, "AD", ["被动", "攻速", "持续"], "第三击双重打击"),
    918018: T("physical", "single", [], ["buff_as"], False, "AD", ["单体", "AOE", "攻速"], "火花爆炸+无限射程"),
    918033: T("physical", "aoe", [("taunt", None, None)], ["shield"], False, "none", ["控制", "护盾", "AOE"], "嘲讽+护盾破碎伤害"),
    918069: T("magic", "multi", [], [], False, "AP", ["持续伤害", "多目标", "叠层"], "15秒中毒，可叠加"),
    918096: T("physical", "multi", [], [], False, "AD", ["多目标", "条件增伤"], "双目标酸液，低血增伤"),
    918107: T("physical", "single", [], ["heal"], False, "AD", ["单体", "突进", "治疗"], "跳斩+已损生命回血"),
    918120: T("magic", "multi", [("stun", None, 1.5)], ["heal"], False, "AP", ["多目标", "控制", "治疗"], "三目标眩晕+回血"),
    918121: T("magic", "single", [], [], False, "AP", ["单体", "突进", "条件增伤"], "跳最远目标，孤立增伤"),
    918131: T("magic", "aoe", [], ["shield"], False, "AP", ["AOE", "护盾"], "6颗法球分摊+护盾"),
    918254: T("none", "self", [], ["heal", "buff_as", "damage_reduction"], False, "none", ["增益", "治疗", "免控"], "回血+攻速+减伤+不可阻挡"),
    918268: T("magic", "multi", [], [], True, "AP", ["召唤", "多目标", "攻速"], "召唤沙兵代替普攻"),
    918993: T("physical", "single", [("taunt", None, None)], ["shield"], True, "AD", ["坦克", "召唤", "控制"], "阵亡分裂小石甲虫并嘲讽"),
    918995: T("physical", "multi", [], [], True, "AD", ["召唤", "多目标"], "召唤4只小鸟协同攻击"),
    918015: T("physical", "multi", [], [], False, "AD", ["弹射", "AOE"], "十字刃弹跳8次"),
    918016: T("magic", "single", [], [], False, "AP", ["单体", "AOE"], "重复命中追加星落"),
    918025: T("magic", "multi", [], ["heal"], False, "AP", ["AOE", "持续伤害", "吸血"], "诅咒+枯萎地带"),
    918032: T("magic", "aoe", [("stun", None, 1.0)], ["heal"], False, "AP", ["AOE", "控制", "持续伤害"], "2格眩晕，灼烧延长"),
    918054: T("magic", "aoe", [], ["shield"], False, "AP", ["护盾", "AOE", "控制"], "石化护盾，破碎放波"),
    918076: T("magic", "single", [], ["buff_as"], False, "AP", ["单体", "攻速", "远程"], "标枪三连，末击打后排"),
    918081: T("physical", "single", [], ["buff_as"], False, "AD", ["单体", "位移", "直线"], "闪烁拉开+四段穿透"),
    918103: T("magic", "aoe", [], [], False, "AP", ["AOE", "远程", "衰减"], "3格大范围，距离衰减"),
    918143: T("magic", "multi", [], [], True, "AP", ["召唤", "多目标", "持续"], "召唤植物攻击10次"),
    918523: T("physical", "single", [], [], False, "AD", ["单体", "AOE", "连击"], "6连斩+月光分摊"),
    918875: T("physical", "aoe", [], ["heal"], False, "AD", ["AOE", "治疗", "坦克"], "锥形重拳+回血"),
    918876: T("magic", "multi", [("sleep", None, 1.5)], ["heal"], False, "AP", ["多目标", "控制", "治疗"], "蝴蝶昏睡+回血"),
    918996: T("physical", "single", [("shred_armor", 40, None)], ["buff_ad"], False, "AD", ["单体", "增益", "破甲"], "跃击+攻击力加成+无视护甲"),
    918997: T("magic", "line", [("knockup", None, 0.5)], ["shield"], False, "AP", ["直线", "控制", "护盾"], "裂隙击飞+全队法力回复"),
    918022: T("physical", "line", [("slow", 20, None)], [], False, "AD", ["直线", "持续伤害", "减速"], "穿透箭+缓速裂隙"),
    918044: T("magic", "ally", [], ["shield", "heal"], False, "AP", ["护盾", "治疗", "辅助"], "绑定友军翡翠护盾"),
    918057: T("magic", "single", [], ["heal"], True, "HP", ["持续伤害", "治疗", "召唤"], "树苗按格挡反伤，阵亡炸开"),
    918085: T("magic", "aoe", [], ["shield"], False, "AP", ["AOE", "护盾", "突进"], "冲刺+火焰风暴"),
    918099: T("magic", "aoe", [], ["mana_regen"], False, "AP", ["AOE", "直线", "辅助"], "激光主炮，同羁绊回蓝"),
    918119: T("physical", "single", [], [], False, "AD", ["单体", "持续伤害", "流血"], "流血叠层+双斧回收"),
    918150: T("physical", "aoe", [("stun", None, 1.0), ("shred_armor", 15, None), ("shred_mr", 15, None)], [], False, "AD", ["AOE", "控制", "变形"], "变形跳大+削双抗"),
    918427: T("magic", "aoe", [], ["shield", "buff_ap", "buff_as"], False, "AP", ["护盾", "增益", "AOE"], "群体护盾+伤害增幅"),
    918955: T("magic", "multi", [], [], False, "AP", ["多目标", "AOE", "爆发"], "9枚碎片+满月大伤"),
    918998: T("physical", "aoe", [("stun", None, 1.25), ("ignite", None, 3)], ["heal", "execute", "untargetable"], False, "HP", ["AOE", "控制", "持续伤害", "斩杀"], "飞天眩晕+引燃+处决"),
}


def main():
    heroes = json.load(open(os.path.join(DST, "heroes.json"), encoding="utf-8"))["heroes"]
    by_id = {h["id"]: h for h in heroes}

    missing = [hid for hid in by_id if hid not in TAGS]
    extra = [hid for hid in TAGS if hid not in by_id]
    if missing or extra:
        raise SystemExit("id 不匹配 missing=%s extra=%s" % (missing, extra))

    out = []
    for h in sorted(heroes, key=lambda x: (x["cost"] or 9, x["id"])):
        t = TAGS[h["id"]]
        out.append({
            "id": h["id"],
            "hero": h["name"],
            "cost": h["cost"],
            "role": h["role"],
            "traits": [x["name"] for x in h["traits"]],
            "skill": h["skill"].get("name"),
            "mana": h["skill"].get("mana"),
            **t,
        })

    json.dump({
        "meta": {
            "source": "data/s18db/heroes.json（技能描述与数值）",
            "method": "LLM 人工规则标注，未使用外部模型 API",
            "extracted": "2026-11-02",
            "count": len(out),
            "status": "draft，需抽检",
            "schemas": {
                "damageType": ["magic", "physical", "true", "mixed", "none"],
                "targeting": ["single", "aoe", "line", "multi", "self", "ally", "summon"],
                "cc.type": ["stun", "knockup", "taunt", "slow", "sleep",
                            "shred_armor", "shred_mr", "burn", "wound", "ignite"],
                "utility": ["shield", "heal", "buff_as", "buff_ad", "buff_ap",
                            "damage_reduction", "cleanse", "untargetable", "execute", "mana_regen"],
                "scaling": ["AP", "AD", "HP", "none"],
            },
            "note": "被动+主动混在一个技能里的（约里克/凯尔/沃里克/阿狸等）按主要效果归类；数值只标 1 星档位。",
        },
        "skills": out,
    }, open(os.path.join(DST, "hero_skills_tags.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    from collections import Counter
    print("skills", len(out))
    print("damageType", Counter(x["damageType"] for x in out))
    print("targeting", Counter(x["targeting"] for x in out))
    print("with cc", sum(1 for x in out if x["cc"]), "| summon", sum(1 for x in out if x["summon"]))


if __name__ == "__main__":
    main()
