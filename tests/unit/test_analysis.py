"""Unit layer: chunking, validator, L2 renderer (synthetic blocks, no network)."""
import json

from litreader.analysis.chunking import block_text, chunk, sections
from litreader.analysis.schema import REQUIRED_FIELDS
from litreader.analysis.validator import validate
from litreader.parse.blocks import Block
from litreader.render import protected_zone
from litreader.render.l2_note import render


def B(order, kind, page, text="", **kw):
    return Block(kind=kind, physical_page=page, bbox_norm=None, text=text, order=order, **kw)


BLOCKS = [
    B(0, "title", 1, "某步态研究"), B(1, "header", 1, "Frontiers"),
    B(2, "text", 1, "本研究共纳入 89 名老年人，其中 MCI 组 31 人。"),
    B(3, "title", 2, "统计分析"), B(4, "text", 2, "采用单因素方差分析（ANOVA），显著性水平 P < 0.05。"),
    B(5, "table", 3, "", caption="表 1 基本特征", table_html="<table><tr><td>年龄</td><td>70.1±5.2</td></tr></table>"),
    B(6, "reference", 4, "[1] Someone 2020"),
]


def fact(**kw):
    base = {"field": "sample_size_total", "value": "89", "context": "本研究共纳入 89 名老年人", "block_id": "b2",
            "physical_page": 1, "label": "PAPER"}
    base.update(kw)
    return base


def test_sections_exclude_noise_and_split_on_titles():
    ss = sections(BLOCKS)
    assert [s.title for s in ss] == ["某步态研究", "统计分析"]
    ids = [b.order for s in ss for b in s.blocks]
    assert 1 in ids            # page-1 masthead kept (DOI/journal metadata)
    assert 6 not in ids and 5 in ids
    assert 7 not in [b.order for s in sections(BLOCKS + [B(7, "header", 2, "running head")]) for b in s.blocks]


def test_chunk_keeps_sections_whole_and_splits_when_needed():
    assert len(chunk(BLOCKS, 100000)) == 1
    cs = chunk(BLOCKS, 60)
    assert len(cs) >= 2 and all(c.blocks for c in cs)
    assert "[b2|p1|text]" in chunk(BLOCKS)[0].render()


def test_table_text_is_checkable():
    assert "70.1±5.2" in block_text(BLOCKS[5])


def test_valid_paper_fact_passes():
    r = validate({"facts": [fact()]}, BLOCKS)
    assert r.counts["facts_paper_ok"] == 1 and not r.rejected


def test_fact_from_table_passes():
    r = validate({"facts": [fact(field="age", value="70.1±5.2", context="年龄 | 70.1±5.2", block_id="b5", physical_page=3)]}, BLOCKS)
    assert not r.rejected


def test_rejections():
    bad = [fact(physical_page=2),                                   # page mismatch
           fact(context="本研究共纳入 90 名老年人", value="90"),     # not verbatim
           fact(value="31"),                                         # value not in context
           fact(block_id="b99"),                                     # unknown block
           fact(label="INFERENCE"),                                  # inference not allowed as fact
           fact(value="{{n}}", context="{{n}}"),                     # placeholder
           fact(label="UNKNOWN"),                                    # UNKNOWN with value
           fact(context=None)]
    r = validate({"facts": bad}, BLOCKS)
    assert len(r.rejected) == len(bad) and r.counts["facts_paper_ok"] == 0
    reasons = " ".join(x["reason"] for x in r.rejected)
    for s in ("page", "verbatim", "inside context", "not found", "label", "placeholder", "carries a value", "missing"):
        assert s in reasons


def test_whitespace_and_fullwidth_normalised():
    assert not validate({"facts": [fact(context="本研究共纳入８９名老年人", value="８９")]}, BLOCKS).rejected


def test_required_fields_enforced_unknown():
    r = validate({"facts": [fact()]}, BLOCKS)
    assert set(r.enforced_unknown) == set(REQUIRED_FIELDS) - {"sample_size_total"}
    assert all(f["value"] is None for f in r.facts if f["label"] == "UNKNOWN")


def test_claims_need_existing_basis():
    r = validate({"claims": [{"text": "a", "label": "INFERENCE", "basis_block_ids": ["b2"], "kind": "evaluation"},
                             {"text": "b", "label": "INFERENCE", "basis_block_ids": [], "kind": "summary"},
                             {"text": "c", "label": "PAPER", "basis_block_ids": ["b404"], "kind": "summary"},
                             {"text": "TODO", "label": "PAPER", "basis_block_ids": ["b2"], "kind": "summary"}]}, BLOCKS)
    assert len(r.claims) == 1 and len(r.rejected) == 3


def test_title_validation():
    r = validate({"title_zh": {"value": "某步态研究", "block_id": "b0", "physical_page": 1, "label": "PAPER"},
                  "title_en": {"value": "Fake English", "block_id": "b0", "physical_page": 1, "label": "PAPER"}}, BLOCKS)
    assert r.title_zh["value"] == "某步态研究" and r.title_en["label"] == "UNKNOWN"


def test_render_l2():
    r = validate({"title_zh": {"value": "某步态研究", "block_id": "b0", "physical_page": 1, "label": "PAPER"},
                  "facts": [fact()],
                  "claims": [{"text": "样本较小", "label": "INFERENCE", "basis_block_ids": ["b2"], "kind": "evaluation"}]}, BLOCKS)
    md = render(r, attachment_key="7M6C5QRN", translation_notice="本 PDF 为中文译本。", link_mechanism_verified=True,
                e_level="E3", model="m")
    assert md.startswith("# 某步态研究（英文原题 UNKNOWN）")
    assert "zotero://open-pdf/library/items/7M6C5QRN?page=1) `UNVERIFIED`" in md
    assert "链接机制已核验" in md and "版本声明" in md and "`INFERENCE`" in md
    assert "{{" not in md and "TODO" not in md
    assert protected_zone.extract(md).strip() == ""


def test_html_markup_is_not_a_placeholder():
    blocks = BLOCKS + [B(9, "text", 1, "<sup>1</sup> 某医院，中国南京；")]
    r = validate({"facts": [fact(field="setting_country", value="中国南京", context="<sup>1</sup> 某医院，中国南京", block_id="b9")]}, blocks)
    assert not r.rejected
    assert validate({"facts": [fact(value="<填写人数>", context="<填写人数>")]}, BLOCKS).rejected
