from litreader.render.l2_note_v2 import dedupe_claims


def C(t, v="CONSISTENT"):
    return {"claim": t, "verdict": v, "page": 1, "quote": "q", "block_id": "b1", "reason": "r"}


def test_each_claim_once_conflict_wins():
    ok = [C("DeepGaitLab 在髋内收/外展力矩上显著低于 OpenCap"), C("DeepGaitLab 在髋内旋/外旋力矩上显著低于 OpenCap"),
          C("OpenCap在髋内收/外展不对称上标有*。")]
    unv = [C("DeepGaitLab 在髋内收/外展力矩上显著低于 OpenCap", "UNVERIFIABLE"), C("五个方法中位数偏正", "UNVERIFIABLE"),
           C("OpenCap 在髋内收外展不对称上标有星号*", "UNVERIFIABLE")]
    bad = [C("OpenCap在髋内收/外展不对称上标有*", "CONTRADICTED"), C("OpenCap 在髋内收/外展不对称上标有 *", "CONTRADICTED")]
    o, u, b = dedupe_claims(ok, unv, bad)
    assert [x["claim"] for x in b] == ["OpenCap在髋内收/外展不对称上标有*"]
    assert len(o) == 2 and all("不对称" not in x["claim"] for x in o)          # distinct consistent claims both kept
    assert [x["claim"] for x in u] == ["五个方法中位数偏正"]


def test_single_conflict_callout_in_note():
    import re
    from pathlib import Path
    src = (Path(__file__).parents[2] / "src/litreader/render/l2_note_v2.py").read_text("utf-8")
    assert src.count("[!warning] 读图与原文不一致") == 1 and "冲突：读图结果与正文/表格不一致" not in src
    assert re.search(r"if bad:", src)
