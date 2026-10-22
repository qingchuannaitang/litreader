"""Restricted YAML-subset parser for template front matter (no PyYAML; safe by construction).

Accepted: `key: scalar`, `key: [flow, list]`, `key: {flow: mapping}`, and one nested block level:
    key:
      - scalar | {flow mapping}
      sub: scalar | [..] | {..}
Scalars: "double" / 'single' quoted strings, integers, true/false, null, bare strings.
Rejected (FrontMatterError): anchors/aliases (&, *), tags (!), block scalars (| >), tabs, multi-document markers,
deeper nesting, more than MAX_KEYS keys, duplicate keys.
"""
from __future__ import annotations

import re

MAX_KEYS = 200


class FrontMatterError(ValueError):
    pass


_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_.\-]*)\s*:(?:\s+(.*))?$")


def split(text: str) -> tuple[str | None, str]:
    """Return (front matter text or None, body)."""
    if text.startswith("\ufeff"):
        text = text[1:]
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return None, text
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            return "".join(lines[1:i]), "".join(lines[i + 1:])
        if lines[i].rstrip("\r\n") == "...":
            raise FrontMatterError("不支持 YAML 文档结束标记")
    raise FrontMatterError("front matter 没有结束的 ---")


class _Flow:
    def __init__(self, s: str):
        self.s, self.i = s, 0

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def value(self, stops: str):
        self.ws()
        if self.i >= len(self.s):
            raise FrontMatterError("值缺失")
        c = self.s[self.i]
        if c == "[":
            return self.seq()
        if c == "{":
            return self.map()
        return self.scalar(stops)

    def seq(self):
        self.i += 1
        out = []
        self.ws()
        if self.s[self.i:self.i + 1] == "]":
            self.i += 1
            return out
        while True:
            v = self.value(",]")
            if isinstance(v, list):
                raise FrontMatterError("嵌套过深")
            if isinstance(v, (list, dict)) and any(isinstance(x, (list, dict)) for x in (v if isinstance(v, list) else v.values())):
                raise FrontMatterError("嵌套过深")
            out.append(v)
            self.ws()
            c = self.s[self.i:self.i + 1]
            self.i += 1
            if c == "]":
                return out
            if c != ",":
                raise FrontMatterError("列表格式错误")

    def map(self):
        self.i += 1
        out: dict = {}
        self.ws()
        if self.s[self.i:self.i + 1] == "}":
            self.i += 1
            return out
        while True:
            self.ws()
            m = re.match(r"([A-Za-z_][A-Za-z0-9_.\-]*)\s*:", self.s[self.i:])
            if not m:
                raise FrontMatterError("映射键格式错误")
            k = m.group(1)
            self.i += m.end()
            if k in out:
                raise FrontMatterError(f"重复的键 {k}")
            v = self.value(",}")
            if isinstance(v, dict) or (isinstance(v, list) and any(isinstance(x, (list, dict)) for x in v)):
                raise FrontMatterError("嵌套过深")
            out[k] = v
            self.ws()
            c = self.s[self.i:self.i + 1]
            self.i += 1
            if c == "}":
                return out
            if c != ",":
                raise FrontMatterError("映射格式错误")

    def scalar(self, stops: str):
        c = self.s[self.i]
        if c in "\"'":
            j = self.i + 1
            buf = []
            while j < len(self.s):
                ch = self.s[j]
                if c == '"' and ch == "\\" and j + 1 < len(self.s):
                    nxt = self.s[j + 1]
                    buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
                    j += 2
                    continue
                if ch == c:
                    if c == "'" and self.s[j + 1:j + 2] == "'":
                        buf.append("'"); j += 2; continue
                    self.i = j + 1
                    return "".join(buf)
                buf.append(ch)
                j += 1
            raise FrontMatterError("引号未闭合")
        j = self.i
        while j < len(self.s) and self.s[j] not in stops:
            j += 1
        tok = self.s[self.i:j].strip()
        self.i = j
        return _bare(tok)


def _bare(tok: str):
    if tok == "":
        raise FrontMatterError("值缺失")
    if tok[0] in "&*!|>%@`":
        raise FrontMatterError(f"不支持的 YAML 语法：{tok[:10]}")
    if tok in ("true", "True"):
        return True
    if tok in ("false", "False"):
        return False
    if tok in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d{1,9}", tok):
        return int(tok)
    return tok


def _inline(rest: str):
    rest = _strip_comment(rest).strip()
    if rest == "":
        return None
    f = _Flow(rest)
    v = f.value("")
    f.ws()
    if f.i != len(rest):
        raise FrontMatterError(f"多余内容：{rest[f.i:][:20]}")
    return v


def _strip_comment(s: str) -> str:
    q = None
    for i, ch in enumerate(s):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i]
    return s


def parse(text: str) -> dict:
    if "\t" in text:
        raise FrontMatterError("front matter 中不允许制表符")
    out: dict = {}
    nkeys = 0
    lines = [l.rstrip("\r") for l in text.split("\n")]
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not _strip_comment(raw).strip():
            i += 1
            continue
        if raw.startswith(" "):
            raise FrontMatterError(f"第 {i + 1} 行缩进不符合格式")
        if raw.strip() in ("---", "..."):
            raise FrontMatterError("不支持多文档")
        m = _KEY.match(raw)
        if not m:
            raise FrontMatterError(f"第 {i + 1} 行不是 键: 值")
        k, rest = m.group(1), m.group(2) or ""
        if k in out:
            raise FrontMatterError(f"重复的键 {k}")
        nkeys += 1
        v = _inline(rest)
        i += 1
        if v is None and not _strip_comment(rest).strip():
            block = []
            while i < len(lines) and (lines[i].startswith(" ") or not _strip_comment(lines[i]).strip()):
                if _strip_comment(lines[i]).strip():
                    block.append((i, lines[i]))
                i += 1
            if block:
                v, n = _block(block)
                nkeys += n
        out[k] = v
        if nkeys > MAX_KEYS:
            raise FrontMatterError(f"键过多（>{MAX_KEYS}）")
    return out


def _block(block):
    ind = len(block[0][1]) - len(block[0][1].lstrip(" "))
    if any(len(l) - len(l.lstrip(" ")) != ind for _, l in block):
        raise FrontMatterError(f"第 {block[0][0] + 1} 行附近：嵌套过深或缩进不一致")
    items = [l.strip() for _, l in block]
    if all(x.startswith("- ") or x == "-" for x in items):
        out = []
        for x in items:
            v = _inline(x[1:])
            if isinstance(v, list) and any(isinstance(y, (list, dict)) for y in v):
                raise FrontMatterError("嵌套过深")
            out.append(v)
        return out, len(out)
    if any(x.startswith("-") for x in items):
        raise FrontMatterError("列表与映射混用")
    out = {}
    for (ln, _), x in zip(block, items):
        m = _KEY.match(x)
        if not m:
            raise FrontMatterError(f"第 {ln + 1} 行不是 键: 值")
        if m.group(1) in out:
            raise FrontMatterError(f"重复的键 {m.group(1)}")
        v = _inline(m.group(2) or "")
        if isinstance(v, dict) or (isinstance(v, list) and any(isinstance(y, (list, dict)) for y in v)):
            raise FrontMatterError("嵌套过深")
        out[m.group(1)] = v
    return out, len(out)
