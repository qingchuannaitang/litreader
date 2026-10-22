"""L2 reading note renderer in the user's reference style (portable-literature-note-v2).

Inputs are ONLY validator_v2 output + figure manifest + vision observations. Rejected items never appear
as content; their absence is shown as a gap. Display text is LaTeX-cleaned; raw values live in the
evidence archive (render_evidence).
"""
from __future__ import annotations

import json
import re

from ..analysis.chunking import block_id
from ..analysis.latex import clean
from ..analysis import wording, terms, zh_terms
from ..analysis.schema_v2 import SECTIONS
from ..analysis.validator_v2 import numbers
from ..analysis.chunking import block_text
from .protected_zone import BEGIN, END

NO_VISION = "依据图注与正文，未经视觉模型看图"


class Ctx:
    def __init__(self, blocks, attachment_key):
        self.page = {block_id(b): b.physical_page for b in blocks}
        self.key = attachment_key
        self.abbrs: list[dict] = []
        # body prose already rendered (review fix 15 / review 2): one entry per kept statement; a merged near-duplicate
        # adds its source blocks to the kept entry, whose links are rendered at the end (placeholder tokens)
        self.entries: list[dict] = []
        self.reg: dict[int, int] = {}

    def dup(self, s, neg: bool = False) -> bool:
        """True if statement `s` is merged into prose already rendered (caller then omits it). Merge only when
        - neither is a negative result (registered with neg=True, or negative wording), and
        - the texts are near-duplicates: ≥70 % of its character bigrams are in the earlier one, or the earlier one is
          ≥75 % contained in it and it ≥50 % in the earlier one, and
        - no unique fact is lost: facts = numbers + Latin terms; the kept text carries the superset of facts (the later
          text replaces the earlier one when it holds more facts; PAPER is preferred over INFERENCE on a tie).
        The page links of both are always combined. Otherwise `s` is registered and False is returned."""
        if not s:
            return False
        t = clean(s["text"])
        b, f = _bigrams(t), _facts(t)
        neg = neg or bool(_NEG.search(t))
        if len(b) >= 8 and not neg:
            for e in self.entries:
                if e["neg"]:
                    continue
                common = len(b & e["b"])
                r_new, r_old = common / len(b), common / max(len(e["b"]), 1)
                if not (r_new >= DUP_RATIO or (r_old >= 0.75 and r_new >= 0.5)):
                    continue
                if f <= e["f"] and not (f == e["f"] and s.get("label") == "PAPER" and e["s"].get("label") != "PAPER"):
                    pass                                     # keep the earlier text
                elif e["f"] <= f:
                    e["s"], e["b"], e["f"] = s, b, f         # the later text holds every fact of the earlier one
                else:
                    continue
                e["ids"] += [i for i in s.get("basis_block_ids") or [] if i not in e["ids"]]
                self.reg[id(s)] = self.entries.index(e)
                return True
        self.reg[id(s)] = len(self.entries)
        self.entries.append({"s": s, "b": b, "f": f, "neg": neg, "ids": list(s.get("basis_block_ids") or [])})
        return False

    def resolve(self, line: str) -> str:
        """Placeholders of registered statements -> final text with the combined page links."""
        def one(m):
            e = self.entries[int(m.group(1))]
            return self._st(e["s"], show_label=m.group(2) == "1", ids=e["ids"])
        return _TOKEN.sub(one, line) if "\x00" in line else line

    def url(self, page: int) -> str:
        return f"zotero://open-pdf/library/items/{self.key}?page={page}"

    def links(self, ids, label="") -> str:
        pages = sorted({self.page[i] for i in ids if i in self.page})
        if not pages:
            return ""
        groups, start, prev = [], pages[0], pages[0]
        for p in pages[1:] + [None]:
            if p is not None and p == prev + 1:
                prev = p; continue
            groups.append((start, prev))
            if p is not None:
                start = prev = p
        lab = (label or "").strip()[:6]
        return " · ".join(f"[{lab}p{a}{'' if a == b else f'–{b}'}]({self.url(a)})" for a, b in groups)

    def st(self, s, *, show_label=False, fallback="") -> str:
        """Display one validated statement. A missing (rejected) item renders as `fallback` — by default nothing,
        so placeholder text never reaches the reading note (review fix 12); callers omit the empty line."""
        if not s:
            return fallback
        if id(s) in self.reg:
            return f"\x00{self.reg[id(s)]}|{int(show_label)}\x00"
        return self._st(s, show_label=show_label)

    def _st(self, s, *, show_label=False, ids=None) -> str:
        lab = f"（{s['label']}）" if show_label else ""
        flag = f" `未核对数字：{'、'.join(s['unchecked_numbers'])}`" if s.get("unchecked_numbers") else ""
        return f"{terms.normalize(clean(s['text']), self.abbrs)}{lab}{flag} {self.links(s['basis_block_ids'] if ids is None else ids, s.get('link_label', ''))}".rstrip()


FM_HUMAN = (("中文标题", "title_zh"), ("英文标题", "title_en"), ("作者", "authors"), ("年份", "year"),
            ("期刊", "journal"), ("DOI", "doi"), ("主题", "topic"), ("阅读日期", "read_date"), ("状态", "status"),
            ("课题相关度", "project_relation"))
FM_MACHINE = ("parent_item_key", "attachment_key", "schema", "template_id")


def front_matter(m: dict, conflict: bool = False) -> dict:
    """G10-7: about ten readable properties with Chinese names, `tags`, and one nested `litreader:` block with the
    few ids the app needs to recognise the note. Everything else (hashes, template/project versions, checks,
    metadata sources, levels) is written to the evidence file. Old notes with the flat English keys stay readable
    (gui.runner reads both)."""
    out = {}
    for zh, k in FM_HUMAN:
        v = m.get(k)
        if k == "authors" and conflict:
            v = "UNKNOWN（作者顺序待核对，见笔记开头「论文信息」）"
        if k == "project_relation":
            v = {"LENS_FAILED": "未能评估"}.get(v, v)
        out[zh] = v if v is not None else "UNKNOWN"
    out["tags"] = m.get("tags") or []
    out["litreader"] = {k: m.get(k) for k in FM_MACHINE if m.get(k) is not None}
    return out


def _yaml(d: dict) -> str:
    out = ["---"]
    for k, v in d.items():
        if isinstance(v, dict) and v:   # G10-7: one nested block mapping (the `litreader:` machine fields)
            out.append(f"{k}:")
            out += [f"  {kk}: {'null' if vv is None else json.dumps(vv, ensure_ascii=False)}" for kk, vv in v.items()]
        elif isinstance(v, list):
            out.append(f"{k}:" + ("" if v else " []"))
            out += [f"  - {json.dumps(x, ensure_ascii=False)}" for x in v]
        elif v is None:
            out.append(f"{k}: null")
        else:
            out.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    return "\n".join(out + ["---", ""])


DUP_RATIO = 0.7
_TOKEN = re.compile("\x00(\\d+)\\|([01])\x00")
_NEG = re.compile(r"无显著|不显著|无统计学|无差异|未见差异|差异不显著|未达|未发现|没有显著|无相关|\bns\b|[pP]\s*[>≥]\s*0?\.\d")
_LAT = re.compile(r"[A-Za-z][A-Za-z0-9\-]+")


def _facts(t: str) -> set:
    """What a merge must never lose: every number and every Latin term (model/tool/metric names, abbreviations)."""
    return set(numbers(t)) | {w.lower() for w in _LAT.findall(t)}
_PUNCT = re.compile(r"[\s，。；：、！？（）()“”\"'·,.;:!?\[\]【】—-]")


def _bigrams(t: str) -> set:
    t = _PUNCT.sub("", t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


QUESTION_DEFAULT = {"s1": "为什么值得研究？", "s2": "研究如何设计？", "s3": "具体怎么做？", "s4": "结果说明了什么？",
                    "s5": "它解决了什么问题？"}


def questionize(h: str, tail: str = "说明了什么？") -> str:
    """Every model-written heading is a question (review fix 11). Already a question → unchanged."""
    h = (h or "").strip()
    if not h or h.endswith(("？", "?")):
        return h
    return h.rstrip("。.；;：:，, ") + "——" + tail


def tidy(md: str) -> str:
    """Punctuation clean-up of the assembled body (review fix 17): doubled sentence punctuation."""
    md = re.sub(r"[。.]\s*([；;])", r"\1", md)
    md = re.sub(r"。{2,}", "。", md)
    return re.sub(r"([；;])\s*[；;]", r"\1", md)


UNREADABLE = "[符号无法识别]"
_FFFD_P = re.compile(r"\ufffd(?=\s*[=＝<>≤≥＜]\s*0?\.\d)")      # MinerU's italic p before a p-value


def unreadable_symbols(md: str) -> tuple[str, int]:
    """G7-12: U+FFFD never reaches the reader. Before a p-value it is the italic p MinerU lost; anywhere else it becomes
    「[符号无法识别]」. Returns (text, number of unreadable symbols that could not be restored)."""
    md = _FFFD_P.sub("p", md)
    n = md.count("\ufffd")
    md = re.sub(r"\ufffd+", UNREADABLE, md)
    return merge_unreadable(md), n


MATH_NOTICE = "图注中的数学变量未能识别，见原页"
_PAGE_LINK = re.compile(r"\[原[^\]\n]*?p\d+\]\([^)\s]+\)")


def merge_unreadable(md: str) -> str:
    """G8-8: two or more 「[符号无法识别]」 in one caption/paragraph collapse into a single notice with a page link
    (the line's own [原…pN] link, else the nearest one above it)."""
    lines = md.split("\n")
    for i, ln in enumerate(lines):
        if ln.count(UNREADABLE) < 2:
            continue
        link = next((m.group(0) for j in range(i, max(-1, i - 15), -1) for m in [_PAGE_LINK.search(lines[j])] if m), "")
        t = re.sub(r"\s*" + re.escape(UNREADABLE) + r"\s*", " ", ln)
        t = re.sub(r" {2,}", " ", t).rstrip()
        lines[i] = t + f"（{MATH_NOTICE}{' ' + link if link else ''}）"
    return "\n".join(lines)


_NUM_ = r"\d+(?:\.\d+)?"


def units(md: str) -> str:
    """G7-12: '3.8° ± 0.5°' -> '3.8 ± 0.5°', '4.2±0.6°' -> '4.2 ± 0.6°', same for %; never inside links/embeds."""
    def fix(seg: str) -> str:
        seg = re.sub(rf"({_NUM_})\s*([°%])\s*±\s*({_NUM_})\s*\2", r"\1 ± \3\2", seg)
        return re.sub(rf"({_NUM_})\s*±\s*({_NUM_})", r"\1 ± \2", seg)
    parts = re.split(r"(\[\[[^\]]*\]\]|\]\([^)]*\))", md)
    return "".join(p if i % 2 else fix(p) for i, p in enumerate(parts))


EMPTY_CELLS = {"", "—", "-", "–", "--", "N/A", "NA"}


def _table(t) -> list[str]:
    def esc(x):
        x = clean(str(x)).strip()
        return "UNKNOWN（此格无数据）" if x in EMPTY_CELLS else x.replace("|", "\\|").replace("\n", " ")
    return [f"**{esc(t['title'])}**（{t['label']}）", "", "| " + " | ".join(map(esc, t["columns"])) + " |",
            "|" + "---|" * len(t["columns"])] + ["| " + " | ".join(map(esc, r)) + " |" for r in t["rows"]]


FIG_W = 760
ROW_W = 680   # review 4: a 3-crop row summing to 760 px wrapped in Obsidian's readable-width pane (DeepGaitLab 图5)


def figure_rows(parts: list[dict], paths: list[str]) -> list[list[tuple[str, int]]]:
    """Sub-figure crops side by side as on the PDF page (review 2: small panels were each blown up to 760 px).
    A path '<id>-<i>.<ext>' is part i; parts on the same page whose vertical extents overlap ≥50 % share a row; each
    width is proportional to its bbox width. Without bbox/index information every crop is its own 760-px row."""
    rows: list[list[tuple[str, dict | None]]] = []
    for p in paths:
        mm = re.search(r"-(\d+)\.[A-Za-z0-9]+$", p)
        part = parts[int(mm.group(1)) - 1] if mm and 0 < int(mm.group(1)) <= len(parts) else None
        bb = (part or {}).get("bbox_norm")
        if rows and bb and rows[-1][-1][1] and rows[-1][-1][1].get("bbox_norm"):
            prev = rows[-1][-1][1]
            pb = prev["bbox_norm"]
            ov = min(bb[3], pb[3]) - max(bb[1], pb[1])
            if prev["physical_page"] == part["physical_page"] and ov >= 0.5 * min(bb[3] - bb[1], pb[3] - pb[1]):
                rows[-1].append((p, part)); continue
        rows.append([(p, part)])
    out = []
    for row in rows:
        ws = [(x[1] or {}).get("bbox_norm") for x in row]
        if not all(ws):
            out += [[(x[0], FIG_W)] for x in row]
            continue
        tot = max(sum(b[2] - b[0] for b in ws), 740)
        lo, budget = (300, FIG_W) if len(row) == 1 else (120, ROW_W)
        out.append([(x[0], min(FIG_W, max(lo, round(budget * (b[2] - b[0]) / tot)))) for x, b in zip(row, ws)])
    return out


def gloss(md_body: str, abbrs: list[dict]) -> str:
    """Gloss each abbreviation at its first use in body prose (skipping links/embeds/headings)."""
    # verbatim text is never glossed: 「原文摘录」 and the original-figure caption line
    protect = re.compile(r"(\]\([^)]*\)|!\[\[[^\]]*\]\]|\[\[[^\]]*\]\]|`[^`]*`|^#.*$|^\|[-|: ]+\|$|「[^」\n]*」|^\*真实原图摘录.*$)", re.M)
    done = set()
    parts = protect.split(md_body)
    for i in range(0, len(parts), 2):
        for a in abbrs:
            if a["abbr"] in done:
                continue
            pat = re.compile(rf"(?<![A-Za-z]){re.escape(a['abbr'])}(?![A-Za-z（(])")
            m = pat.search(parts[i])
            if m and a["zh"] in parts[i][max(0, m.start() - len(a["zh"]) - 2):m.start()]:
                done.add(a["abbr"])  # already glossed as 中文（ABBR）
                continue
            if m:
                zh = a["zh"].replace(a["abbr"], "").strip(" ：:（）()") if a["abbr"] in a["zh"] else a["zh"]
                if zh:   # “BEDLAM（BEDLAM 合成数据集）” -> “BEDLAM（合成数据集）”
                    parts[i] = parts[i][:m.end()] + f"（{zh}）" + parts[i][m.end():]
                done.add(a["abbr"])
    return "".join(parts)


def _builtin_general():
    from ..templates import builtin
    return builtin.load("main.general")


def _heading(sec, S) -> str:
    suf = (S.get(sec.data) or {}).get("heading_suffix") or "" if sec.data in ("s1", "s2", "s3", "s4", "s5") else ""
    if suf:
        suf = questionize(clean(suf), QUESTION_DEFAULT.get(sec.data, "说明了什么？"))
    if sec.suffix == "colon":
        h = sec.title + (f"：{suf}" if suf else "")
    elif sec.suffix == "append":
        h = sec.title + (suf or sec.suffix_default)
    else:
        h = sec.title
    return h


_PANEL_LEAD = re.compile(r"^(?:图\s*\d*[A-Za-z]?|面板\s*[A-H]|[A-H]\s*面板|上图|中图|下图|左图|右图|该图|此图|本图)\s*(?:中|为|显示|展示)?[，,：:]?\s*")


_AXIS_LEAD = re.compile(r"^(?:(?:纵轴|横轴|[xyXY]\s*轴)\s*(?:为|表示|是|显示)?|(?:分别|依次)?(?:展示|显示|呈现)了?)\s*")
_CHART = r"(?:箱线|箱形|箱|柱状|条形|折线|散点|热力?|雷达|饼|示意|流程|统计|对比|分组|堆叠)?"
_GENERIC_TOPIC = re.compile(r"^(?:(?:该|此|本)?图?\s*(?:包含|展示|显示|由|为|共有|共|是)?\s*)?"
                            r"(?:[一二三四五六七八九十两\d]+\s*(?:幅|个|张|组|块|列|行|部分)\s*)?(?:分图|子图|面板)?\s*的?\s*"
                            + _CHART + r"\s*(?:图|面板|分图|子图)?\s*(?:组成|构成)?$")


def generic_topic(t: str) -> bool:
    """G10-2: a topic that only names the chart type / panel count (“三幅箱线图”, “两个面板”) says nothing specific."""
    t = (t or "").strip("，,：:。 ")
    return not t or bool(_GENERIC_TOPIC.match(t))


def vision_topic(finding: str, n: int = 24) -> str:
    """First specific clause of a vision reading, without panel / axis lead-ins, as a short heading topic.
    G10-2: clauses that only name the chart type (“三幅箱线图”) are skipped."""
    t = clean(finding or "").strip()
    for sent in re.split(r"[。；;！!？?\n]", t):
        for cl in re.split(r"[，,]", sent):
            cl = _PANEL_LEAD.sub("", cl.strip()).strip("，,：: ")
            cl = _AXIS_LEAD.sub("", cl).strip("，,：: ")
            if len(cl) >= 4 and not generic_topic(cl):
                return cl[:n].rstrip("的和与及、")
    return ""


def _claim_key(t: str) -> str:
    return _PUNCT.sub("", clean(t or "")).lower()


def dedupe_claims(ok: list, unv: list, bad: list) -> tuple[list, list, list]:
    """G10-5: a vision claim is shown once. Exact repeats (same wording after punctuation is removed) collapse to the
    first; a claim that is also listed as a conflict, or ≥60% the same wording (bigrams) as one, is shown only in the
    conflict callout; a 未核对 claim repeating a 主要发现 claim exactly is dropped. Similar but distinct consistent claims
    (髋内收 vs 髋内旋) are all kept."""
    def near(a, b):
        ba, bb = _bigrams(a), _bigrams(b)
        return a == b or (ba and bb and len(ba & bb) / max(len(ba), len(bb)) >= 0.6)
    seen: list[str] = []
    out_bad, out_ok, out_unv = [], [], []
    for x in bad:
        k = _claim_key(x["claim"])
        if k not in seen:
            seen.append(k)
            out_bad.append(x)
    bad_keys = list(seen)
    for src, dst in ((ok, out_ok), (unv, out_unv)):
        for x in src:
            k = _claim_key(x["claim"])
            if k and k not in seen and not any(near(k, b_) for b_ in bad_keys):
                seen.append(k)
                dst.append(x)
    return out_ok, out_unv, out_bad


def order_hints(seq: list[tuple]) -> dict[str, str]:
    """G10-4: figures stay in the section that discusses them, so 图8 may come before 图2. seq = (is_table, number,
    id) in note order -> {id: "（先于图2出现）"} for every figure/table followed later by a lower-numbered one of the
    same kind (the lowest such number is named)."""
    out = {}
    for i, (kind, n, fid) in enumerate(seq):
        if not isinstance(n, int) or n >= 10 ** 6:
            continue
        later = [m for k, m, _ in seq[i + 1:] if k == kind and isinstance(m, int) and m < n]
        if later:
            out[fid] = f"（先于{'表' if kind else '图'}{min(later)}出现）"
    return out


def presumed_number(m: dict, manifest: list[dict]) -> tuple[int, int | None, int | None] | None:
    """G7-12: an uncaptioned, unnumbered figure whose position fits exactly one missing figure number N (figure N-1 is on
    an earlier-or-same page, figure N+1 on a later-or-same page, both numbered) -> (N, page of N-1, page of N+1).
    Pages are physical pages, so a figure section placed at the end (methods figures) does not count as a neighbour
    unless its page brackets the orphan."""
    if m.get("kind") != "figure" or m.get("number"):
        return None
    pages = {}
    for x in manifest:
        if x.get("kind") == "figure" and str(x.get("number") or "").isdigit():
            pages[int(x["number"])] = min(p["physical_page"] for p in x["parts"]) if x.get("parts") else None
    if not pages or not m.get("parts"):
        return None
    pg = min(p["physical_page"] for p in m["parts"])
    hits = []
    for n in range(2, max(pages)):          # a real gap only: figures n-1 and n+1 both exist
        if n in pages or n - 1 not in pages or n + 1 not in pages:
            continue
        b, a = pages[n - 1], pages[n + 1]
        if b is not None and a is not None and b <= pg <= a:
            hits.append((n, b, a))
    return hits[0] if len(hits) == 1 else None


def render(v2, *, blocks, manifest, vision_obs, figure_paths, attachment_key, parent_key, e_level,
           translation_notice, link_mechanism_verified, read_date, evidence_link, model_info,
           crosscheck: dict | None = None, zotero_meta: dict | None = None, top_unknowns: int = 5,
           template=None, modules=(), provenance: dict | None = None, layout_warnings: list | None = None,
           project: dict | None = None, lens: dict | None = None) -> str:
    """Template-driven block assembler. `template` = parsed main Template (default: built-in main.general, which
    reproduces the pre-Stage-6 renderer byte for byte). Templates choose order/titles; every block's content and
    every gate is code (templates/layout.py)."""
    from ..templates import layout as layout_mod
    lay = layout_mod.build(template or _builtin_general(), list(modules))
    _ids: set = set()
    lay.modules = [m for m in lay.modules if not (m.id in _ids or _ids.add(m.id))]
    if layout_warnings is not None:
        layout_warnings.extend(lay.warnings)
    secs = lay.sections
    c = Ctx(blocks, attachment_key)
    c.abbrs = v2.abbreviations
    zm = zotero_meta or {}
    meta = {k: (m.get("value") if m["label"] == "PAPER" else None) for k, m in v2.meta.items()}
    src = {k: ("PAPER" if v else None) for k, v in meta.items()}
    for k in ("authors", "journal", "title_en", "year", "doi"):   # Zotero metadata outranks text extraction
        if zm.get(k):
            meta[k], src[k] = zm[k], "ZOTERO"
    ac = zm.get("authors_conflict")
    if ac:   # Zotero and PDF disagree on the first author: never pick one silently (review fix 10)
        meta["authors"], src["authors"] = None, "CONFLICT"
    authors_disp = (f"UNKNOWN（作者顺序冲突：Zotero 首位 {ac['zotero_first']}，PDF 首位 {ac['pdf_first']}；请在 Zotero 中核对）"
                    if ac else None)
    parent_key = parent_key or zm.get("parent_key")
    crosscheck = crosscheck or {}
    zh = clean(meta["title_zh"]) if meta["title_zh"] else "UNKNOWN"
    en = clean(meta["title_en"]) if meta["title_en"] else None
    d, S = v2.data, v2.data["sections"]
    a = v2.data.get("_aux", {})
    machine = {   # G10-7: program fields leave the front matter; kept in the evidence file (笔记元数据)
        "note_type": "科研精读笔记", "schema": "portable-literature-note-v2",
        "parent_item_key": parent_key, "attachment_key": attachment_key, "doi": meta["doi"] or "UNKNOWN",
        "title_zh": zh, "title_en": en or "UNKNOWN", "title": f"{zh}（{en or '英文原题 UNKNOWN'}）",
        "authors": clean(meta["authors"]) if meta["authors"] else (authors_disp or "UNKNOWN"), "year": meta["year"] or "UNKNOWN",
        "journal": meta["journal"] or "UNKNOWN", "topic": a.get("topic") or "UNKNOWN", "read_date": read_date,
        "reading_level": "L2", "extraction_level": e_level,
        "source_version": translation_notice or "原文版本", "status": "待审阅",
        "figure_check": ("MINERU_CROPS_VISION_CROSSCHECKED_TEXT" if crosscheck else "MINERU_CROPS_VISION_UNCHECKED") if vision_obs else "MINERU_CROPS_TEXT_ONLY_NO_VISION",
        "metadata_source": {k: v for k, v in src.items() if v} or "TEXT_ONLY",
        "link_check": "MECHANISM_VERIFIED_PER_LINK_UNVERIFIED" if link_mechanism_verified else "UNVERIFIED",
        "project_id": project["project_id"] if project else None, "project_version": project["version"] if project else None,
        "project_relation": _relation(project, lens),
        **({"project_snapshot_sha256": project["sha256"]} if project else {}),
        "tags": ["文献精读"] + [t for t in a.get("tags", []) if isinstance(t, str)][:5]}
    if provenance:   # spec §3.4 template fields; written by code, never by a template
        for k in ("template_id", "template_version", "template_sha256", "template_modules", "study_type"):
            if k in provenance:
                machine[k] = provenance[k]
    ymap = front_matter(machine, conflict=bool(ac))
    v2.note_meta = machine
    y = _yaml(ymap)
    from ..templates import vocab
    st_code = (provenance or {}).get("study_type")
    paper_st = clean(meta["study_type"]) if meta.get("study_type") else None
    if st_code:   # info bar shows the same study type as the frontmatter (review fix 14)
        study_disp = f"{vocab.STUDY_TYPES.get(st_code, st_code)}（{st_code}）" + (f"；原文自述：{paper_st}" if paper_st else "")
    else:
        study_disp = paper_st or "UNKNOWN"
    # one UNKNOWN list for every count in the note (review fix 13): fields Zotero resolved are not "unknown"
    resolved = {f"元数据 {k}" for k, v in src.items() if v == "ZOTERO"}
    res_words = {"title_en": ("英文原题", "英文题名", "英文标题", "英文题目"), "authors": ("作者", "作者列表", "第一作者"),
                 "doi": ("DOI",), "journal": ("期刊", "期刊名", "期刊名称"), "year": ("年份", "发表年份", "出版年份")}
    res_kw = [w for k, ws in res_words.items() if src.get(k) == "ZOTERO" for w in ws]
    res_re = (re.compile(r"^(?:" + "|".join(map(re.escape, res_kw)) + r")(?:缺失|未知|不明|未报告|UNKNOWN)?$", re.I)
              if res_kw else None)
    for u in v2.unknowns:
        it = re.sub(r"[\s*（）()：:。]", "", clean(u.get("item") or ""))
        if u["item"] in resolved or (res_re and res_re.match(it)):   # the writer's own “英文原题” item counts too
            u["resolved_by"] = "ZOTERO"
        if ac and u["item"] == "元数据 authors":
            u["resolved_by"] = "AUTHOR_CONFLICT_ITEM"   # superseded by the explicit conflict item
        if st_code and u["item"] == "元数据 study_type":
            u["resolved_by"] = "CLASSIFIER"   # review 5: the info bar already shows the classifier's study type
    unks = [u for u in v2.unknowns if not u.get("resolved_by") and not u.get("malformed")]
    v2.stats["unknowns_in_note"] = len(unks)
    L = [f"# {zh}", ""]
    en = clean(meta["title_en"]) if meta["title_en"] else None
    # plain Markdown subtitle (readable without custom CSS)
    L += [f"*{en}*" if en else "*英文原题 UNKNOWN（本附件为中文译本，未含英文题名；需 Zotero 元数据补全）*", ""]
    SUB_END = len(L)
    first = secs[0]
    deep = next((s for s in secs if "evaluation" in s.blocks), None) or next((s for s in secs if "author_conclusion" in s.blocks), first)

    def h_info():
        return ["> [!info] 论文信息",
                f"> **作者／年份：** {clean(meta['authors']) if meta['authors'] else (authors_disp or 'UNKNOWN')}{'（Zotero）' if src.get('authors') == 'ZOTERO' else ''} · {meta['year'] or 'UNKNOWN'}　**期刊：** {meta['journal'] or 'UNKNOWN'}  ",
                f"> **阅读层级：** L2 标准科研精读　**主题分类：** {a.get('topic') or 'UNKNOWN'}  ",
                f"> **抽取完整度：** {e_level}；{translation_notice or ''}  ",
                f"> **研究类型：** {study_disp}　**DOI：** {meta['doi'] or 'UNKNOWN'}", "",
                f"[查看附件首页]({c.url(1)})", ""]

    def h_nav():
        return [f"**按需阅读：** [[#^three-minute|三分钟了解论文]] · [[#{_heading(first, S)}|十分钟读懂研究]] · "
                f"[[#{_heading(deep, S)}|深度科研分析]] · [[{evidence_link}|独立证据与溯源档案]]", ""]

    def h_three():
        tm = d["three_minute"]
        key = c.st(tm["key_result"])
        if not key:   # never a placeholder: a verbatim verified result, else an explicit UNKNOWN
            fx = min(result_facts(), key=lambda f: c.page.get(f.get("block_id"), 0), default=None)   # earliest result
            key = (f"原文摘录：「{clean(f_ctx(fx))}」 {c.links([fx['block_id']], '结果')}".rstrip() if fx
                   else "UNKNOWN（无通过核对的结果陈述，见证据档案）")
        line = lambda lab, v: [f"> **{lab}：** {v}  "] if v else []
        return ["> [!abstract] 三分钟了解论文",
                *line("研究什么", c.st(tm["what"])),
                *line("怎么研究", c.st(tm["how"])),
                f"> **最重要的结果（PAPER）：** {key}  ",
                *line("通用科研价值（INFERENCE，未关联课题）", c.st(tm["value"])),
                *([f"> **当前课题价值（INFERENCE，课题 v{project['version']}）：** 相关程度{lens['relevance']['level']}——"
                   f"{clean(lens.get('current_value') or lens['relevance']['reason'])}  "] if _lens_ok(project, lens) else []),
                *([f"> **最需警惕：** {c.st(tm['caution'], show_label=True)}"] if tm.get("caution") else []),
                "", "^three-minute", ""]

    def h_one():
        return [f"**最值得长期记住的一句话（独立评价）：** {c.st(d['one_liner'])}", ""] if d.get("one_liner") else []

    def h_pdf():
        return [f"[📄 Zotero 原始 PDF]({c.url(1)}) · [[{evidence_link}|完整证据与{len(unks)}项UNKNOWN]]", ""]

    def h_conv():
        mech = "已核验（据用户报告）" if link_mechanism_verified else "未核验"
        fig_note = (f"本页图表为 MinerU 版面检测的真实矩形裁剪，未重绘或改字；图的“主要发现”由视觉模型 {model_info.get('vision', 'UNKNOWN')} 读图得到，未经人工核对。"
                    if vision_obs else "本页图表为 MinerU 真实矩形裁剪；未经视觉模型看图。")
        return ["> [!note] 阅读约定",
                "> **PAPER**指本文原文直接报告（数字均已与原文块逐一核对）；**INFERENCE**指整理者（模型）的科研评价或建议；**UNKNOWN**指缺失、冲突及尚不能确认的事实。"
                f"{fig_note}正文模型 {model_info.get('text')}。", "",
                f"Zotero 页码链接机制{mech}；本页各条页码链接均**未逐条点击核验（UNVERIFIED）**。", ""]

    bmap = {block_id(b): b for b in blocks}
    POP = re.compile(r"MCI|轻度认知|卒中|stroke|ACLR|患者|patient|临床|病", re.I)

    def f_ctx(f):
        return f.get("context") or f.get("value") or ""

    def result_facts():
        """Verified PAPER facts that look like results (a number with ±, %, a decimal or a test statistic),
        clinical-population results first (review fix 8)."""
        out = []
        for f in v2.facts:
            ctx = clean(f_ctx(f))
            if not re.search(r"\d", str(f.get("value") or "")) or not re.search(r"±|%|\d\.\d|[pP]\s*[<=>]", ctx):
                continue
            btxt = clean(block_text(bmap[f["block_id"]])) if f.get("block_id") in bmap else ""
            out.append((0 if POP.search(ctx + btxt) else 1, c.page.get(f.get("block_id"), 0), f))
        return [f for _, _, f in sorted(out, key=lambda x: (x[0], x[1]))]

    HEADER = {"info_callout": h_info, "nav": h_nav, "three_minute": h_three, "one_liner": h_one, "pdf_nav": h_pdf,
              "reading_convention": h_conv}
    for b in lay.header:
        L += HEADER[b]()

    figs_by_sec: dict[str, list] = {}
    shown = {s.data for s in secs if "figures" in s.blocks and s.data}
    fallback_sec = next((s.data for s in secs if "figures" in s.blocks and s.data), None)
    if fallback_sec is None:   # gate: every real figure is shown somewhere
        tgt = next(s for s in secs if s.data == "s4")
        tgt.blocks.append("figures")
        shown, fallback_sec = {"s4"}, "s4"
    man = {m["id"]: m for m in manifest}

    def fig_num(f) -> tuple:
        """G8-6 sort key: figures before tables, then number (a presumed number counts), then first page."""
        m = man.get(f["id"]) or {}
        n = m.get("number") or (str(g[0]) if (g := presumed_number(m, manifest)) else "")
        pages = [p["physical_page"] for p in m.get("parts") or []] or [0]
        return (m.get("kind") != "figure", int(n) if str(n).isdigit() else 10 ** 6, min(pages))

    sec_of = {}
    for f in v2.figures:
        sec_of[f["id"]] = f["section"] if f["section"] in shown else fallback_sec
    by_num = {str(fig_num(f)[1]): f for f in v2.figures if not fig_num(f)[0]}
    for f in v2.figures:     # a presumed figure N goes right after figure N-1 (it has no caption to place it by)
        m = man.get(f["id"]) or {}
        g = presumed_number(m, manifest) if not m.get("number") else None
        if g and str(g[0] - 1) in by_num:
            sec_of[f["id"]] = sec_of[by_num[str(g[0] - 1)]["id"]]
    for f in sorted(v2.figures, key=fig_num):
        figs_by_sec.setdefault(sec_of[f["id"]], []).append(f)
    early_hint = order_hints(
        [(fig_num(f)[0], fig_num(f)[1], f["id"]) for sd in list(dict.fromkeys([s.data for s in secs] + list(figs_by_sec)))
         for f in figs_by_sec.get(sd, [])])
    text_all = clean("\n".join(block_text(b) for b in blocks))

    def fig_block(f) -> list[str]:
        m = man[f["id"]]
        guess = presumed_number(m, manifest) if not m["number"] else None
        num = ("图" if m["kind"] == "figure" else "表") + (m["number"] or (f"{guess[0]}（推定，图注缺失）" if guess else "（无编号）"))
        cap = clean(m["caption"]).strip()
        if clean(f.get("title") or ""):
            ttl = questionize(clean(f["title"]))
        else:   # short caption phrase, made a question
            short = re.split(r"[。.；;:：]", re.sub(r"^(图|表|Fig(?:ure)?\.?|Table)\s*\d+[A-Za-z]?\s*[.:：、|｜]?\s*", "", cap))[0].strip()[:30]
            if not short:   # G8-7/G10-2: no title, no caption -> a specific vision title, else the writer's finding,
                o = (vision_obs or {}).get(f["id"]) or {}   # else the first specific clause of the vision reading
                short = next((t for t in (vision_topic(o.get("title") or ""), vision_topic(f.get("finding") or ""),
                                          vision_topic(o.get("finding") or "")) if t), "")
            ttl = questionize(short) if short else f"这张{'图' if m['kind'] == 'figure' else '表'}显示了什么？"
        out = [f"### {num}{early_hint.get(f['id'], '')}｜{ttl}", ""]
        for row in figure_rows(m["parts"], figure_paths.get(f["id"], [])):
            out.append(" ".join(f"![[{p}|{w}]]" for p, w in row))
        pages = sorted({p["physical_page"] for p in m["parts"]})
        pg = "／".join(f"物理p{p}" for p in pages)
        flags = "；分图已合并" if "SUBFIGURES_MERGED" in m["flags"] else ("；跨页续表按推定合并" if "CONTINUATION_ASSUMED" in m["flags"] else "")
        out += ["", f"*真实原图摘录，{cap.rstrip('。.；; ') or '无图注'}；PDF **{pg}**，MinerU 矩形裁剪，未重绘或改字{flags}。*[打开原页]({c.url(pages[0])})", ""]
        if "UNCAPTIONED_ORPHAN" in m["flags"] and guess:
            n, before, after = guess
            ctx = "、".join(x for x in (before and f"图{n - 1} 在物理p{before}", after and f"图{n + 1} 在物理p{after}") if x)
            out += [f"> [!warning] 图注缺失，图号为推定：MinerU 在 PDF {pg} 识别出这张图，但没有找到它的图注或正文引用。"
                    f"全文已编号的图唯独缺少图{n}，且这张图的位置正好在其前后（{ctx}），因此推定为图{n}。"
                    "推定可能有误（也可能是附图或被误识别的版面元素），请点“打开原页”核对。",
                    f"> 图注请在 Zotero 原页阅读：[{pg}]({c.url(pages[0])})。本笔记不转录、不猜测图注；读图观察仅凭图片本身。", ""]
            v2.unknowns.append({"item": f"{f['id']} 图号（推定为图{n}）", "why": f"图注缺失；按前后图位置推定为图{n}，需对照 {pg} 原页确认",
                                "impact": 1, "impact_tags": ["图注"]})
        elif "UNCAPTIONED_ORPHAN" in m["flags"]:
            out += [f"> [!warning] 无图注、无编号的图块：MinerU 在 PDF {pg} 识别出这些图片区域，但没有找到图注或正文引用。"
                    "它们可能是公式、表格片段、标志或页面装饰被识别成了图片，也可能是图注漏识别的图；"
                    "未并入任何编号图，请点“打开原页”核对。",
                    f"> 图注请在 Zotero 原页阅读：[{pg}]({c.url(pages[0])})。解析结果（MinerU）中没有这段图注，"
                    "本笔记不转录、不猜测图注和图号；读图观察仅凭图片本身。", ""]
        elif "UNCAPTIONED" in m["flags"] and m["kind"] == "figure":
            how = "图号由正文引用推断" if "NUMBER_INFERRED_FROM_TEXT" in m["flags"] else "图号未知"
            out += [f"> [!warning] 图注未识别：解析结果（MinerU）中没有找到这张图的图注，{how}。"
                    f"图注请在 Zotero 原页阅读：[{pg}]({c.url(pages[0])})；本笔记不转录、不猜测图注。", ""]
        obs = (vision_obs or {}).get(f["id"])
        conflict_lines = []
        known = clean(m["caption"]) + " " + text_all

        def zh(t: str) -> str:
            """vision text -> Chinese with English in parentheses (deterministic post-check, recorded)."""
            new, recs = zh_terms.bilingual(clean(t), known)
            for r in recs:
                v2.wording.append({"where": f"figure.{f['id']}.vision", "original": r["phrase"], "result": r["result"],
                                   "rule": "英文词组→中文（English）" if r["rule"].endswith("glossary") else "英文词组未译，已标注",
                                   "gate": r["rule"]})
            return new
        if obs:
            claims = crosscheck.get(f["id"]) or [{"claim": obs["finding"], "verdict": "UNVERIFIABLE", "page": None,
                                                  "quote": None, "reason": "未做交叉核对"}]
            ok, demoted = [], []
            for x in claims:
                if x["verdict"] != "CONSISTENT":
                    continue
                new, rule = wording.gate(x["claim"], x.get("quote") or "")
                if rule:
                    v2.wording.append({"where": f"figure.{f['id']}.vision", "original": x["claim"], "result": new, "rule": rule,
                                       "gate": "wording.deterministic(vision)"})
                if new:
                    ok.append({**x, "claim": new})
                else:   # comparative not supported: shown as an unverified reading, never as PAPER
                    demoted.append(x)
            unv = [x for x in claims if x["verdict"] == "UNVERIFIABLE"] + demoted
            bad = [x for x in claims if x["verdict"] == "CONTRADICTED"]
            ok, unv, bad = dedupe_claims(ok, unv, bad)   # G10-5: each vision claim appears once
            parts_ = []
            if ok:
                parts_.append(f"**主要发现（PAPER，图像观察｜{obs['model']} 读图，已与正文/表格交叉核对）：** "
                              + "；".join(f"{zh(x['claim'])} [核对p{x['page']}]({c.url(x['page'])})" for x in ok))
            if unv:
                parts_.append(f"**未核对（{obs['model']} 读图，正文/表格无法确认）：** " + "；".join(zh(x["claim"]) for x in unv))
            only_vis = sorted(numbers(obs["finding"]) - numbers(clean(m["caption"]) + " " + text_all))
            if only_vis:
                parts_.append(f"`仅视觉读出、正文/图注未见的数字：{'、'.join(only_vis)}`")
            find = " ".join(parts_)
            if bad:   # G10-5: one callout per figure, one numbered entry per conflicting claim
                conflict_lines.append(f"> [!warning] 读图与原文不一致 {len(bad)} 处（{obs['model']} 读图，{num}，"
                                      f"[原图p{pages[0]}]({c.url(pages[0])})；不作为 PAPER 事实，以原文为准待人工复核）")
                for i, x in enumerate(bad, 1):
                    conflict_lines += [">", f"> {i}. **读图：** {zh(x['claim'])}  ",
                                       f">    **原文（{x['block_id']}，物理p{x['page']}）：** 「{clean(x['quote'])}」 "
                                       f"[原文p{x['page']}]({c.url(x['page'])})  ",
                                       f">    **核对说明：** {clean(x['reason'])}"]
                conflict_lines.append("")
        elif m["kind"] == "table" and f.get("finding"):
            find = f"**主要发现（PAPER，依据表格文本，已逐数核对）：** {c.st(f['finding'])}"
        elif f.get("finding"):
            find = f"**主要发现（PAPER，{NO_VISION}）：** {c.st(f['finding'])}"
        else:
            find = ""
        tail = "".join([f" **解读（INFERENCE）：** {c.st(f['interpretation'])}" if f.get("interpretation") else "",
                        f" **局限：** {c.st(f['limitation'])}" if f.get("limitation") else "",
                        f" **图中不可读：** {zh(obs['unreadable'])}" if obs and obs.get("unreadable") else ""])
        txt = (find + tail).strip()
        return out + ([txt, ""] if txt else []) + conflict_lines

    extra = d.get("extra_sections") or {}
    mfields = d.get("module_fields") or {}

    # G7-12: each module is rendered once (duplicates in the layout are dropped); a field shared by several modules is
    # filled from whichever has a value BEFORE anything is called UNKNOWN; missing fields are listed once per module.
    seen_mods: set = set()
    shown_fields: set = set()
    field_texts: list[tuple[str, set]] = []     # (field label, bigrams of its value) for G8-5 overlap checks

    def overlaps_field(p) -> bool:
        """G8-5: a leftover module paragraph that repeats a shown field (same label prefix such as 「对照方法…」/
        「消融…」, or ≥40% of its wording) is dropped, so a fact is never shown twice with different labels."""
        t = clean(p.get("text") or "")
        tb = _bigrams(t)
        for lab, fb in field_texts:
            if lab and (t.startswith(lab) or t.startswith(lab[:2])):
                return True
            if tb and fb and len(tb & fb) / min(len(tb), len(fb)) >= 0.4:
                return True
        return False

    def module_lines(m) -> list[str]:
        out = []
        if m.id in seen_mods:
            return out
        seen_mods.add(m.id)
        for ms in m.adds_sections:
            out += [f"### {ms.title}", ""]
            for b in ms.blocks:
                if b == "module_fields":
                    missing = []
                    for f in m.adds_fields:
                        if f["name"] in shown_fields:
                            continue
                        mv = mfields.get(f["name"])
                        if not mv:
                            missing.append(f["label"])
                            continue
                        shown_fields.add(f["name"])
                        field_texts.append((re.split(r"[与和及/、]", clean(f["label"]))[0], _bigrams(clean(mv.get("text") or ""))
                                            if isinstance(mv, dict) else set()))
                        out.append(f"- **{f['label']}：** " + ("（同上文，不重复）" if c.dup(mv) else c.st(mv, show_label=True)))
                    if missing:
                        out.append(f"- **原文未报告或未通过核对（UNKNOWN）：** {'、'.join(missing)}")
                    out.append("")
                elif b == "paragraphs":
                    for p in (extra.get(ms.id) or {}).get("paragraphs") or []:
                        if overlaps_field(p):
                            v2.duplicates.append({"where": f"module.{m.id}", "text": p.get("text"),
                                                  "reason": "repeats a module field (G8-5)"})
                            continue
                        if not c.dup(p):
                            out += [c.st(p, show_label=p["label"] == "INFERENCE"), ""]
        return out

    def block(b, sec) -> list[str]:
        sd = S.get(sec.data) or {} if sec.data else (extra.get(sec.id) or {})
        if b == "paragraphs":
            return [x for p in sd.get("paragraphs") or [] if not c.dup(p)
                    for x in (c.st(p, show_label=p["label"] == "INFERENCE"), "")]
        if b == "supports":
            sup = [c.st(x) for x in sd.get("supports") or [] if x and not c.dup(x)]
            cna = [c.st(x) for x in sd.get("cannot_answer") or [] if x]
            parts_ = ([f"**本文能支持的认识：** {'；'.join(sup)}"] if sup else []) + ([f"**本文不能回答：** {'；'.join(cna)}"] if cna else [])
            return ["　".join(parts_), ""] if parts_ else []
        if b == "tables":
            return [x for t in sd.get("tables") or [] for x in _table(t) + ["", c.links(t["basis_block_ids"], "原表"), ""]]
        if b == "negative_results":
            neg = [x for x in sd.get("negative_results") or [] if x]
            for x in neg:
                c.dup(x, neg=True)   # registered, never merged (negative results are exempt from dedupe)
            return (["**不能遗漏的阴性结果：** " + "；".join(c.st(x) for x in neg), ""] if neg else []) + [UNSHOWN + str(sec.data)]
        if b == "figures":
            return [x for f in figs_by_sec.pop(sec.data, []) for x in fig_block(f)]
        if b == "author_conclusion":
            v = S["s6"].get("author_conclusion")
            return [f"**作者结论（PAPER）：** {c.st(v)}", ""] if v else []
        if b == "evaluation":
            v = S["s6"].get("evaluation")
            return [f"**整理者评价（INFERENCE）：** {c.st(v)} 以上不代表用户已经认可的最终观点。", ""] if v else []
        if b == "review_items":
            return ([f"{i}. {c.st(x, show_label=True)}" for i, x in enumerate(S["s7"]["items"], 1)]
                    + ["", f"[[{evidence_link}#UNKNOWN 登记|查看完整 {len(unks)} 项 UNKNOWN]]", ""])
        if b == "borrow_items":
            out = (["**以下 3 件事为 INFERENCE（通用科研价值，由主笔独立生成，未参考课题）**；与当前课题的关联见下方小节。", ""]
                   if project else ["**未关联课题**：以下为 **INFERENCE（通用科研价值）**。", ""])
            for i, it in enumerate(S["s8"]["items"], 1):
                out.append(f"{i}. **{clean(it['title'])}**" + "".join(
                    f" **{lab}：** {c.st(it.get(k))}" for k, lab in (("basis", "本文依据"), ("help", "可借鉴之处"), ("limit", "借鉴限制"))
                    if it.get(k)))
            rs = S["s8"].get("review_summary")
            return out + [""] + ([f"**可用于综述起草的概括（INFERENCE）：** {c.st(rs)}", ""] if rs else [])
        if b == "next_checks":
            return ["**建议的后续核查：**", ""] + [f"{i}. {clean(x)}" for i, x in enumerate(S["s9"]["next_checks"], 1)] + [""]
        if b == "protected_zone":
            return ["> [!question] 用户批注区（留待用户填写）", "> 下列空间不代表已有个人结论，自动化不得静默覆盖。", "",
                    BEGIN, "**我最想带走的结论：**", "", "**我仍不接受／想复核的地方：**", "", "**对课题方案的具体决定：**", "", END, ""]
        if b == "unknown_top":
            top, rest_n = unks[:top_unknowns], max(0, len(unks) - top_unknowns)
            out = ["按对结论、临床适用性、可复现性的影响排序，仅列最重要的几项：", ""]
            out += [f"{i}. **{clean(u['item'])}**" + (f"：{clean(u.get('why'))}" if u.get("why") else "") for i, u in enumerate(top, 1)] or ["无"]
            return out + ["", f"[[{evidence_link}#UNKNOWN 登记|另 {rest_n} 项及全部 {len(unks)} 项完整登记见证据档案]]" if rest_n else f"[[{evidence_link}#UNKNOWN 登记|完整登记见证据档案]]", ""]
        if b == "evidence_nav":
            return [f"[[{evidence_link}|全部事实、原文定位、被拒条目与 UNKNOWN]] · [查看附件首页]({c.url(1)})", ""]
        if b == "module_slot":
            return [x for m in lay.modules for x in module_lines(m)]
        if b == "module_fields":
            return []
        if b == "project_lens":
            return lens_lines(project, lens, v2, c) if project else []
        raise ValueError(f"unknown block {b}")

    if lay.modules and not any("module_slot" in s.blocks for s in secs):
        i = next(i for i, s in enumerate(secs) if "evidence_nav" in s.blocks)
        from ..templates.format import Section
        secs.insert(i, Section("_modules", "专业模块评价", ["module_slot"], None))
    for sec in secs:
        h = _heading(sec, S)
        if h:
            L += [f"{'#' * sec.level} {h}", ""]
        for b in sec.blocks:
            L += block(b, sec)
    # verified results the writer left out of the body still reach it, verbatim (review fix 8)
    L = [c.resolve(x) for x in L]   # merged near-duplicates: final text + combined page links
    toks = [x for x in L if x.startswith(UNSHOWN)]
    if toks:   # placed in 四、核心结果 when the template has it, else in the first section with negative results
        i = L.index(UNSHOWN + "s4") if UNSHOWN + "s4" in toks else L.index(toks[0])
        body_nums = numbers(clean("\n".join(x for x in L if not x.startswith(UNSHOWN))))
        miss = [f for f in result_facts() if not numbers(clean(str(f.get("value") or ""))) <= body_nums][:MAX_UNSHOWN]
        seen_ctx, items = set(), []
        for f in miss:
            ctxt = clean(f_ctx(f)).strip()
            if ctxt in seen_ctx:
                continue
            seen_ctx.add(ctxt)
            items.append(f"「{ctxt}」 {c.links([f['block_id']], '结果')}".rstrip())
        L[i:i + 1] = ([f"**其他已逐字核对的结果（PAPER，原文摘录，正文未展开）：** {'；'.join(items)}", ""] if items else [])
        L = [x for x in L if not x.startswith(UNSHOWN)]
    head, n1 = unreadable_symbols("\n".join(L[:SUB_END]))
    body, n2 = unreadable_symbols(units(tidy(gloss("\n".join(L[SUB_END:]), v2.abbreviations))))
    if n1 + n2:
        v2.unknowns.append({"item": f"无法识别的符号 {n1 + n2} 处", "why": f"解析结果含 U+FFFD，笔记中显示为{UNREADABLE}；"
                            "请对照原页核对这些符号（常见为希腊字母、斜体变量或数学符号）", "impact": 1, "impact_tags": ["解析"]})
        v2.stats["unreadable_symbols"] = n1 + n2
    out = y + head + "\n" + body
    if out.count(BEGIN) != 1 or out.count(END) != 1:   # gate: exactly one protected zone
        raise ValueError("protected zone gate failed")
    return out


UNSHOWN = "\x00UNSHOWN_FACTS\x00"
MAX_UNSHOWN = 6


def _lens_ok(project, lens) -> bool:
    return bool(project and lens and lens.get("status") == "OK" and lens.get("relevance"))


def _relation(project, lens) -> str:
    if not project:
        return "无关联课题"
    return lens["relevance"]["level"] if _lens_ok(project, lens) else "LENS_FAILED"


def lens_lines(project, lens, v2, c) -> list[str]:
    """Project Lens block (design §5.2/§5.4). Paper cells and project cells are copied by CODE (R7)."""
    from ..project import lens as lens_mod, model as pmodel
    head = f"### 与当前课题的关联（INFERENCE，课题《{clean(project['title'])}》v{project['version']}）"
    if not _lens_ok(project, lens):
        why = (lens or {}).get("failure") or "未生成"
        return [head, "", f"> [!warning] 项目视角生成失败（{why}）；本篇仅提供上文的通用科研应用价值，课题档案未改动。", ""]
    items = {x["id"]: x for x in lens_mod.paper_items(v2)}
    obj = project["obj"]

    def refs(ids):
        return c.links(sorted({b for i in ids for b in items[i]["basis_block_ids"]}))

    rel = lens["relevance"]
    L = [head, "", "> [!tip] 项目视角只读取本次冻结的课题快照，不改变上文任何论文事实，也不修改课题档案。", "",
         f"**相关程度：** {rel['level']}——{clean(rel['reason'])} {refs(rel['refs'])}".rstrip(), ""]
    if lens.get("supports"):
        L += ["**可支持课题的环节：**", ""] + [f"- **{s['stage']}**：{clean(s['text'])} {refs(s['refs'])}".rstrip()
                                             for s in lens["supports"]] + [""]
    if lens.get("borrow"):
        L += ["**值得借鉴的方法：**", ""]
        for i, b in enumerate(lens["borrow"], 1):
            L.append(f"{i}. **{clean(b['method'])}** {refs(b['refs'])}".rstrip()
                     + (f" **适用前提：** {clean(b['preconditions'])}" if b.get("preconditions") else "")
                     + (f" **课题中尚未满足或未定：** {clean(b['unmet'])}" if b.get("unmet") else ""))
        L.append("")
    if lens.get("not_transferable"):
        L += ["**不能照搬：**", ""] + [f"- {clean(s['text'])} {refs(s['refs'])}".rstrip() for s in lens["not_transferable"]] + [""]
    if lens.get("next_steps"):
        L += ["**下一步建议（仅为建议，不改变课题档案）：**", ""] + [f"{i}. 建议：{clean(t)}" for i, t in enumerate(lens["next_steps"], 1)] + [""]
    if lens.get("matrix"):
        esc = lambda x: str(x).replace("|", "\\|").replace("\n", " ")
        L += ["**关联矩阵：**", "", "| 维度 | 本篇已证实内容 | 当前项目已确认情况 | 借鉴/差异 | 原页证据/状态 |", "|---|---|---|---|---|"]
        prev = None
        for m in lens["matrix"]:
            it = items[m["paper_ref"]]
            ptxt = "同上" if m["paper_ref"] == prev else esc(clean(it["text"]))
            prev = m["paper_ref"]
            vals = pmodel.confirmed(obj, m["project_key"])
            pj = "；".join(vals) if vals else "未定（论文做法仅供参考，不代表已采用）"
            L.append(f"| {esc(m['dimension'])} | {ptxt} | {esc(pj)} | {esc(clean(m['diff']))} | "
                     f"{c.links(it['basis_block_ids'], it.get('link_label', ''))} PAPER / 课题{'已确认' if vals else '未定'} |")
        L.append("")
    return L


def render_evidence(v2, *, raw, blocks, manifest, attachment_key, title, runs, vision_runs, e_report) -> str:
    from ..analysis.validator_v2 import refresh_stats
    refresh_stats(v2)   # wording/rejections were appended after validation (judge, renderer): count the real records
    c = Ctx(blocks, attachment_key)
    L = [f"# {title}——证据档案", "", "> [!info] 本档案保留原始值（含 MinerU LaTeX 原文），阅读版仅做显示清理。", "",
         "## 运行信息", "", "```json", json.dumps({"text_runs": runs, "vision_runs": vision_runs, "extraction": e_report,
                                                  "stats": v2.stats}, ensure_ascii=False, indent=1), "```", "",
         "## 元数据核对", "", "| 字段 | 值 | 标签 | 出处 |", "|---|---|---|---|"]
    for k, m in v2.meta.items():
        L.append(f"| {k} | {(m.get('value') or 'UNKNOWN')} | {m['label']} | {c.links([m['block_id']]) if m.get('block_id') else ''} |")
    L += ["", "## 逐字核对通过的事实（原始值）", "", "| 字段 | 原始值 | 原文片段 | block | 页 |", "|---|---|---|---|---|"]
    esc = lambda x: str(x or "").replace("|", "\\|").replace("\n", " ")
    for f in v2.facts:
        L.append(f"| {f['field']} | {esc(f['value'])} | {esc(f['context'])} | {f['block_id']} | {c.links([f['block_id']])} |")
    L += ["", "## 重复字段（已去重，仅存档）", ""] + [_dup_line(f, esc) for f in v2.duplicates] + [""]
    nm = getattr(v2, "note_meta", None)
    if nm:   # G10-7: the program fields that used to sit in the note's front matter
        L += ["## 笔记元数据（程序用）", "", "笔记开头只保留可读属性；以下字段供程序与核对使用。", "", "```json",
              json.dumps(nm, ensure_ascii=False, indent=1, default=str), "```", ""]
    loc = getattr(v2, "located_cells", None) or []
    if loc:   # G10-6
        L += ["## 表格单元格：数字在表格引用段落外核对通过", "", "| 位置 | 单元格 | 数字 | 方式 |", "|---|---|---|---|"]
        L += [f"| {esc(x['where'])} | {esc(x['cell'])} | {'、'.join(x['numbers'])} | {x['how']} |" for x in loc] + [""]
    L += ["## 被拒条目", "", "| 位置 | 原因 | 内容摘要 |", "|---|---|---|"]
    for r in v2.rejected:
        item = r["item"]
        summ = item.get("text") or item.get("value") or item.get("title") or json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item)
        L.append(f"| {r['where']} | {esc(r['reason'])} | {esc(str(summ)[:120])} |")
    L += ["", "## UNKNOWN 登记", "", "按影响排序（结论 3 / 临床适用 2 / 复现 1，可叠加；元数据 0）。", ""]
    n_res = sum(1 for u in v2.unknowns if u.get("resolved_by"))
    if n_res:
        L += [f"主笔记计 {v2.stats.get('unknowns_in_note', len(v2.unknowns) - n_res)} 项；另 {n_res} 项已由 Zotero 元数据、论文类型分类补全或被作者顺序冲突项取代，不计入主笔记。", ""]
    L += [f"{i}. **{esc(u['item'])}** — {esc(u.get('why'))}　`impact={u.get('impact', '?')} {'/'.join(u.get('impact_tags', []))}`" + (f" **MALFORMED：{esc(u['malformed'])}（不在主笔记显示）**" if u.get("malformed") else "") + (f" **已解决（{u['resolved_by']}），不在主笔记计数**" if u.get("resolved_by") else "") for i, u in enumerate(v2.unknowns, 1)]
    up = (e_report or {}).get("unknown_pages") or []
    if up:
        L += ["", "**UNKNOWN 页面**（解析器在这些页上没有得到任何内容；其中的信息未被读取，相关内容一律视为 UNKNOWN）：", ""]
        L += [f"- 第 {u['page']} 页：{esc(u['why'])} · [打开原页](zotero://open-pdf/library/items/{attachment_key}?page={u['page']})"
              for u in up]
    L += ["", "## 措辞闸门记录", "", f"共 {len(v2.wording)} 条（= 运行信息 stats.wording_changes）。", "",
          "| 位置 | 原文 | 处理后 | 闸门 | 规则 |", "|---|---|---|---|---|"]
    L += [f"| {w['where']} | {esc(w['original'])} | {esc(w.get('result')) if w.get('result') is not None else '（已拒绝）'} | "
          f"{esc(w.get('gate') or 'UNKNOWN')}{(' · 判官原判 ' + esc(w['judge_verdict'])) if w.get('judge_verdict') else ''} | "
          f"{esc(w.get('rule'))}{(' · ' + esc(w.get('reason'))) if w.get('reason') else ''} |" for w in v2.wording]
    L += ["", "## 图表来源", "", "```json", json.dumps(manifest, ensure_ascii=False, indent=1), "```", ""]
    return "\n".join(L)


def _dup_line(f, esc) -> str:
    """G9-1: duplicates come from the validator ({field,value}) or from module paragraphs ({where,text,reason})."""
    if not isinstance(f, dict):
        return f"- {esc(f)}"
    if f.get("field") is not None:
        return f"- {f.get('field')}: {esc(f.get('value'))}"
    reason = f"（{esc(f.get('reason'))}）" if f.get("reason") else ""
    return f"- {f.get('where') or 'module'}（模块段落）: {esc(f.get('text') or f.get('value'))}{reason}"
