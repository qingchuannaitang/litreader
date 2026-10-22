"""Stage 6: templates CLI and the template step inside the one-paper run (confirm / override / modules / cancel /
named template / ask mode / NL refresh). No network."""
import json
import shutil
import sys
from pathlib import Path

import pytest

from litreader import appconfig, cli, realrun

sys.path.insert(0, str(Path(__file__).parent))
from test_realrun import ScriptUI, go, setup_run, kr  # noqa: E402,F401

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "templates"


def tx_factory(study, seen):
    """Fake LLM: classification answer, writer answer (records the system prompt), topic answer."""
    def tx(url, headers, body, timeout):
        req = json.loads(body)
        sysmsg = req["messages"][0]["content"]
        seen.append(sysmsg)
        if "研究设计类型" in sysmsg:
            out = study
        elif "主题文件夹" in sysmsg:
            out = {"choice": "existing", "folder": "认知与步态", "reason": "相近"}
        else:
            out = {"meta": {"title_zh": {"value": "步态研究", "label": "INFERENCE"}}, "facts": [],
                   "module_fields": {"reference_standard": {"text": "共纳入 89 名老年人", "label": "PAPER",
                                                            "basis_block_ids": ["b1"], "link_label": "方法"}}}
        return 200, json.dumps({"choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}],
                                "usage": {"prompt_tokens": 9, "completion_tokens": 3}}).encode()
    return tx


DIAG = {"study_type": "diagnostic_accuracy", "confidence": 0.85, "reason": "评价诊断准确性",
        "quote": "共纳入 89 名老年人", "block_id": "b1"}


def lib_of(cfg):
    p = cfg.vault_root / cfg.templates_dir
    p.mkdir(exist_ok=True)
    return p


def test_run_picks_specialised_template_with_module_and_records_provenance(tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path)
    shutil.copy(FIX / "diag_main.md", lib_of(cfg) / "诊断模板.md")
    before = (lib_of(cfg) / "诊断模板.md").read_bytes()
    seen = []
    r, ui, _, _ = go(cfg, tmp_path, ["y", ""], tx=tx_factory(DIAG, seen))
    assert "论文类型：诊断准确性研究（模型判定；依据：「共纳入 89 名老年人」p1" in ui.text
    assert "本次使用：诊断与预测模型精读（模板库 v1） ＋ 诊断准确性与预测模型评价模块" in ui.text
    assert "与本篇研究设计匹配的专用主模板" in ui.text
    note = Path(r["note"]).read_text("utf-8")
    ev = Path(r["evidence"]).read_text("utf-8")     # G10-7: provenance in the evidence file; id kept under litreader:
    assert '  template_id: "user.diag_main"' in note and '"template_version": "1.0.0+r1"' in ev
    assert '"module.diagnostic@r1"' in ev and '"study_type": "diagnostic_accuracy"' in ev and "template_sha256" not in note
    assert "## 三、推导集与验证集结果" in note and "### 诊断准确性与预测模型专项评价（专业模块）" in note
    assert "**参考标准：** 共纳入 89 名老年人" in note
    writer_sys = next(s for s in seen if "TEMPLATE_DATA" in s)
    assert "推导集与外部验证集" in writer_sys and "reference_standard" in writer_sys
    assert r["template"]["registry_snapshot"] >= 1 and r["template"]["study"]["source"] == "llm"
    assert (lib_of(cfg) / "诊断模板.md").read_bytes() == before
    ev = Path(r["evidence"]).read_text("utf-8")
    assert '"template_id": "user.diag_main"' in ev


def test_override_to_spec_a_and_cancel_at_template_step(tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path)
    seen = []
    study = {**DIAG, "study_type": "cross_sectional"}
    r, ui, _, _ = go(cfg, tmp_path, ["y", "2", ""], tx=tx_factory(study, seen))
    note = Path(r["note"]).read_text("utf-8")
    assert "## 一、研究背景与科学问题" in note and 'template_id: "main.spec_appendix_a"' in note
    assert r["template"]["user_override"] is True and "TEMPLATE_DATA" not in "".join(seen)
    seen.clear()
    with pytest.raises(realrun.Cancelled, match="未调用主笔模型"):
        go(cfg, tmp_path, ["y", "q"], tx=tx_factory(study, seen))
    assert not any("精读笔记（L2）" in s for s in seen)            # writer never called


def test_named_template_in_command_and_ask_mode(tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path)
    seen = []
    r, ui, _, _ = go(cfg, tmp_path, ["y", ""], tx=tx_factory(DIAG, seen),
                     command="用规范附录A模板精读zotero中的Gait study title，并将精读笔记存入obsidian中")
    assert r["template"]["template_id"] == "main.spec_appendix_a" and "你本次指定" in ui.text
    cfg2 = appconfig.load(str(cfg.path))
    object.__setattr__(cfg2, "template_selection", "ask")
    r, ui, _, _ = go(cfg2, tmp_path, ["y", "", "1", ""], tx=tx_factory(DIAG, []))
    assert "请输入序号选择主模板" in ui.text and "无效输入" in ui.text


def test_ambiguous_type_forces_choice_and_modules_menu(tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path)
    bad = {"study_type": "rct", "confidence": 0.9, "quote": "not in the paper", "block_id": "b1"}
    r, ui, _, _ = go(cfg, tmp_path, ["y", "m", "0", "1", ""], tx=tx_factory(bad, []))
    assert "依据引文未逐字见于原文" in ui.text and "论文类型或模板存在歧义" in ui.text
    assert r["template"]["modules"] == [] and r["template"]["study"]["confidence"] == 0.0


def test_malicious_library_template_needs_review_is_never_used(tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path)
    shutil.copy(FIX / "malicious_injection.md", lib_of(cfg) / "好模板.md")
    before = set(vault.rglob("*"))
    seen = []
    r, ui, _, _ = go(cfg, tmp_path, ["y", ""], tx=tx_factory({**DIAG, "study_type": "cohort"}, seen))
    assert "user.evil v1 → 待审" in ui.text and r["template"]["template_id"] == "main.general"
    assert "evil.example" not in "".join(seen) and "忽略之前" not in "".join(seen)
    new = set(vault.rglob("*")) - before
    assert all(cfg.dry_run_root in p.parents or p == cfg.dry_run_root for p in new)


def test_cli_templates_commands(tmp_path, kr, capsys, monkeypatch):
    vault, pdf, cfg = setup_run(tmp_path)
    shutil.copy(FIX / "diag_main.md", lib_of(cfg) / "d.md")
    shutil.copy(FIX / "no_frontmatter.md", lib_of(cfg) / "n.md")
    c = ["--config", str(cfg.path), "templates"]
    assert cli.main(c + ["refresh"]) == 0
    out = capsys.readouterr().out
    assert "登记快照 #1" in out and "user.diag_main" in out
    assert cli.main(c + ["list"]) == 0
    out = capsys.readouterr().out
    assert "main.spec_appendix_a" in out and "待审" in out and "overview.v2" in out
    assert cli.main(c + ["show", "user.diag_main"]) == 0
    out = capsys.readouterr().out
    assert "送入模型的内容" in out and "推导集与外部验证集" in out and "版本历史：v1" in out
    assert cli.main(c + ["prefer", "main.spec_appendix_a"]) == 0
    assert cli.main(c + ["prefer", "user.diag_main", "--for", "prediction_model"]) == 0
    assert cli.main(c + ["pin", "user.diag_main@1"]) == 0 and cli.main(c + ["unpin", "user.diag_main"]) == 0
    assert cli.main(c + ["rollback", "user.diag_main"]) == 1          # no older version -> clear STOP
    from litreader.templates.session import registry_for
    snap = registry_for(cfg).snapshot()
    nofm = next(r for r in snap["records"] if r["path"] == "n.md")
    assert cli.main(c + ["approve", f"{nofm['id']}@1"]) == 1          # no role/types -> refuses
    assert cli.main(c + ["approve", f"{nofm['id']}@1", "--role", "main", "--types", "any"]) == 0
    assert cli.main(c + ["export", "main.general"]) == 0
    exp = cfg.dry_run_root / "模板导出" / "单篇科研精读笔记_V2.0.md"
    from litreader.templates import builtin
    assert exp.read_bytes() == builtin.raw("main.general")
    assert cli.main(c + ["export", "main.general"]) == 1               # never overwrites
    assert cli.main(c + ["disable", "main.general"]) == 1
    assert cli.main(c + ["lint", str(FIX / "malicious_injection.md")]) == 0
    assert cli.main(c + ["recover", "--yes"]) == 0
    capsys.readouterr()
    assert cli.main(c + ["list", "--all"]) == 0
    assert "默认主模板" in capsys.readouterr().out
    assert (lib_of(cfg) / "d.md").read_bytes() == (FIX / "diag_main.md").read_bytes()


def test_cli_draft_with_fake_model(tmp_path, kr, capsys, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path)
    sample = tmp_path / "样例笔记.md"
    sample.write_text("# 某论文\n\n## 一、背景\n文字\n## 二、我的特色\n文字\n", "utf-8")
    ans = {"study_types": ["any"], "sections": [{"title": "一、背景", "data": "s1", "blocks": ["paragraphs"]},
                                                {"title": "二、我的特色", "data": None, "blocks": ["paragraphs"]}]}

    def tx(url, headers, body, timeout):
        assert "不可信" in json.loads(body)["messages"][0]["content"]
        return 200, json.dumps({"choices": [{"message": {"content": json.dumps(ans, ensure_ascii=False)}}], "usage": {}}).encode()
    from litreader import cli_templates
    from types import SimpleNamespace
    a = SimpleNamespace(action="draft", config=str(cfg.path), target=str(sample), id="user.mine", title="我的模板")
    assert cli_templates.cmd_templates(a, tx) == 0
    out = capsys.readouterr().out
    assert "user.mine@1" in out and "待审" in out


def test_nl_refresh_command_does_not_run_paper(tmp_path, kr, capsys):
    vault, pdf, cfg = setup_run(tmp_path)
    assert cli.run_command("刷新模板库", str(cfg.path), ScriptUI([])) == 0
    assert "登记快照" in capsys.readouterr().out and not cfg.dry_run_root.exists()


def test_manual_modules_survive_main_switch(tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path)
    study = {**DIAG, "study_type": "cross_sectional", "secondary": ["diagnostic_accuracy"]}
    r, ui, _, _ = go(cfg, tmp_path, ["y", "m", "2", "2", ""], tx=tx_factory(study, []))
    assert "适用于次要类型，可按 m 手动添加" in ui.text
    assert r["template"]["template_id"] == "main.spec_appendix_a"
    assert [m["id"] for m in r["template"]["modules"]] == ["module.methods"]
    note = Path(r["note"]).read_text("utf-8")
    sec6 = note.split("## 六、方法学评价、局限与UNKNOWN")[1].split("## 七、")[0]
    assert "### 方法学/技术/AI 研究专项评价（专业模块）" in sec6 and "按对结论、临床适用性" in sec6
