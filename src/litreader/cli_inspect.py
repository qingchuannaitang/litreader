"""`litreader inspect-parse [job] [--page 20-22] [--text]`: per-page block-type counts of a CACHED MinerU job.
Local only: no upload, no model call, nothing written. Without options no paper content is printed (only counts,
character totals, page kinds and the E-level verdict), so the output can be shared for troubleshooting.
--page lists every block of the given physical pages (= the N of a Zotero link ?page=N): order, MinerU type, bbox,
share of the page, image file (absolute path, pixel size) and which note figure it was grouped into; page-number /
header / footer text and the first 30 characters of a caption are shown (they identify the page and the figure).
--text additionally shows, for EVERY non-image block (text/title/aside/footnote/page number), its type, bbox, length and
first 40 characters, marks a caption pattern found inside a block, and lists the blocks MinerU discarded (layout.json
discarded_blocks, bbox converted to ‰) — that IS paper content. Caption-like starts are listed even without --text.
bbox: MinerU content_list uses a 0–1000 space per axis (x ‰ of page width, y ‰ of page height), not PDF points."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .errors import Stop

COLS = [("text", "正文"), ("title", "标题"), ("list", "列表"), ("equation", "公式"), ("image", "图"), ("chart", "图表"),
        ("table", "表"), ("caption", "图注"), ("ref_text", "参考文献"), ("aside_text", "旁注"), ("page_footnote", "脚注"),
        ("chrome", "页眉脚/页码"), ("other", "其他")]


def find_job(jobs: Path, wanted: str | None) -> Path:
    cands = sorted((d for d in jobs.iterdir() if d.is_dir() and (d / "mineru" / "extracted").is_dir()),
                   key=lambda d: d.stat().st_mtime, reverse=True) if jobs.is_dir() else []
    if not cands:
        raise Stop(f"没有找到已缓存的 MinerU 解析结果（{jobs}）")
    if not wanted:
        return cands[0]
    hit = [d for d in cands if d.name == wanted] or [d for d in cands if wanted in d.name]
    if len(hit) != 1:
        names = "\n".join(f"  {d.name}" for d in cands[:20])
        raise Stop(f"{'没有' if not hit else '有多个'}缓存任务匹配「{wanted}」。已有：\n{names}")
    return hit[0]


def parse_pages(spec: str | None) -> list[int]:
    """'21' / '20-22' / '8,21' -> sorted physical page numbers."""
    out: set[int] = set()
    for part in (spec or "").replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        if not a.isdigit() or (b and not b.isdigit()):
            raise Stop(f"页码写法不对：「{spec}」（例：21 或 20-22 或 8,21）")
        lo, hi = int(a), int(b or a)
        out.update(range(min(lo, hi), max(lo, hi) + 1))
    return sorted(p for p in out if p > 0)


def image_size(path: Path) -> tuple[int, int] | None:
    """Pixel size of a JPEG/PNG from its header (no imaging library needed)."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1; continue
            marker, ln = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + ln
    return None


def _short(t: str, n: int) -> str:
    t = " ".join((t or "").split())
    return t[:n] + ("…" if len(t) > n else "")


_LOOSE = re.compile(r"^(?:图|圖|Fig(?:ure)?\.?)\s*\d+", re.I)
_MID = re.compile(r"(?:图|Fig(?:ure)?\.?)\s*\d+\s*[.．:：|｜]")


def _strip(t: str) -> str:
    return re.sub(r"^(?:[\s*_#>`]|<[^>]{1,10}>)*", "", t or "")


def _discarded(lj: Path, sizes: dict) -> dict[int, list[tuple[str, list[int], str]]]:
    """layout.json discarded_blocks per physical page: (type, bbox in ‰ of the page, text). Best effort."""
    import json
    out: dict[int, list] = {}
    try:
        info = json.loads(lj.read_text("utf-8")).get("pdf_info") or []
    except (ValueError, OSError, AttributeError):
        return out
    for i, pg in enumerate(info):
        p = pg.get("page_idx", i) + 1
        w, h = (pg.get("page_size") or [0, 0])[:2] or (0, 0)
        for d in pg.get("discarded_blocks") or []:
            txt = "".join(str(sp.get("content") or "") for ln in d.get("lines") or [] for sp in ln.get("spans") or [])
            bb = d.get("bbox") or []
            bbn = [round(bb[0] * 1000 / w), round(bb[1] * 1000 / h), round(bb[2] * 1000 / w), round(bb[3] * 1000 / h)] \
                if len(bb) == 4 and w and h else [round(x) for x in bb]
            out.setdefault(p, []).append((str(d.get("type") or "?"), bbn, txt))
    return out


def page_detail(res, ext: Path, pages: list[int], show_text: bool, out=print) -> None:
    import json
    from .parse.figures import build_manifest, cap_start
    where = {}
    for m in build_manifest(res, "", ""):
        for p in m["parts"]:
            where[p["order"]] = f"{m['id']}（{'、'.join(m['flags']) or '有图注'}）"
    sizes = {}
    lj = ext / "layout.json"
    if lj.is_file():
        try:
            for i, pg in enumerate(json.loads(lj.read_text("utf-8")).get("pdf_info") or []):
                sizes[pg.get("page_idx", i) + 1] = pg.get("page_size")
        except (ValueError, OSError, AttributeError):
            pass
    discarded = _discarded(lj, sizes) if lj.is_file() else {}
    for p in pages:
        bs = sorted((b for b in res.blocks if b.physical_page == p), key=lambda b: b.order)
        out("")
        out(f"—— 物理第 {p} 页（MinerU page_idx={p - 1}；Zotero 链接 ?page={p} 打开的就是这一页）"
            + (f"；页面尺寸 {sizes[p]}" if sizes.get(p) else "") + " ——")
        if not bs:
            out("  （这一页没有任何块）")
            continue
        labels = [f"{b.kind}「{_short(b.text, 30)}」" for b in bs if b.kind in ("page_number", "header", "footer") and b.text.strip()]
        out("  页码/页眉/页脚文字：" + ("；".join(labels) if labels else "无（看不出印刷页码）"))
        n_text = 0
        for b in bs:
            vis = b.kind in ("figure", "table") or b.raw_type in ("image", "chart", "table", "equation")
            typ = b.raw_type if not b.raw_type or b.raw_type == b.kind else f"{b.raw_type}/{b.kind}"
            if not vis:
                n_text += 1
                bb = f" bbox {[int(x) for x in b.bbox_norm]}" if b.bbox_norm else " 无 bbox"
                n_ch = len(b.text or "")
                if cap_start(b.text):   # a caption paragraph: always listed (it decides the figure number)
                    out(f"  #{b.order} {typ or b.kind}{bb}：图注段落「{_short(b.text, 30)}」")
                elif _LOOSE.match(_strip(b.text)):   # starts like a caption but not in the accepted format
                    out(f"  #{b.order} {typ or b.kind}{bb}：疑似图注（格式不在识别规则内）「{_short(b.text, 30)}」")
                elif show_text:
                    out(f"  #{b.order} {typ or b.kind}{bb}（{n_ch} 字）：{_short(b.text, 40) or '（空）'}")
                    mid = _MID.search(b.text or "")
                    if mid and mid.start() > 0:
                        out(f"      ↳ 第 {mid.start()} 字处出现「{_short(b.text[mid.start():], 30)}」（图注可能被并进了这个块）")
                continue
            bb = b.bbox_norm
            geo = (f"bbox {[int(x) for x in bb]}，宽 {bb[2] - bb[0]:.0f}‰ × 高 {bb[3] - bb[1]:.0f}‰，占页面 "
                   f"{(bb[2] - bb[0]) * (bb[3] - bb[1]) / 10000:.1f}%") if bb else "无 bbox"
            out(f"  #{b.order} {b.raw_type or b.kind}：{geo}")
            out(f"      图注：{_short(b.caption, 30) if b.caption.strip() else '无'}；归入：{where.get(b.order, '未归入任何图表（如公式）')}")
            if b.img_path:
                f = ext / b.img_path
                sz = image_size(f) if f.is_file() else None
                out(f"      图片：{f}" + (f"（{sz[0]}×{sz[1]} 像素）" if sz else ("（文件不存在）" if not f.is_file() else "")))
        out(f"  其他块（正文/标题/旁注/页码等）：{n_text} 个" + ("" if show_text else "（加 --text 可显示每块的类型、位置、字数和开头 40 字）"))
        disc = discarded.get(p) or []
        if disc:
            out(f"  MinerU 丢弃的块（layout.json discarded_blocks，不在 content_list 里，程序看不到）：{len(disc)} 个")
            for k, (typ, bb, txt) in enumerate(disc, 1):
                capish = cap_start(txt) or _LOOSE.match(_strip(txt))
                if show_text or capish:
                    out(f"    丢弃#{k} {typ} bbox {bb}：{'疑似图注' if capish else ''}「{_short(txt, 30 if capish and not show_text else 40)}」")


def run(cfg, wanted: str | None, out=print, pages: str | None = None, show_text: bool = False) -> int:
    from .estimate import pdf_stats
    from .parse import mineru
    from .parse.extraction_level import KIND_ZH, assess, core_pages, page_kinds
    jobs = cfg.data_dir / "jobs"
    job = find_job(jobs, wanted)
    res = mineru.load_extracted_dir(job / "mineru" / "extracted")
    src = job / "source.pdf"
    pdf_pages = (pdf_stats(src).get("pages") if src.is_file() else None) or res.page_count_reported or 0
    n = max([pdf_pages] + [b.physical_page for b in res.blocks])
    out(f"任务：{job.name}")
    out(f"解析器：MinerU {res.parser_version or '版本未知'}；PDF 页数：{pdf_pages or '未知'}；解析器报告页数：{res.page_count_reported or '未知'}；块总数：{len(res.blocks)}")
    kinds = page_kinds(res, n)
    core = core_pages(res, n)
    out(f"方法/结果部分（按标题推断）：{f'第 {min(core)}–{max(core)} 页' if core else '未识别到'}")
    out("每页块数（只统计数量，不含内容）：")
    out("页 | " + " | ".join(z for _, z in COLS) + " | 正文字数 | 判定")
    for p in range(1, n + 1):
        bs = [b for b in res.blocks if b.physical_page == p]
        c = Counter()
        for b in bs:
            if b.kind in ("header", "footer", "page_number"):
                c["chrome"] += 1
            elif b.kind == "title":
                c["title"] += 1
            elif b.raw_type in dict(COLS):
                c[b.raw_type] += 1
            else:
                c["other"] += 1
            if b.caption.strip():
                c["caption"] += 1
        chars = sum(len(b.text) for b in bs if b.kind in ("text", "title") and b.raw_type != "equation")
        flag = KIND_ZH[kinds[p]] + ("（方法/结果）" if p in core else "")
        out(f"{p} | " + " | ".join(str(c.get(k, 0) or "·") for k, _ in COLS) + f" | {chars} | {flag}")
    el = assess(res, pdf_pages or n)
    out(f"抽取完整度：{el.level}")
    for r in el.reasons:
        out(f"  - {r}")
    if pages:
        page_detail(res, job / "mineru" / "extracted", parse_pages(pages), show_text, out)
        out("")
        out("（本命令只读本机缓存：未上传、未调用模型、未写任何文件；以上只含页码/图注开头"
            + ("和正文开头" if show_text else "") + "，可以截图发给开发者）")
    else:
        out("（本命令只读本机缓存：未上传、未调用模型、未输出论文内容）")
    return 0
