"""Review 2 follow-up (approved): vision statements in Chinese with the English original in parentheses."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_note_v2 as T  # noqa: E402

from litreader.analysis import crosscheck, vision  # noqa: E402
from litreader.analysis.validator_v2 import validate_v2  # noqa: E402
from litreader.analysis.zh_terms import bilingual  # noqa: E402


def test_prompts_require_chinese_with_english_in_parentheses():
    assert "双相机（2 Cams）" in vision.PROMPT and "不得出现括号外的英文词组" in vision.PROMPT
    assert "双相机（2 Cams）" in crosscheck.JUDGE and "quote 保持原文逐字" in crosscheck.JUDGE


def test_bare_english_repaired_or_flagged_names_kept():
    assert bilingual("2 Cams 下 DeepGaitLab 的 RMSD 更低（p<0.0001）")[0] == "双相机（2 Cams）下 DeepGaitLab 的 RMSD 更低（p<0.0001）"
    assert bilingual("10 Cams 下与 Theia3D 无显著差异 ns")[0] == "十相机（10 Cams）下与 Theia3D 无显著差异 ns"
    assert bilingual("Landmark template 显示 57 个点")[0] == "标志点模板（Landmark template）显示 57 个点"
    assert bilingual("左侧为 knee flexion 曲线")[0] == "左侧为膝屈曲（knee flexion）曲线"
    new, recs = bilingual("Some odd label 出现在 A 面板")
    assert new == "Some odd label（英文原文，未译）出现在 A 面板" and recs[0]["rule"] == "zh_terms.flag"
    assert bilingual("Vicon 系统为金标准", "Vicon motion capture")[0] == "Vicon 系统为金标准"   # proper name in the paper
    for keep in ("双相机（2 Cams）", "原文「Lateral step-down task」", "OpenCap vs. Theia3D", "N=1 例"):
        assert bilingual(keep) == (keep, [])


def test_render_applies_post_check_to_vision_but_not_caption_or_quote():
    man = [{**T.MAN[0], "caption": "图 1 | Overground walking with 2 Cams 招募流程图。"}]
    obs = {"Fig1": {"finding": "x", "numbers": [], "unreadable": "Box plot 中位数不可读", "model": "vm"}}
    cross = {"Fig1": [{"claim": "2 Cams 下共纳入 79 名", "verdict": "CONSISTENT", "page": 2, "quote": "共纳入 79 名",
                       "block_id": "b2", "reason": ""},
                      {"claim": "Overground walking 无差异", "verdict": "CONTRADICTED", "page": 2,
                       "quote": "膝伸展角增加", "block_id": "b2", "reason": "冲突"}]}
    v = validate_v2(T.good(), T.BLOCKS, man)
    md = T.render(v, blocks=T.BLOCKS, manifest=man, vision_obs=obs, figure_paths={}, attachment_key="A", parent_key="K",
                  e_level="E3", translation_notice=None, link_mechanism_verified=False, read_date="d", evidence_link="ev",
                  model_info={"text": "m", "vision": "vm"}, crosscheck=cross)
    assert "双相机（2 Cams）下共纳入 79 名" in md
    assert "地面行走（Overground walking）无差异" in md and "「膝伸展角增加」" in md
    assert "箱线图（Box plot）中位数不可读" in md
    assert "图 1 | Overground walking with 2 Cams 招募流程图" in md                  # caption verbatim
    assert any(w["gate"] == "zh_terms.glossary" for w in v.wording)               # recorded for the evidence file


def test_r4_camera_lists_are_repaired_as_one_phrase():
    assert bilingual("6/10 Cams 下 DeepGaitLab 自动校准更低")[0] == "6/10 台相机（6/10 Cams）下 DeepGaitLab 自动校准更低"
    assert bilingual("按 2/6/10 Cams 三组")[0] == "按 2/6/10 台相机（2/6/10 Cams）三组"
    assert bilingual("2 Cams 与 10 Cams")[0] == "双相机（2 Cams）与十相机（10 Cams）"
