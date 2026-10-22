"""G11-2: the v1.0.1 DeepGaitLab note still said 「图7（推定，图注缺失）｜这张图显示了什么？」. Root cause: the cached v1.0
vision reading had no "title", G10-2 re-read that figure, the re-read did not return OK and the old finding was thrown
away -> no vision obs, no writer finding, no caption. Fixes: keep the cached reading when the re-read fails; and, with
no vision at all, take the topic from the note's own verified paragraph citing the figure's page."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import test_note_v2 as T  # noqa: E402

from litreader.analysis import vision  # noqa: E402
from litreader.analysis.validator_v2 import validate_v2  # noqa: E402
from litreader.parse.blocks import Block  # noqa: E402
from litreader.render.l2_note_v2 import text_topic  # noqa: E402

FACT = "环境特定微调在平地行走中改善为 3.4 ± 0.7° 对 3.8 ± 0.6°（p=0.0250）"


def test_text_topic():
    assert text_topic(FACT) == "环境特定微调在平地行走中改善"
    assert text_topic("Fine-tuning improved 3.4") == "" and text_topic("三幅箱线图") == ""


def _render(vision_obs=None):
    blocks = T.BLOCKS + [Block(kind="text", physical_page=21, bbox_norm=None, order=5,
                               text="Fine-tuning improved overground walking (3.4 ± 0.7° vs 3.8 ± 0.6°, p = 0.0250)."),
                         Block(kind="figure", physical_page=21, bbox_norm=None, order=6, text="", img_path="images/u.jpg")]
    man = T.MAN + [{"id": "Fig6", "kind": "figure", "number": "6", "caption": "图 6. 自动校准。", "flags": [],
                    "parts": [{"img_path": "images/f6.jpg", "physical_page": 20}]},
                   {"id": "Fig8", "kind": "figure", "number": "8", "caption": "图 8. 网络。", "flags": [],
                    "parts": [{"img_path": "images/f8.jpg", "physical_page": 29}]},
                   {"id": "figure_unnumbered_7", "kind": "figure", "number": None, "caption": "", "flags":
                    ["UNCAPTIONED", "UNCAPTIONED_ORPHAN", "SUBFIGURES_MERGED"],
                    "parts": [{"img_path": "images/u.jpg", "physical_page": 21}]}]
    a = T.good()
    a["sections"]["s4"] = {"heading_suffix": "结果如何？", "paragraphs": [T.S(FACT, ids=("b5",))]}   # the note's own Chinese paragraph citing p21
    a["figures"] = [{"id": m["id"], "section": "s4", "title": ""} for m in man]
    v = validate_v2(a, blocks, man)
    return T.render(v, blocks=blocks, manifest=man, vision_obs=vision_obs, figure_paths={}, attachment_key="A",
                    parent_key="K", e_level="E3", translation_notice=None, link_mechanism_verified=False,
                    read_date="d", evidence_link="ev", model_info={"text": "m"})


def test_presumed_fig7_without_vision_gets_specific_title():
    head = next(l for l in _render().splitlines() if l.startswith("### 图7"))
    assert "这张图显示了什么" not in head and "环境特定微调在平地行走中改善" in head, head


def test_presumed_fig7_with_old_vision_finding_uses_it():
    obs = {"figure_unnumbered_7": {"finding": "上图纵轴为运动学RMSD改善量（°）；上图总计标有星号", "numbers": [],
                                   "unreadable": "", "model": "M"}}
    head = next(l for l in _render(obs).splitlines() if l.startswith("### 图7"))
    assert "运动学RMSD改善量" in head, head


def test_failed_title_reread_keeps_cached_reading(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"\xff\xd8x")
    fig = {"id": "figure_unnumbered_7", "caption": "", "parts": [{"img_path": "a.jpg"}]}
    key = f"K_figure_unnumbered_7_{vision.figure_hash(fig, tmp_path)}_m"
    (tmp_path / "vc").mkdir()
    (tmp_path / "vc" / f"{key}.json").write_text(json.dumps(
        {"obs": {"finding": "上图纵轴为运动学RMSD改善量（°）", "numbers": [], "unreadable": "", "model": "m"},
         "info": {"status": "OK"}}))
    orig = vision.observe
    vision.observe = lambda *a: (None, {"id": fig["id"], "status": "BAD_OUTPUT"})
    try:
        obs, info = vision.cached_observe(fig, tmp_path, [SimpleNamespace(model="m")], None, {}, tmp_path / "vc", "K")
    finally:
        vision.observe = orig
    assert obs["finding"].startswith("上图纵轴") and info["refresh_failed"] == "BAD_OUTPUT"
