"""Template file format + lint (design §2, §4; spec §5.1–§5.3).

A template is UTF-8 Markdown with a restricted front matter. Only front-matter structure and `> 写作提示：` lines
under `##`/`###` headings are machine-read; everything else is human preview and is never sent to a model.
`parse_template` never raises on bad content: it returns a Template whose `errors` (→ REJECTED) and
`review` reasons (→ NEEDS_REVIEW) say why.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from . import fm, sanitize, vocab

MAX_BYTES = 64 * 1024
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
SEC_ID_RE = re.compile(r"^[a-z0-9_]{1,24}$")
FIELD_RE = re.compile(r"^[a-z_]{2,40}$")
ALLOWED_KEYS = {"litreader_template", "id", "title", "role", "version", "language", "applies_to", "priority",
                "compatible_with", "header_blocks", "sections", "required_blocks", "adds_fields", "adds_sections",
                "fixture", "description"}
HINT_MAX = 300


@dataclass
class Section:
    id: str
    title: str
    blocks: list[str]
    data: str | None              # schema data key (s1..s10) or None = extra section filled via TEMPLATE_DATA
    suffix: str = "none"          # none | colon (title：suffix) | append (title+suffix)
    suffix_default: str = ""
    level: int = 2
    hint: str = ""


@dataclass
class Template:
    path: str
    sha256: str
    size: int
    id: str | None = None
    title: str = ""
    role: str | None = None           # spec enum MAIN_NOTE / MODULE / OVERVIEW / EVIDENCE_APPENDIX
    declared_version: str | None = None
    language: str = "zh-CN"
    study_types: list[str] = field(default_factory=list)
    reading_levels: list[str] = field(default_factory=lambda: ["L2"])
    topics: list[str] = field(default_factory=list)
    priority: int = 50
    compatible_with: list[str] = field(default_factory=list)
    header_blocks: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    required_blocks: list[str] = field(default_factory=list)
    adds_fields: list[dict] = field(default_factory=list)
    adds_sections: list[Section] = field(default_factory=list)
    fixture: bool = False
    missing_front_matter: bool = False
    errors: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)       # structural problems → NEEDS_REVIEW
    warnings: list[str] = field(default_factory=list)     # preview-only problems (still usable)

    @property
    def features(self) -> list[str]:
        blocks = {b for s in self.sections + self.adds_sections for b in s.blocks}
        out = ["PDF_PAGE_LINK"] if self.role in ("MAIN_NOTE", "MODULE") else []
        out += [f for f, b in vocab.FEATURES.items() if b and b in blocks]
        return out

    @property
    def required_fields(self) -> list[str]:
        return [f["name"] for f in self.adds_fields]

    def status_hint(self) -> str:
        return "REJECTED" if self.errors else ("NEEDS_REVIEW" if self.review else "ACTIVE")


def _list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _hints(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    cur = None
    for line in body.splitlines():
        m = re.match(r"^(#{2,3})\s+(.*?)\s*$", line)
        if m:
            cur = sanitize.clean_title(m.group(2), 60)
            continue
        m = re.match(r"^>\s*写作提示[：:]\s*(.*)$", line)
        if m and cur:
            out[cur] = (out.get(cur, "") + " " + m.group(1)).strip()
        elif not line.startswith(">"):
            pass
    return out


def _section(d, where: str, t: Template, allowed_blocks, *, module=False) -> Section | None:
    if not isinstance(d, dict):
        t.review.append(f"{where}：章节必须是 {{id, title, blocks}} 映射")
        return None
    sid = str(d.get("id") or "")
    if not SEC_ID_RE.match(sid):
        t.review.append(f"{where}：章节 id「{sid[:30]}」不合法（a-z0-9_，≤24）")
        return None
    raw_title = str(d.get("title") or "")
    title = sanitize.clean_title(raw_title)
    if title != raw_title.strip():
        t.review.append(f"{where}：章节标题含不允许的字符或过长，已清洗为「{title}」")
    blocks = []
    for b in _list(d.get("blocks")):
        if b in allowed_blocks:
            blocks.append(b)
        else:
            t.review.append(f"{where}：未知块类型「{str(b)[:30]}」（模板不能定义新的渲染逻辑）")
    data = d.get("data", sid if sid in vocab.DATA_KEYS else None)
    if data is not None and data not in vocab.DATA_KEYS:
        t.review.append(f"{where}：data「{str(data)[:20]}」不在 {', '.join(vocab.DATA_KEYS)} 中")
        data = None
    if module:
        data = None
    suffix = d.get("suffix", "none")
    if suffix not in vocab.SUFFIX_MODES:
        t.review.append(f"{where}：suffix 只能是 {vocab.SUFFIX_MODES}")
        suffix = "none"
    level = d.get("level", 2)
    if level not in (2, 3):
        t.review.append(f"{where}：level 只能是 2 或 3")
        level = 2
    sd = sanitize.clean_title(str(d.get("suffix_default") or ""), 20)
    return Section(sid, title, blocks, data, suffix, sd, level)


def parse_template(raw: bytes, path: str) -> Template:
    t = Template(path=path, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
    if len(raw) > MAX_BYTES:
        t.errors.append(f"文件过大（{len(raw)} 字节 > {MAX_BYTES}）")
        return t
    if b"\x00" in raw:
        t.errors.append("含二进制内容")
        return t
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        t.errors.append("不是 UTF-8 编码")
        return t
    try:
        fm_text, body = fm.split(text)
        d = fm.parse(fm_text) if fm_text is not None else {}
    except fm.FrontMatterError as e:
        t.errors.append(f"front matter 格式错误：{e}")
        return t
    if fm_text is None or not d:
        t.missing_front_matter = True
        t.review.append("缺少 front matter（角色/适用类型需 AI 建议并经你确认）")
    for code, ctx in sanitize.scan(fm_text or ""):
        t.review.append(f"front matter 含可疑内容 {code}：「{ctx}」")
    hints = _hints(body)
    hint_text = " ".join(hints.values())
    for code, ctx in sanitize.scan(hint_text):
        t.review.append(f"写作提示含可疑内容 {code}：「{ctx}」")
    rest = re.sub(r"^>\s*写作提示.*$", "", body, flags=re.M)
    for code, ctx in sanitize.scan(rest):
        t.warnings.append(f"预览正文含 {code}：「{ctx}」（不会被读取或执行）")
    for k in d:
        if k not in ALLOWED_KEYS:
            t.warnings.append(f"未知字段 {k} 已忽略")
    if d.get("fixture") is True:
        t.fixture = True
    fv = d.get("litreader_template")
    if d and fv != vocab.FORMAT_VERSION:
        t.review.append(f"litreader_template={fv!r}（首版只认 1）")
    tid = d.get("id")
    if tid is not None:
        tid = str(tid)
        if ID_RE.match(tid):
            t.id = tid
        else:
            t.review.append(f"id「{tid[:40]}」不合法（[a-z0-9._-]，3–64）")
    elif d:
        t.review.append("缺少 id")
    if t.fixture or (t.id or "").startswith(("test.", "fixture.")):
        t.fixture = True
        t.errors.append("测试模板（fixture / test. / fixture. 前缀）不得进入生产登记")
    raw_title = str(d.get("title") or "")
    t.title = sanitize.clean_title(raw_title, 60)
    if raw_title and t.title != raw_title.strip():
        t.review.append(f"标题含不允许的字符，已清洗为「{t.title}」")
    role = d.get("role")
    if role in vocab.ROLES:
        t.role = vocab.ROLES[role]
    elif role in vocab.ROLES.values():
        t.role = role
    elif d:
        t.review.append(f"role「{role}」缺失或不在 main/module/overview/evidence 中")
    t.declared_version = str(d["version"]) if d.get("version") is not None else None
    lang = d.get("language", "zh-CN")
    if lang != "zh-CN":
        t.review.append(f"language={lang!r}（首版只支持 zh-CN）")
    ap = d.get("applies_to") or {}
    if not isinstance(ap, dict):
        t.review.append("applies_to 必须是映射")
        ap = {}
    for s in _list(ap.get("study_types")):
        if s == vocab.ANY or s in vocab.STUDY_TYPES:
            t.study_types.append(s)
        else:
            t.review.append(f"未知论文类型「{str(s)[:30]}」（受控词表外）")
    lv = [x for x in _list(ap.get("reading_levels")) if x in vocab.LEVELS]
    if ap.get("reading_levels") is not None and len(lv) != len(_list(ap.get("reading_levels"))):
        t.review.append("reading_levels 只能是 L1/L2/L3")
    t.reading_levels = lv or ["L2"]
    t.topics = [sanitize.clean_title(x, 20) for x in _list(ap.get("topics"))][:10]
    pr = d.get("priority", 50)
    if isinstance(pr, int) and not isinstance(pr, bool) and 0 <= pr <= 100:
        t.priority = pr
    else:
        t.review.append("priority 必须是 0–100 的整数")
    if t.role in ("MAIN_NOTE", "MODULE") and not t.study_types:
        t.review.append("缺少 applies_to.study_types")
    if t.role == "MODULE":
        t.compatible_with = [str(x) for x in _list(d.get("compatible_with"))]
        if not t.compatible_with:
            t.review.append("专业模块缺少 compatible_with")
    for b in _list(d.get("header_blocks")):
        if b in vocab.HEADER_BLOCKS:
            t.header_blocks.append(b)
        else:
            t.review.append(f"header_blocks：未知块类型「{str(b)[:30]}」")
    seen = set()
    for i, sd in enumerate(_list(d.get("sections"))):
        s = _section(sd, f"sections[{i}]", t, vocab.SECTION_BLOCKS)
        if s:
            if s.id in seen:
                t.review.append(f"章节 id 重复：{s.id}")
                continue
            seen.add(s.id)
            t.sections.append(s)
    if t.role == "MAIN_NOTE" and not t.sections:
        t.review.append("主模板缺少 sections")
    t.required_blocks = [b for b in _list(d.get("required_blocks")) if b in vocab.SECTION_BLOCKS + vocab.HEADER_BLOCKS]
    names = set()
    for i, f in enumerate(_list(d.get("adds_fields"))):
        if not isinstance(f, dict) or not FIELD_RE.match(str(f.get("name") or "")):
            t.review.append(f"adds_fields[{i}]：name 必须是 [a-z_]{{2,40}}")
            continue
        if f["name"] in names:
            t.review.append(f"adds_fields 重名：{f['name']}")
            continue
        names.add(f["name"])
        lr = f.get("label_rule", "ANY")
        if lr not in ("PAPER", "INFERENCE", "ANY"):
            t.review.append(f"adds_fields[{i}]：label_rule 只能是 PAPER/INFERENCE/ANY")
            lr = "ANY"
        t.adds_fields.append({"name": f["name"], "label": sanitize.clean_title(str(f.get("label") or f["name"]), 30),
                              "label_rule": lr, "description": sanitize.clean(str(f.get("description") or ""), 120)})
    for i, sd in enumerate(_list(d.get("adds_sections"))):
        s = _section(sd, f"adds_sections[{i}]", t, ("paragraphs", "module_fields"), module=True)
        if s:
            t.adds_sections.append(s)
    for s in t.sections + t.adds_sections:   # attach writing hints by heading text
        h = hints.get(s.title) or hints.get(s.id)
        if h:
            s.hint = sanitize.clean(h, HINT_MAX)
    if not t.title:
        t.title = path.rsplit("/", 1)[-1].removesuffix(".md")[:60]
    return t


def lint_report(t: Template) -> list[str]:
    lines = [f"{t.path}  sha256 {t.sha256[:12]}…  {t.size} 字节",
             f"  判定：{ {'ACTIVE': '可用', 'NEEDS_REVIEW': '待审（不参与自动选择）', 'REJECTED': '拒绝'}[t.status_hint()] }"]
    lines += [f"  ❌ {e}" for e in t.errors] + [f"  ⚠️ {r}" for r in t.review] + [f"  ℹ️ {w}" for w in t.warnings]
    if not t.errors:
        lines.append(f"  id={t.id} 角色={vocab.ROLE_ZH.get(t.role, '未知')} 适用={','.join(t.study_types) or '未声明'} "
                     f"章节={len(t.sections)} 模块章节={len(t.adds_sections)} 能力={','.join(t.features)}")
    return lines
