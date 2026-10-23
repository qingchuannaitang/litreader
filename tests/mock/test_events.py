"""Event bus + CLI adapter (Stage G1): the terminal must look exactly as before; structured events for the GUI."""
import sys
from pathlib import Path

import pytest

from litreader import cli, events, realrun
from litreader.events import BusUI, CliAdapter, EventBus

sys.path.insert(0, str(Path(__file__).parent))
from test_realrun import go, setup_run, topic_llm  # noqa: E402


class Rec:
    def __init__(self, answers):
        self.answers, self.events, self.prompts = list(answers), [], []

    def on(self, ev):
        self.events.append(ev)

    def respond(self, ev):
        self.prompts.append(ev["prompt"])
        assert self.answers, f"unexpected prompt {ev['prompt']}"
        return self.answers.pop(0)

    def of(self, t):
        return [e for e in self.events if e.type == t]


def bus_ui(answers):
    r = Rec(answers)
    ui = BusUI()
    ui.bus.subscribe(r.on)
    ui.bus.set_responder(r.respond)
    return ui, r


def test_bus_fanout_request_response_and_unknown_type():
    bus = EventBus()
    seen = []
    unsub = bus.subscribe(seen.append)
    bus.set_responder(lambda ev: "2")
    assert bus.request("candidate", "请输入序号：", [events.opt("1", "A"), events.opt("2", "B")]) == "2"
    req, resp = seen
    assert req.type == "decision_request" and req["kind"] == "candidate" and req["options"][1]["label"] == "B"
    assert resp.type == "decision_response" and resp["id"] == req["id"] and resp["choice"] == "2"
    unsub()
    bus.emit("log", level="info", text="x")
    assert len(seen) == 2
    with pytest.raises(ValueError):
        bus.emit("nope")
    with pytest.raises(RuntimeError):
        EventBus().request("text", "?")


def test_say_levels_and_yn_inference():
    ui, r = bus_ui(["y"])
    ui.say("⚠️ 注意"); ui.say("⛔ 已停止"); ui.say("普通")
    assert [e["level"] for e in r.of("log")] == ["warn", "error", "info"]
    assert ui.ask("同意？(y/n)：") == "y"
    req = r.of("decision_request")[0]
    assert req["kind"] == "text" and [o["key"] for o in req["options"]] == ["y", "n"] and req["allow_custom"]


def test_cli_adapter_prints_logs_only_and_reads_input():
    out, prompts = [], []
    ui = cli.ConsoleUI(out=out.append, inp=lambda p: prompts.append(p) or "1")
    ui.say("你好")
    events.stage(ui, "parse"); events.progress(ui, "vision", 1, 3); events.emit(ui, "done", note_path="x")
    assert events.decide(ui, "candidate", "请输入序号（q 取消）：", [events.opt("1", "A")]) == "1"
    assert out == ["你好"] and prompts == ["请输入序号（q 取消）："]


def test_cli_adapter_eof_means_q():
    def eof(p):
        raise EOFError
    a = CliAdapter(out=lambda m: None, inp=eof)
    assert a.respond(events.Event("decision_request", {"prompt": "x"})) == "q"


def test_console_ui_default_uses_print_and_input(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda p: "z")
    ui = cli.ConsoleUI()
    ui.say("一行")
    assert ui.ask("?") == "z" and capsys.readouterr().out == "一行\n"


def test_helpers_degrade_on_plain_say_ask_objects():
    class Plain:
        def __init__(self):
            self.p = []
        def say(self, m):
            pass
        def ask(self, p):
            self.p.append(p)
            return "ok"
    u = Plain()
    events.stage(u, "parse"); events.progress(u, "vision", 1, 2); events.emit(u, "done")
    assert events.decide(u, "cost", "是否继续？(y/n)：") == "ok" and u.p == ["是否继续？(y/n)："]


def test_cancel_takes_effect_at_next_stage():
    ui, r = bus_ui([])
    events.stage(ui, "parse")
    ui.cancel_requested.set()
    with pytest.raises(realrun.Cancelled):
        events.stage(ui, "vision")
    events.stage(ui, "vision", "done")   # done/skip markers never raise


def run_bus(cfg, tmp_path, answers, **kw):
    """go() with a BusUI instead of ScriptUI: same answers, same results."""
    from litreader.zotero.client import ZoteroClient
    from test_realrun import FakeMinerU, STATS, zot_fake
    zt, _ = zot_fake(tmp_path / "Zotero" / "storage")
    ui, rec = bus_ui(answers)
    f = FakeMinerU()
    res = realrun.run(cfg, "精读zotero中的Gait study title，并将精读笔记存入obsidian中", ui, zotero=ZoteroClient(zt),
                      llm_tx=kw.get("tx") or topic_llm("existing", "认知与步态"),
                      mineru_kwargs={"req": f.req, "put": f.put, "sleep": lambda s: None}, pages_fn=lambda p: 2,
                      stats_fn=STATS)
    return res, rec


def test_full_run_events_match_terminal_text(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path, prices=(2, 8))
    go(cfg, tmp_path, ["y", ""])                               # first run uploads; both runs below use the cache
    r_script, ui_script, _, _ = go(cfg, tmp_path, ["y", ""])
    res, rec = run_bus(cfg, tmp_path, ["y", ""])
    assert res["status"] == "DRY_RUN_COMPLETE"
    # same prompts as the plain say/ask path
    assert rec.prompts == ui_script.prompts
    kinds = [e["kind"] for e in rec.of("decision_request")]
    assert kinds == ["cost", "template"]
    cost = rec.of("decision_request")[0]
    assert cost["data"]["upload"] is False and cost["data"]["cost"]["priced"] and "writer" in cost["data"]["cost"]["roles"]
    assert [o["key"] for o in cost["options"]] == ["y", "n"]
    st = [(e["stage"], e["status"]) for e in rec.of("stage")]
    for s in ("zotero", "estimate", "parse", "template", "writer", "judge", "topic", "write"):
        assert (s, "start") in st and (s, "done") in st, s
    assert ("vision", "skip") in st and ("lens", "skip") in st
    assert st.index(("estimate", "done")) < st.index(("parse", "start")) < st.index(("write", "start"))
    done = rec.of("done")[0]
    assert done["note_path"] == res["note"] and done["receipt_path"] == res["receipt"] and done["usage"] == res["actual"]
    # log text identical to what the plain say/ask path printed (same lines; nothing added by the bus)
    logs = [e["text"] for e in rec.of("log")]
    assert len(logs) == len(ui_script.out)
    assert logs[:6] == ui_script.out[:6] and logs[-3:] == ui_script.out[-3:]


def test_topic_folder_decision_has_abc_existing_and_custom(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")   # fake (W2: env is hermetic)
    vault, pdf, cfg = setup_run(tmp_path)
    res, rec = run_bus(cfg, tmp_path, ["y", "", "我的新主题", "y"], tx=topic_llm("new", "老年步态力学"))
    tf = [e for e in rec.of("decision_request") if e["kind"] == "topic_folder"][0]
    assert tf["allow_custom"] and tf["options"][0]["key"] == "" and tf["options"][0]["label"] == "老年步态力学"
    assert any(o["label"] == "认知与步态" and o["key"] == "1" for o in tf["options"])
    assert rec.of("decision_request")[-1]["kind"] == "confirm"
    assert "论文库/我的新主题/" in res["note"]


def test_cost_decline_via_bus(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")   # fake (W2: env is hermetic)
    vault, pdf, cfg = setup_run(tmp_path)
    with pytest.raises(realrun.Cancelled):
        run_bus(cfg, tmp_path, ["n"])
    assert not cfg.dry_run_root.exists()
