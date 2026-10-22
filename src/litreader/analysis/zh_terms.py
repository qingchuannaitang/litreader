"""Vision text must be Chinese with the original English in parentheses: 双相机（2 Cams）, 地面行走（Overground walking）.

Deterministic post-check on what the vision model wrote (findings, claims, unreadable parts) — never on verbatim
quotes 「…」, figure captions, inline code or text already inside parentheses:
- names and symbols stay bare: words with a digit or an inner capital (Theia3D, OpenCap, ViTPose), ALL-CAPS
  abbreviations (RMSD, ACLR), single letters (A, p, N), statistics/units (ns, vs., SD, mm, Hz…), and Capitalised words
  that also occur in the paper text (proper names such as a lab system);
- any other run of English words is a bare phrase: repaired from a small glossary to “中文（English）” (“2 Cams” →
  “双相机（2 Cams）”), otherwise flagged in place as “phrase（英文原文，未译）”.
Returns the text and a list of {"phrase", "result", "rule"} records for the evidence file.
"""
from __future__ import annotations

import re

_PROTECT = re.compile(r"「[^」]*」|“[^”]*”|`[^`]*`|（[^）]*）|\([^)]*\)")
_RUN = re.compile(r"[A-Za-z][A-Za-z0-9\-'.]*(?:[ \t]+[A-Za-z0-9][A-Za-z0-9\-'.]*)*")
_CAMS = re.compile(r"(?<![\w（(/、])(\d{1,2}(?:\s*[/、]\s*\d{1,2})*)\s*-?\s*(Cams?|cams?|Cameras?|cameras?)\b")
_ZHNUM = {1: "单", 2: "双", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}
_OK = {"ns", "vs", "vs.", "sd", "se", "ci", "iqr", "mm", "cm", "ms", "kg", "hz", "deg", "m", "s", "km", "nm", "et", "al",
       "al.", "e.g.", "i.e.", "e.g", "i.e", "etc", "etc."}
GLOSSARY = {
    "overground walking": "地面行走", "walking": "行走", "gait": "步态", "running": "跑步", "jogging": "慢跑",
    "landmark template": "标志点模板", "landmark": "标志点", "landmarks": "标志点", "template": "模板",
    "kinematics": "运动学", "kinetics": "动力学", "inverse kinematics": "逆运动学", "inverse dynamics": "逆动力学",
    "box": "箱", "box plot": "箱线图", "markerless": "无标记", "marker-based": "基于标记点", "ground truth": "真值",
    "error": "误差", "joint angle": "关节角度", "joint angles": "关节角度", "knee": "膝", "hip": "髋", "ankle": "踝",
    "pelvis": "骨盆", "flexion": "屈曲", "extension": "伸展", "adduction": "内收", "abduction": "外展",
    "rotation": "旋转", "internal rotation": "内旋", "external rotation": "外旋", "lateral step-down": "侧向下台阶",
    "single-leg squat": "单腿深蹲", "squat": "深蹲", "sit-to-stand": "坐站转换", "jump": "跳跃", "lunge": "弓步",
    "side step": "横向跨步", "healthy": "健康", "stroke": "卒中", "baseline": "基线", "mean": "均值", "median": "中位数",
    "step length": "步长", "stride length": "步幅", "walking speed": "步行速度", "cadence": "步频",
    "asymmetry": "不对称", "calibration": "校准", "auto-calibration": "自动校准", "checkerboard": "棋盘格",
    "fine-tuning": "微调", "synthetic data": "合成数据", "all activities": "所有活动", "activities": "活动",
    "token": "令牌", "tokens": "令牌", "encoder": "编码器", "decoder": "解码器", "mask": "掩码", "masks": "掩码",
}


def _allowed(w: str, known: set[str]) -> bool:
    core = w.strip(".'-")
    if not core or len(core) == 1 or w.lower() in _OK or core.lower() in _OK:
        return True
    if any(ch.isdigit() for ch in core) or (any(ch.isupper() for ch in core[1:]) and not core.isupper()):
        return True                                   # Theia3D, OpenCap, ViTPose
    if core.isupper() or (core[:-1].isupper() and core.endswith("s") and len(core) > 2):
        return True                                   # RMSD, ACLR, RMSDs
    return core[0].isupper() and core in known        # proper name that the paper text also uses


def _zh_cams(m: re.Match) -> str:
    nums = re.split(r"\s*[/、]\s*", m.group(1))
    if len(nums) > 1:   # “6/10 Cams” -> “6/10 台相机（6/10 Cams）”
        return f"{'/'.join(nums)} 台相机（{m.group(0).strip()}）"
    n = int(nums[0])
    return f"{_ZHNUM.get(n, str(n) + ' 台')}相机（{m.group(0).strip()}）"


def bilingual(text: str, known_text: str = "") -> tuple[str, list[dict]]:
    if not text:
        return text, []
    known = set(re.findall(r"[A-Za-z][A-Za-z0-9\-]+", known_text or ""))
    recs: list[dict] = []
    out, pos = [], 0
    for pm in list(_PROTECT.finditer(text)) + [None]:
        seg = text[pos:pm.start()] if pm else text[pos:]
        out.append(_fix(seg, known, recs))
        if pm:
            out.append(pm.group(0)); pos = pm.end()
    return "".join(out), recs


def _fix(seg: str, known: set[str], recs: list[dict]) -> str:
    def cams(m):
        r = _zh_cams(m)
        recs.append({"phrase": m.group(0).strip(), "result": r, "rule": "zh_terms.glossary"})
        return r
    seg = _CAMS.sub(cams, seg)
    parts = re.split(r"(（[^）]*）)", seg)   # a repaired “（2 Cams）” is protected from the phrase pass
    seg = "".join(p if p.startswith("（") else _phrases(p, known, recs) for p in parts)
    if not recs:
        return seg
    seg = re.sub(r"）[ \t]+(?=[\u4e00-\u9fff])", "）", seg)
    return re.sub(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])", "", seg)


def _phrases(seg: str, known: set[str], recs: list[dict]) -> str:
    def one(m):
        run = m.group(0).rstrip(".")
        tail = m.group(0)[len(run):]
        words = run.split()
        if all(_allowed(w, known) for w in words):
            return m.group(0)
        # keep leading/trailing names outside the phrase: “OpenCap overground walking” -> name + phrase
        i, j = 0, len(words)
        # (a Capitalised word known from the paper is a name only on its own: “Overground walking” stays one phrase)
        while i < j and _allowed(words[i], set()):
            i += 1
        while j > i and _allowed(words[j - 1], set()):
            j -= 1
        phrase = " ".join(words[i:j])
        zh = GLOSSARY.get(phrase.lower())
        if not zh and len(words[i:j]) > 1 and all(w.lower() in GLOSSARY for w in words[i:j]):
            zh = "".join(GLOSSARY[w.lower()] for w in words[i:j])     # “knee flexion” -> 膝屈曲
        if zh:
            rep, rule = f"{zh}（{phrase}）", "zh_terms.glossary"
        else:
            rep, rule = f"{phrase}（英文原文，未译）", "zh_terms.flag"
        recs.append({"phrase": phrase, "result": rep, "rule": rule})
        pre, post = " ".join(words[:i]), " ".join(words[j:])
        return (pre + " " if pre else "") + rep + (" " + post if post else "") + tail
    return _RUN.sub(one, seg)
