"""Deterministic wording gate: comparative/superlative judgements need a statistical test in the cited blocks.

If the cited blocks contain a test/p-value (p=…, p<…, F=…, t=…, χ²…, 显著, Bonferroni …) the wording is kept.
Otherwise: safe rewrites to neutral numeric phrasing (最好/最佳/最优 -> 数值最高; 更好/优于/更高效/更有效/更准确 -> 数值更高),
ONLY when a higher-is-better metric is named in the comparative's own clause (review 4: never borrowed from the cited blocks) — with no metric the
item is annotated as the authors' wording / an inference, or rejected — and never when the metric is "lower is better": for RMSD / error / bias / time-like metrics "优于" means a LOWER
number, so a "数值更高" rewrite would invert the meaning -> such items are rejected (raw paired values stay in the
evidence archive). Metric direction comes from the comparative's clause only (review 4); if both directions
appear the item is rejected. Direction-ambiguous words (更差/最差/劣于/更糟) are rejected.
Headings and titles have no cited blocks, so they are always gated. Every change is logged with its gate name.
"""
from __future__ import annotations

import re

from .latex import clean

GATE = "wording.deterministic"

_TEST = re.compile(r"[pP\ufffd]\s*[=<>≤≥]\s*0?\.\d|[FtZ]\s*[=(]\s*-?\d|χ\s*2|χ²|显著|Bonferroni|LSD|ANOVA|MANCOVA|卡方|95%\s*CI|置信区间")
# a real test statistic (no keyword-only matches such as 显著)
STAT = re.compile(r"[pP\ufffd]\s*[=<>≤≥]\s*0?\.\d|[FtZ]\s*[=(]\s*-?\d|χ\s*2\s*=|χ²\s*=|95%\s*CI|置信区间")
REWRITE = [(r"表现最好|表现最佳|表现最优", "数值最高"), (r"最好|最佳|最优", "数值最高"),
           (r"表现更好", "数值更高"), (r"优于|胜过", "数值高于"), (r"更好|更高效|更有效|更准确", "数值更高")]
REJECT = re.compile(r"更差|最差|劣于|更糟|表现更差|更敏感|更可靠|更稳定|更强|更弱|最强|最明显")
# metric direction (where a "better" number is lower / higher)
LOWER_BETTER = re.compile(r"r?RMSD|RMSE|MAE|MSE|均方根|误差|偏差|错误率|失败率|耗时|延迟|损失|\bloss\b|\berror\b|\bbias\b", re.I)
HIGHER_BETTER = re.compile(r"AUC|ICC|准确率|准确度|精度|敏感度|灵敏度|特异度|相关系数|相关性|一致性|召回率|\bF1\b|Dice|R²|kappa|κ|得分|评分", re.I)


def _norm_t(text: str) -> str:
    return clean(text or "").replace("\ufffd", "p")


def has_test(text: str) -> bool:
    return bool(_TEST.search(_norm_t(text)))


def has_stat(text: str) -> bool:
    return bool(STAT.search(_norm_t(text)))


def direction(text: str, basis_text: str | None = None) -> str | None:
    """'lower' | 'higher' | 'ambiguous' | None (no metric named). Sentence first, cited blocks second."""
    for t in (text, basis_text):
        if not t:
            continue
        lo, hi = bool(LOWER_BETTER.search(t)), bool(HIGHER_BETTER.search(t))
        if lo and hi:
            return "ambiguous"
        if lo:
            return "lower"
        if hi:
            return "higher"
    return None


# set phrases with 最佳/最优 that compare nothing (“尚未取得最佳平衡”)
IDIOM = re.compile(r"(?:最佳|最优|最好)(?:的)?(?:平衡|折中|实践|时机|方式|方法|途径|选择|做法)")


def _idiom_free(text: str) -> str:
    return IDIOM.sub("", text or "")


def _hits(text: str) -> list[str]:
    t = _idiom_free(text)
    return [h for pat, _ in REWRITE for h in re.findall(pat, t)]


# a yes/no question heading asserts nothing: “…是否优于对照工具？”
_YESNO = re.compile(r"是否[^，。；;？?]*?(?:优于|胜过|更好|更高效|更有效|更准确|最好|最佳|最优)[^，。；;]*[？?]\s*$")


NO_METRIC = "no metric named in the clause or cited blocks: a “数值更高” rewrite would be meaningless"
ANNOT_PAPER, ANNOT_INFER = "（作者表述，无对应检验）", "（整理者推断，无对应检验）"
_CLAUSE = re.compile(r"[^，,；;。.!?！？]+")


def _clauses_of_hits(text: str) -> list[str]:
    out = []
    for m in _CLAUSE.finditer(text):
        if any(re.search(pat, m.group(0)) for pat, _ in REWRITE):
            out.append(m.group(0))
    return out or [text]


_METRIC_VALUE = re.compile("(?:" + LOWER_BETTER.pattern + "|" + HIGHER_BETTER.pattern + r")\s*(?:[=:：]|为|达)?\s*\d", re.I)


def _clause_direction(text: str, clause: str) -> str | None:
    """Direction from the comparative's clause; else from the NEXT clause of the same sentence only when it gives that
    metric's value (“表现最好，AUC 0.906”). “…优于…，且精度提升” (no value) does not count."""
    d = direction(clause)
    if d:
        return d
    sent = re.split(r"[。.!?！？；;]", _idiom_free(text))
    for st in sent:
        cl = _CLAUSE.findall(st)
        if clause in cl:
            i = cl.index(clause)
            if i + 1 < len(cl) and _METRIC_VALUE.search(cl[i + 1]):
                return direction(cl[i + 1])
    return None


def rewrite(text: str, basis_text: str | None = None) -> tuple[str | None, str | None]:
    """Neutral rewrite. Returns (new | None, reason-if-refused).
    Metric direction is read from the CLAUSE that holds the comparative (then the cited blocks): “性能优于…，且精度提升”
    has no metric in the comparative's clause, so 精度 elsewhere in the sentence does not license “数值高于”."""
    hits = _hits(text)
    if not hits:
        return None, None
    # review 4: the metric must be named in the comparative's OWN clause. Borrowing it from the cited blocks produced
    # “指标多数值高于”(RMSD-type metrics!) and “尚未取得数值最高平衡” on DeepGaitLab.
    dirs = {_clause_direction(text, c) for c in _clauses_of_hits(_idiom_free(text))}
    if dirs & {"lower", "ambiguous"}:
        d = "lower" if "lower" in dirs else "ambiguous"
        why = ("lower-is-better metric (RMSD/误差/偏差/耗时…): '“" + "、".join(dict.fromkeys(hits)) + "”' cannot become “数值更高”"
               if d == "lower" else "metric direction ambiguous (both lower- and higher-is-better metrics named)")
        return None, why
    if None in dirs:
        return None, NO_METRIC
    new = text
    for pat, rep in REWRITE:
        new = _sub_outside_idioms(new, pat, rep)
    return new, None


def _sub_outside_idioms(text: str, pat: str, rep: str) -> str:
    out, pos = [], 0
    for m in IDIOM.finditer(text):
        out.append(re.sub(pat, rep, text[pos:m.start()])); out.append(m.group(0)); pos = m.end()
    out.append(re.sub(pat, rep, text[pos:]))
    return "".join(out)


def gate(text: str, basis_text: str | None, label: str | None = None) -> tuple[str | None, str | None]:
    """Return (new_text | None if rejected, rule | None if unchanged).
    A comparative with no metric at all (“性能优于”“更有效利用”) is never turned into “数值更高”: if the comparative
    word itself is in the cited text it is kept as the authors' wording and annotated（作者表述，无对应检验）; an
    INFERENCE is annotated（整理者推断，无对应检验）; otherwise (incl. headings) it is rejected."""
    if not text:
        return text, None
    if basis_text is not None and has_test(basis_text):
        return text, None
    if basis_text is None and _YESNO.search(text):
        return text, None
    if REJECT.search(text):
        return None, f"reject: direction-ambiguous comparative '{REJECT.search(text).group(0)}' without a test in cited blocks"
    hits = _hits(text)
    if not hits:
        return text, None
    if ANNOT_PAPER in text or ANNOT_INFER in text:
        return text, None
    new, refused = rewrite(text, basis_text)
    if new is None and refused == NO_METRIC and basis_text is not None:
        words = "、".join(dict.fromkeys(hits))
        if label == "INFERENCE":
            return text + ANNOT_INFER, f"annotate: {words} without a metric or test -> 整理者推断 (no test in cited blocks)"
        if all(h in _norm_t(basis_text) for h in dict.fromkeys(hits)):
            return text + ANNOT_PAPER, f"annotate: {words} is the authors' wording, no metric or test -> 作者表述 (no test in cited blocks)"
        return None, f"reject: {words} not in the cited text and no metric named (no test in cited blocks)"
    if new is None:
        return None, f"reject: {refused} (no test in cited blocks)"
    return new, f"rewrite: {'、'.join(dict.fromkeys(hits))} -> neutral numeric wording (no test in cited blocks)"
