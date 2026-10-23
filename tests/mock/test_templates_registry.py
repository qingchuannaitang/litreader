"""Stage 6: registry (objects/snapshots/CURRENT/journal/lock), state machine, versioning, pin/rollback/prefer,
approve, audited recovery, library read-only (T05), quarantine of test templates."""
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from litreader.errors import Stop
from litreader.templates import builtin
from litreader.templates.registry import Corrupt, Locked, Registry

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "templates"


def tree_hash(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(d.rglob("*")) if p.is_file()}


@pytest.fixture
def env(tmp_path):
    lib = tmp_path / "vault" / "模板库"
    lib.mkdir(parents=True)
    clock = [1_800_000_000.0]
    reg = Registry(tmp_path / "appdata" / "templates", lib, now=lambda: clock[0], pid=4242, host="h",
                   pid_alive=lambda pid: pid == 4242)
    return reg, lib, clock


def recs(snap, tid):
    return sorted([r for r in snap["records"] if r["id"] == tid], key=lambda r: r["registry_version"])


def test_first_refresh_registers_builtins_only(env):
    reg, lib, _ = env
    snap, ev, _ = reg.refresh()
    assert snap["n"] == 1 and {r["id"] for r in snap["records"]} == set(builtin.all_ids())
    assert all(r["status"] == "ACTIVE" for r in snap["records"])
    assert reg.current_file.read_text("utf-8") == "1" and (reg.snaps / "1.json").is_file()
    assert all((reg.objects / f"{r['sha256']}.md").is_file() for r in snap["records"])
    lines = [json.loads(l) for l in reg.journal.read_text("utf-8").splitlines()]
    assert lines[0]["op"] == "REFRESH" and all(l["snapshot"] == 1 for l in lines)
    # incremental: nothing changed -> no new snapshot
    snap2, ev2, _ = reg.refresh()
    assert snap2["n"] == 1 and ev2 == [] and not reg.lockfile.exists()


def test_T05_new_template_library_bytes_unchanged(env):
    reg, lib, _ = env
    reg.refresh()
    shutil.copy(FIX / "diag_main.md", lib / "诊断模板.md")
    (lib / "sub").mkdir()
    shutil.copy(FIX / "malicious_injection.md", lib / "sub" / "evil.md")
    before = tree_hash(lib)
    snap, ev, _ = reg.refresh()
    assert tree_hash(lib) == before                              # library is read-only (bytes + mtime)
    d = recs(snap, "user.diag_main")[0]
    assert d["status"] == "ACTIVE" and d["role"] == "MAIN_NOTE" and d["path"] == "诊断模板.md"
    assert d["applies_to"]["study_types"] == ["diagnostic_accuracy", "prediction_model"] and len(d["sha256"]) == 64
    assert "ORIGINAL_FIGURE" in d["features"] and d["size_bytes"] == (lib / "诊断模板.md").stat().st_size
    assert recs(snap, "user.evil")[0]["status"] == "NEEDS_REVIEW"     # T06: never auto-selectable
    assert {e["op"] for e in ev} >= {"REFRESH", "NEW"}


def test_T05b_rename_new_version_remove_restore_rollback(env):
    reg, lib, _ = env
    shutil.copy(FIX / "diag_main.md", lib / "a.md")
    reg.refresh()
    (lib / "a.md").rename(lib / "b.md")                            # rename: same version
    snap, ev, _ = reg.refresh()
    assert [e["op"] for e in ev if e["op"] != "REFRESH"] == ["MOVED"] and recs(snap, "user.diag_main")[0]["path"] == "b.md"
    (lib / "b.md").write_text((lib / "b.md").read_text("utf-8").replace("priority: 70", "priority: 71"), "utf-8")
    snap, ev, _ = reg.refresh()
    v1, v2 = recs(snap, "user.diag_main")
    assert (v1["status"], v2["status"], v2["registry_version"], v1["superseded_by"]) == ("SUPERSEDED", "ACTIVE", 2, 2)
    snap = reg.rollback("user.diag_main")
    assert snap["prefs"]["pins"]["user.diag_main"] == 1 and reg.effective(snap, "user.diag_main")["registry_version"] == 1
    with pytest.raises(Stop, match="没有更早"):
        reg.rollback("user.diag_main")
    reg.unpin("user.diag_main")
    (lib / "b.md").unlink()                                        # removed: object kept, history intact
    snap, _, _ = reg.refresh()
    assert recs(snap, "user.diag_main")[1]["status"] == "REMOVED"
    assert (reg.objects / f"{recs(snap, 'user.diag_main')[1]['sha256']}.md").is_file()
    reg.pin("user.diag_main", 1)                                   # explicit use of an old version still possible
    shutil.copy(FIX / "diag_main.md", lib / "c.md")                # v1 content reappears -> restored
    snap, ev, _ = reg.refresh()
    assert any(e["op"] == "RESTORED" for e in ev)
    assert [r["status"] for r in recs(snap, "user.diag_main")] == ["ACTIVE", "REMOVED"]


def test_conflict_same_id_two_files(env):
    reg, lib, _ = env
    shutil.copy(FIX / "diag_main.md", lib / "a.md")
    reg.refresh()
    (lib / "copy.md").write_text((lib / "a.md").read_text("utf-8").replace("priority: 70", "priority: 20"), "utf-8")
    snap, _, _ = reg.refresh()
    v1, v2 = recs(snap, "user.diag_main")
    assert v1["status"] == "ACTIVE" and v2["status"] == "CONFLICT"   # registered ACTIVE version keeps working
    (lib / "copy.md").unlink()
    snap, _, _ = reg.refresh()
    assert recs(snap, "user.diag_main")[0]["status"] == "ACTIVE"


def test_rejections_symlink_hardlink_depth_size_fixture(env, tmp_path):
    reg, lib, _ = env
    outside = tmp_path / "outside.md"
    shutil.copy(FIX / "diag_main.md", outside)
    os.symlink(outside, lib / "link.md")
    os.link(outside, lib / "hard.md")
    deep = lib / "a" / "b" / "c"
    deep.mkdir(parents=True)
    shutil.copy(FIX / "diag_main.md", deep / "too_deep.md")
    (lib / "big.md").write_bytes(b"#" * (64 * 1024 + 5))
    shutil.copy(FIX / "fixture_marked.md", lib / "fx.md")
    (lib / "_draft.md").write_text("x"); (lib / ".hidden.md").write_text("x")
    snap, _, notes = reg.refresh()
    by_path = {r["path"]: r for r in snap["records"]}
    assert by_path["link.md"]["status"] == "REJECTED" and by_path["hard.md"]["status"] == "REJECTED"
    assert by_path["big.md"]["status"] == "REJECTED" and by_path["fx.md"]["status"] == "REJECTED"
    assert not any("too_deep" in p for p in by_path) and any("过深" in n for n in notes)
    assert not any(p.startswith(("_", ".")) for p in by_path)
    assert by_path["link.md"].get("object") is False


def test_lock_live_foreign_stale_autorecover(env, tmp_path):
    reg, lib, clock = env
    reg.refresh()
    reg.lockfile.write_text(json.dumps({"pid": 4242, "host": "h", "started": clock[0], "op": "refresh"}))
    with pytest.raises(Locked, match="另一个 litreader"):
        reg.refresh()
    reg.lockfile.write_text(json.dumps({"pid": 1, "host": "other", "started": clock[0], "op": "refresh"}))
    with pytest.raises(Locked, match="另一台电脑"):
        reg.refresh()
    # crash simulation: object written + snapshot tmp, CURRENT not moved, dead pid, old lock
    reg.lockfile.write_text(json.dumps({"pid": 999, "host": "h", "started": clock[0] - 3600, "op": "refresh"}))
    (reg.objects / ("f" * 64 + ".md")).write_bytes(b"orphan")
    (reg.snaps / "2.json.tmp").write_text("{}")
    snap, ev, _ = reg.refresh()
    assert snap["n"] == 1 and not reg.lockfile.exists()
    q = list((reg.root / "quarantine").rglob("*"))
    assert any(p.name == "2.json.tmp" for p in q) and any(p.name == "f" * 64 + ".md" for p in q)
    log = [json.loads(l) for l in reg.journal.read_text("utf-8").splitlines()]
    assert any(l["op"] == "RECOVERED" and l["auto"] for l in log)


def test_recover_refuses_on_sha_mismatch_and_rolls_back_only_with_explicit_target(env):
    reg, lib, _ = env
    reg.refresh()
    shutil.copy(FIX / "diag_main.md", lib / "a.md")
    snap, _, _ = reg.refresh()
    obj = reg.objects / f"{recs(snap, 'user.diag_main')[0]['sha256']}.md"
    os.chmod(obj, 0o644); obj.write_bytes(b"tampered")
    with pytest.raises(Corrupt):
        reg.snapshot()
    rep = reg.recover(apply=False)
    assert not rep["ok"] and rep["verified_snapshots"] == [1] and "--to 1" in rep["hint"]
    rep = reg.recover(apply=True, to=1)
    assert rep["ok"] and reg.current_n() == 1 and reg.snapshot()["n"] == 1   # never "fixes" by skipping SHA checks


def test_approve_reject_disable_prefer(env):
    reg, lib, _ = env
    shutil.copy(FIX / "malicious_injection.md", lib / "evil.md")
    shutil.copy(FIX / "no_frontmatter.md", lib / "nofm.md")
    shutil.copy(FIX / "diag_main.md", lib / "diag.md")
    snap, _, _ = reg.refresh(tagger=lambda d: {"role": "main", "study_types": ["cohort", "astrology"], "confidence": 0.9,
                                               "reason": "x"})
    nofm = next(r for r in snap["records"] if r["path"] == "nofm.md")
    assert nofm["status"] == "NEEDS_REVIEW" and nofm["ai_suggested"]["study_types"] == ["cohort"]
    with pytest.raises(Stop, match="待审"):
        reg.pin("user.evil", 1)
    with pytest.raises(Stop, match="不是可用的主模板"):
        reg.prefer("user.evil")
    snap = reg.approve(nofm["id"], 1)
    r = reg.find(snap, nofm["id"], 1)
    assert r["status"] == "ACTIVE" and r["role"] == "MAIN_NOTE" and r["applies_to"]["study_types"] == ["cohort"]
    assert r["overrides"][-1]["action"] == "approve"
    snap = reg.set_status("user.evil", 1, "REJECTED", "reject")
    assert reg.find(snap, "user.evil", 1)["status"] == "REJECTED"
    with pytest.raises(Stop, match="回退模板"):
        reg.set_status("main.general", None, "DISABLED", "disable")
    snap = reg.prefer("main.spec_appendix_a")
    assert snap["prefs"]["default_main"] == "main.spec_appendix_a"
    snap = reg.prefer("user.diag_main", "diagnostic_accuracy")
    assert snap["prefs"]["prefer_for"] == {"diagnostic_accuracy": "user.diag_main"}
    with pytest.raises(Stop, match="不是可用的主模板"):
        reg.prefer("overview.v2")
    snap = reg.set_status("user.diag_main", None, "DISABLED", "disable")
    assert reg.effective(snap, "user.diag_main") is None
    # every mutation is a new immutable snapshot + journal entry
    assert snap["n"] == len(list(reg.snaps.glob("*.json")))


def test_ai_tagger_failure_stays_needs_review(env):
    reg, lib, _ = env
    shutil.copy(FIX / "no_frontmatter.md", lib / "nofm.md")
    def boom(d):
        raise RuntimeError("model down")
    snap, _, _ = reg.refresh(tagger=boom)
    r = next(r for r in snap["records"] if r["path"] == "nofm.md")
    assert r["status"] == "NEEDS_REVIEW" and r["ai_suggested"] is None
    with pytest.raises(Stop, match="角色"):
        reg.approve(r["id"], 1)


def test_draft_is_needs_review(env):
    from litreader.cli_templates import compose_draft
    reg, lib, _ = env
    reg.refresh()
    md = compose_draft("user.my_style", "我的风格", {"study_types": ["rct", "bogus"], "sections": [
        {"title": "一、背景 [[x]](http://e)", "data": "s1", "blocks": ["paragraphs", "rm_rf"]},
        {"title": "二、我的特色章节", "data": None, "blocks": ["paragraphs"]}]})
    assert "http" not in md and "rm_rf" not in md and "bogus" not in md
    snap = reg.add_draft(md.encode(), "AI 起草")
    r = recs(snap, "user.my_style")[0]
    assert r["status"] == "NEEDS_REVIEW" and r["source"] == "ai_draft"
    t = reg.load_template(r)
    assert [s.data for s in t.sections] == ["s1", None]
    snap = reg.approve("user.my_style", 1)
    assert recs(snap, "user.my_style")[0]["status"] == "ACTIVE"


def test_snapshot_bytes_frozen_against_library_edits(env):
    reg, lib, _ = env
    shutil.copy(FIX / "diag_main.md", lib / "a.md")
    snap, _, _ = reg.refresh()
    rec = recs(snap, "user.diag_main")[0]
    (lib / "a.md").write_text("changed during run", "utf-8")
    t = reg.load_template(rec)                                     # T07-a: still the registered bytes
    assert t.sha256 == rec["sha256"] and t.id == "user.diag_main"


def test_shipped_package_has_no_fixture_templates_outside_tests():
    root = Path(__file__).resolve().parents[2]
    import subprocess
    files = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split()
    for f in files:
        if f.endswith(".md") and f.startswith("src/"):
            b = (root / f).read_bytes()
            assert b"fixture: true" not in b and b"id: test." not in b and b"id: fixture." not in b, f
    assert not any("/registry/" in f or f.startswith("registry/") or "/objects/" in f for f in files)
