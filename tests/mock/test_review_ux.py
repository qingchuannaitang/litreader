"""DeepGaitLab review UX fixes: template prompt confirms on the current number; topic prompt accepts Enter."""
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
from test_realrun import ScriptUI  # noqa: E402
from test_templates_select import ABSTRACTS, CHAIN, blocks_for, tx_answer  # noqa: E402

from litreader import realrun  # noqa: E402
from litreader.templates import session  # noqa: E402


def _prepare(tmp_path, answers):
    cfg = SimpleNamespace(vault_root=tmp_path, templates_dir=None, data_dir=tmp_path / "data")
    ui = ScriptUI(answers)
    fr = session.prepare(cfg, ui, blocks_for(ABSTRACTS["rct"]), title="T", zotero_tags=["随机对照试验"], chain=CHAIN,
                         transport=tx_answer({}), env={"K": "k"}, requested=None)
    return fr, ui


def test_typing_current_template_number_confirms(tmp_path):
    fr0, ui0 = _prepare(tmp_path, [""])
    cur = next(l for l in ui0.out if l.endswith("← 本次"))
    n = re.match(r"\s*(\d+)\.", cur).group(1)
    fr, ui = _prepare(tmp_path, [n])          # one answer only: a second prompt would fail ScriptUI
    assert fr.main_rec["id"] == fr0.main_rec["id"] and len(ui.prompts) == 1


def test_topic_enter_accepts_suggestion_and_hint_says_so():
    ui = ScriptUI([""])
    got = realrun.choose_topic({"choice": "new", "folder": "步态分析与AI工具", "reason": "r"}, ["老年步态"], ui)
    assert got == "步态分析与AI工具" and "回车 = 新建「步态分析与AI工具」" in ui.prompts[0]
    assert realrun.choose_topic({"choice": "new", "folder": "X主题"}, ["老年步态"], ScriptUI(["1"])) == "老年步态"
