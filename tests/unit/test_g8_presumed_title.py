from litreader.render.l2_note_v2 import vision_topic, questionize


def test_vision_topic_drops_panel_lead_and_keeps_first_clause():
    assert vision_topic("上图中，环境特定微调使步态误差显著下降。其余略") == "环境特定微调使步态误差显著下降"
    assert vision_topic("") == "" and vision_topic("短") == ""


def test_presumed_heading_is_not_generic():
    h = questionize(vision_topic("不同地形下的误差对比，平地最低"))
    assert h == "不同地形下的误差对比——说明了什么？" and "这张图" not in h


def test_g10_generic_chart_type_is_skipped():
    from litreader.render.l2_note_v2 import generic_topic
    assert generic_topic("三幅箱线图") and generic_topic("两个面板") and generic_topic("箱线图")
    assert not generic_topic("环境特定微调的改善量")
    assert vision_topic("三幅箱线图") == ""
    assert vision_topic("三幅箱线图，分别展示运动学改善量") == "运动学改善量"
    assert vision_topic("上图纵轴为运动学RMSD改善量（°）；上图总计标有星号") == "运动学RMSD改善量（°）"


def test_g10_cached_vision_without_title_is_reread_only_for_uncaptioned(tmp_path):
    import json
    from types import SimpleNamespace
    from litreader.analysis import vision
    img = tmp_path / "a.jpg"
    img.write_bytes(b"\xff\xd8x")
    calls = []

    def fake_observe(fig, root, chain, tx, env):
        calls.append(fig["id"])
        return {"title": "环境特定微调后的运动学改善", "finding": "f", "numbers": [], "unreadable": "", "model": "m"}, \
            {"id": fig["id"], "status": "OK"}
    orig = vision.observe
    vision.observe = fake_observe
    try:
        chain = [SimpleNamespace(model="m")]
        for cap in ("", "Figure 2. x"):
            fig = {"id": "F" + str(len(cap)), "caption": cap, "parts": [{"img_path": "a.jpg"}]}
            key = f"K_{fig['id']}_{vision.figure_hash(fig, tmp_path)}_m"
            (tmp_path / "vc").mkdir(exist_ok=True)
            (tmp_path / "vc" / f"{key}.json").write_text(json.dumps(
                {"obs": {"finding": "三幅箱线图", "numbers": [], "unreadable": "", "model": "m"}, "info": {"status": "OK"}}))
            obs, info = vision.cached_observe(fig, tmp_path, chain, None, {}, tmp_path / "vc", "K")
            if cap:
                assert "title" not in obs and info.get("cached")           # captioned: old cache reused, no cost
            else:
                assert obs["title"] == "环境特定微调后的运动学改善"         # uncaptioned: read again once
        assert calls == ["F0"]
    finally:
        vision.observe = orig
