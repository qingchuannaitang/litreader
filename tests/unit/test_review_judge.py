"""Review fix 4: CONTRADICTED only when panel and camera configuration align."""
import json

from litreader.analysis.crosscheck import cameras, caption_segments, contradiction_aligned, judge, panels
from litreader.llm.config import parse_config
from tests.fixtures.deepgaitlab import BLOCKS, FIG5_CAPTION

CFG = parse_config({"providers": {"j": {"protocol": "openai_compatible", "base_url": "https://j.example", "model": "jm",
                                        "key_env": "JK", "json_mode": True}}, "stations": {"judge": ["j"]}})


def test_parsers():
    assert cameras("两台相机的 DeepGaitLab 为 0.22，十台相机的 Theia3D") == {2, 10}
    assert cameras("双相机配置下") == {2} and cameras("OpenCap (2 Cams)") == {2}
    assert panels("B面板各活动") == {"B"} and panels("图3A中OpenCap") == {"A"} and panels("（图 5A）") == {"A"}
    assert "十相机" in caption_segments(FIG5_CAPTION)["B"]


def test_fig5_false_conflict_is_downgraded():
    # archive: claim 'B面板各活动与自由度均无显著差异' was CONTRADICTED by the 2-cam DeepGaitLab vs 10-cam Theia3D sentence
    q = "但在行走中则不然（两台相机的 DeepGaitLab 为 0.22±0.03，十台相机的 Theia3D 为 0.16±0.03, p<0.0001）"
    assert "camera configuration" in contradiction_aligned("B面板各活动与自由度均无显著差异", q, FIG5_CAPTION)
    fig = {"id": "Fig5", "kind": "figure", "number": "5", "caption": FIG5_CAPTION, "flags": [],
           "parts": [{"img_path": "x.jpg", "physical_page": 19, "order": 120}]}

    def t(url, h, body, timeout):
        return 200, json.dumps({"choices": [{"message": {"content": json.dumps({"claims": [
            {"claim": "B面板各活动与自由度均无显著差异", "verdict": "CONTRADICTED", "block_id": "b111", "quote": q, "reason": "x"}]})}}],
            "usage": {}}).encode()
    out, _ = judge(fig, {"finding": "x"}, BLOCKS, CFG.chain("judge"), t, {"JK": "k"})
    assert out[0]["verdict"] == "UNVERIFIABLE" and out[0]["gate"].startswith("contradiction downgraded")


def test_aligned_conflicts_stay():
    assert contradiction_aligned("图3B中OpenCap在髋屈/伸不对称上未显著偏离零", "OpenCap 成功检测到该不对称 (10.0±14.9°, p=0.0003)",
                                 "图 3. (A) 一致精度。(B) 捕捉不对称") is None
    assert contradiction_aligned("双相机下 DeepGaitLab 与 OpenCap 无显著差异", "两台相机时 rRMSD 低于 OpenCap（p<0.0001）") is None
    assert contradiction_aligned("A面板无差异", "（图 5B）差异显著") is not None
