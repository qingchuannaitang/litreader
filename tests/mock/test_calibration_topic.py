"""Decisions 3 + 4 (2026-10-18): per-model token calibration; topic folder suggestions + custom name."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_realrun import ScriptUI, go, kr, setup_run, topic_llm  # noqa: E402,F401

from litreader import calibration as C  # noqa: E402
from litreader import realrun  # noqa: E402
from litreader.vault import topics  # noqa: E402

DEF = {"roles": {"writer": {"in": 10000, "out": 4000}, "judge": {"in": 20000, "out": 5000}}}


def _est():
    return json.loads(json.dumps(DEF))


def test_store_lives_outside_the_vault(tmp_path):
    with pytest.raises(ValueError):
        C.Store(tmp_path / "vault" / ".litreader", tmp_path / "vault")
    s = C.Store(tmp_path / "appdata", tmp_path / "vault")
    assert s.load() == {"version": 1, "models": {}} and s.records("x") == []


def test_uncalibrated_uses_default_ratios_with_wider_range_and_says_why(tmp_path):
    s = C.Store(tmp_path / "a")
    e = C.apply(_est(), {"writer": ("Kimi", "k2"), "judge": ("Kimi", "k2")}, s)
    w = e["roles"]["writer"]
    assert (w["in"], w["out"]) == (10000, 4000) and w["calibration"]["spread"] == C.SPREAD_DEFAULT > 0.4
    assert "按默认比例估算，误差较大" in w["calibration"]["label"] and "分词器（tokenizer）" in w["calibration"]["label"]
    s.add(C.key("Kimi", "k2", "writer"), {"est_in": 1, "est_out": 1, "act_in": 1, "act_out": 1})
    s.add(C.key("Kimi", "k2", "writer"), {"est_in": 1, "est_out": 1, "act_in": 1, "act_out": 1})
    st = C.apply(_est(), {"writer": ("Kimi", "k2")}, s)["roles"]["writer"]["calibration"]
    assert not st["calibrated"] and "已实测 2 篇，还需 1 篇才启用本模型校准" in st["label"]
    assert C.slot_line(s.records(C.key("Kimi", "k2", "writer"))) == "已实测 2 篇，还需 1 篇才启用本模型校准"


def test_three_runs_calibrate_by_median_and_records_stay_against_the_default(tmp_path):
    s = C.Store(tmp_path / "a")
    used = lambda i, o: {"writer": {"providers": [("Kimi", "k2")], "in": i, "out": o}}
    for i, o in [(12000, 6000), (13000, 6400), (11000, 6200)]:
        e = C.apply(_est(), {"writer": ("Kimi", "k2")}, s)
        r = C.record(s, e, used(i, o), item_key="K", chars=1, figures=0)
    assert r["writer"] == {"recorded": True, "key": "Kimi|k2|writer", "n": 3, "calibrated_next": True}
    assert all(x["est_in"] == 10000 and x["est_out"] == 4000 for x in s.records("Kimi|k2|writer"))   # no compounding
    w = C.apply(_est(), {"writer": ("Kimi", "k2"), "judge": ("Kimi", "k2")}, s)["roles"]
    assert (w["writer"]["in"], w["writer"]["out"]) == (12000, 6200) and w["writer"]["base_in"] == 10000
    assert w["writer"]["calibration"]["label"] == "按本机 3 篇实测校准" and C.SPREAD_MIN <= w["writer"]["calibration"]["spread"] < 0.6
    assert not w["judge"]["calibration"]["calibrated"]                         # per role: judge still default
    other = C.apply(_est(), {"writer": ("Kimi", "k2-mini")}, s)["roles"]["writer"]
    assert other["in"] == 10000                                                 # per model id


def test_role_served_by_two_models_is_not_recorded(tmp_path):
    s = C.Store(tmp_path / "a")
    e = C.apply(_est(), {"writer": ("A", "m")}, s)
    r = C.record(s, e, {"writer": {"providers": [("A", "m"), ("B", "n")], "in": 1, "out": 1}}, item_key="K")
    assert r["writer"]["recorded"] is False and s.load()["models"] == {}


def test_real_run_records_calibration_in_app_dir_and_receipt(tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path, prices=(2, 8))
    r, ui, _, _ = go(cfg, tmp_path, ["y", ""])
    rec = r["calibration"]["recorded"]["writer"]
    assert rec["n"] == 1 and rec["key"].endswith("|writer")
    # a 2nd paper measured earlier (same model) — a 3rd note of one title in one folder would exhaust the file names
    C.Store(cfg.data_dir).add(rec["key"], C.Store(cfg.data_dir).records(rec["key"])[0])
    r, ui, _, _ = go(cfg, tmp_path, ["y", ""])
    assert r["calibration"]["recorded"]["writer"]["n"] == 3
    assert "按默认比例估算，误差较大" in ui.text and "按你填的单价" in ui.text
    store = Path(r["calibration"]["store"])
    assert store.is_file() and tmp_path / "appdata" in store.parents and vault not in store.parents
    assert not list(vault.rglob("calibration*"))
    r4, ui4, _, _ = go(cfg, tmp_path, ["y", ""])
    cal = r4["calibration"]["estimate"]["writer"]
    assert cal["calibrated"] and "按本机 3 篇实测校准" in ui4.text
    assert r4["estimate"]["roles"]["writer"]["in"] == round(r4["estimate"]["roles"]["writer"]["base_in"] * cal["in_ratio"])
    saved = json.loads(Path(r4["receipt"]).read_text("utf-8"))
    assert saved["calibration"]["estimate"]["writer"]["label"] == "按本机 3 篇实测校准"


def test_clean_name_validates_and_matches_existing_case_insensitively():
    ex = ["Gait AI", "老年步态"]
    assert topics.clean_name("gait ai", ex) == ("Gait AI", "")
    assert topics.clean_name("  步态/传感器 ", ex)[0] == "步态 传感器"
    for bad in ["", "   ", "_系统", ".隐藏", "论文库", "x" * 41]:
        assert topics.clean_name(bad, ex)[0] is None, bad


def test_uncertain_topic_lists_suggestions_existing_and_custom_name():
    sug = {"choice": "existing", "folder": "老年步态", "reason": "r", "confident": False, "alternatives": ["步态传感器"]}
    ui = ScriptUI(["b"])
    assert realrun.choose_topic(sug, ["老年步态", "认知"], ui) == "步态传感器"
    assert "拿不准" in ui.text and "a. 老年步态（已有）" in ui.text and "b. 步态传感器（新建）" in ui.text
    assert "直接输入其他新名称" in ui.prompts[0]
    assert realrun.choose_topic(sug, ["老年步态", "认知"], ScriptUI([""])) == "老年步态"
    assert realrun.choose_topic(sug, ["老年步态", "认知"], ScriptUI(["2"])) == "认知"
    ui = ScriptUI(["_坏", "9", "无标记 / 步态", "y"])
    assert realrun.choose_topic(sug, ["老年步态", "认知"], ui) == "无标记 步态"
    assert "无效名称：不能以 _ 或 . 开头" in ui.text and "序号不存在" in ui.text and "确认新建「无标记 步态」" in ui.prompts[-1]
    assert realrun.choose_topic(sug, ["老年步态", "认知"], ScriptUI(["认知"])) == "认知"   # existing name, no confirm
    assert realrun.choose_topic({"choice": "existing", "folder": "认知", "reason": "r"}, ["认知"], ScriptUI([])) == "认知"


def test_custom_new_topic_is_created_only_in_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")   # fake (W2: env is hermetic)
    vault, pdf, cfg = setup_run(tmp_path)
    r, ui, _, _ = go(cfg, tmp_path, ["y", "", "无标记步态", "y"], tx=topic_llm("new", "老年步态力学"))
    assert "论文库/无标记步态/" in r["note"] and r["topic"]["new"] is True
    assert (cfg.dry_run_root / "论文库" / "无标记步态").is_dir() and not (vault / "论文库" / "无标记步态").exists()
