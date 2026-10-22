"""Untrusted-template text handling (R6, spec §5.3): detect injection-like content, clean what may reach a prompt
or a heading. Templates are DATA; nothing here executes, fetches or follows anything."""
from __future__ import annotations

import re
import unicodedata

ZW = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u00ad]")
URL = re.compile(r"(?:https?|ftp|file|zotero|obsidian|javascript|data):\S*|www\.\S+", re.I)
HTML = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")
TEMPLATER = re.compile(r"<%.*?%>", re.S)
PLACE = re.compile(r"\{\{.*?\}\}", re.S)
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
MDLINK = re.compile(r"!?\[\[([^\]]*)\]\]|!?\[([^\]]*)\]\([^)]*\)")

CHECKS = [
    ("INJECTION_PHRASE", re.compile(r"ignore (all |any )?(previous|prior|above)|disregard (the )?(rules|instructions)|system prompt|"
                                    r"you are now|jailbreak|忽略(之前|以上|此前|上述|前面)|无视(规则|以上)|你现在是|系统提示|越狱|开发者模式", re.I)),
    ("COMMAND", re.compile(r"\brm\s+-|\bcurl\b|\bwget\b|\bbash\b|\bsh\s+-c|python\s+-c|os\.system|subprocess|\beval\(|\bexec\(|"
                           r"powershell|chmod\s|sudo\s|&&|\$\(", re.I)),
    ("URL", URL),
    ("SCOPE", re.compile(r"\.\./|写入(其他|任意|整个)|上传|删除(文件|笔记|目录)|改(变)?权限|修改(Key|密钥|模型)|api[_ ]?key|"
                         r"keychain|钥匙串|write to|delete (the )?file|upload", re.I)),
    ("LOWER_STANDARD", re.compile(r"没有就编|(可以|请|允许|尽量)编造|不要写\s*UNKNOWN|不(要|用)标(注)?\s*UNKNOWN|全部标(为|成)?\s*PAPER|"
                                  r"省略\s*UNKNOWN|不需要(依据|出处|页码)|fabricate|make (it|something) up|"
                                  r"label everything (as )?PAPER", re.I)),
    ("HTML", re.compile(r"<\s*(script|iframe|style|object|embed|img|link|meta)\b", re.I)),
    ("TEMPLATER", re.compile(r"<%|```dataview|\{\{")),
    ("INVISIBLE", ZW),
]


def scan(text: str) -> list[tuple[str, str]]:
    out = []
    for code, rx in CHECKS:
        m = rx.search(text or "")
        if m:
            out.append((code, (text[max(0, m.start() - 10):m.end() + 10]).replace("\n", " ")[:60]))
    return out


def clean(text: str, limit: int) -> str:
    t = unicodedata.normalize("NFC", text or "")
    t = ZW.sub("", t)
    t = CODE.sub(" ", t)
    t = TEMPLATER.sub(" ", t)
    t = PLACE.sub(" ", t)
    t = MDLINK.sub(lambda m: m.group(1) or m.group(2) or "", t)
    t = HTML.sub(" ", t)
    t = URL.sub(" ", t)
    t = "".join(ch for ch in t if ch == "\n" or unicodedata.category(ch)[0] != "C")
    t = re.sub(r"[ \t\u3000]+", " ", t).strip()
    return t[:limit]


def clean_title(text: str, limit: int = 40) -> str:
    t = clean(str(text or ""), 200).replace("\n", " ")
    t = re.sub(r"\s+", " ", re.sub(r"[#|\[\]^`*<>]", "", t)).strip()
    return t[:limit]
