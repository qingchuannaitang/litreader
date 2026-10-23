"""Mock layer: pipeline with fake core/renderer. No network, tmp dirs only."""
import json
import os

from conftest import fake_core, fake_render, fake_render_v2
from litreader.hashing import sha256_file
from litreader.pipeline import INDEX_REL, Pipeline
from litreader.render.protected_zone import BEGIN, END, extract


def make(vault, data_dir, **kw):
    return Pipeline(vault, data_dir, fake_core, fake_render, topic="步态研究", **kw)


def snapshot(root):
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in root.rglob("*") if p.is_file()}


def test_full_run_complete(vault, data_dir, ident):
    r = make(vault, data_dir, assets=lambda i, a: [("Fig1_p5.png", b"\x89PNG fake")]).run(ident, "测试中文题名（Test）")
    assert r.status == "COMPLETE" and r.state == "COMPLETE"
    assert (vault / "步态研究/测试中文题名（Test）.md").is_file() and r.note_path == "步态研究/测试中文题名（Test）.md"
    assert not (vault / "步态研究/ABCD1234.md").exists()
    assert (vault / "_图表/ABCD1234/Fig1_p5.png").is_file()      # figure dirs keep the key
    assert "[[步态研究/测试中文题名（Test）|测试中文题名（Test）]]" in (vault / INDEX_REL).read_text("utf-8")  # path from record
    rc = json.loads(open(r.receipt, encoding="utf-8").read())
    assert rc["test_layer"] == "mock" and rc["counters"]["core_calls"] == 1


def test_T17_repeat_returns_exists_zero_writes(vault, data_dir, ident):
    p = make(vault, data_dir)
    first = p.run(ident)
    before = snapshot(vault)
    second = p.run(ident)
    assert second.status == "EXISTS"
    assert second.note_path == first.note_path and second.note_sha == first.note_sha
    assert second.counters.core_calls == 0 and second.counters.vault_writes == 0
    assert snapshot(vault) == before


def test_T17_exists_still_holds_after_user_annotates(vault, data_dir, ident):
    p = make(vault, data_dir); p.run(ident)
    note = vault / "步态研究/ABCD1234.md"
    t = note.read_text("utf-8")
    note.write_text(t.replace(f"{BEGIN}\n", f"{BEGIN}\n我的批注\n"), "utf-8")
    assert p.run(ident).status == "EXISTS"


def test_exists_refused_if_machine_content_drifted(vault, data_dir, ident):
    p = make(vault, data_dir); p.run(ident)
    note = vault / "步态研究/ABCD1234.md"
    note.write_text(note.read_text("utf-8").replace("三分钟", "被篡改"), "utf-8")
    r = p.run(ident)
    assert r.status == "STOP" and r.counters.core_calls == 0 and r.counters.vault_writes == 0


def test_T16_index_failure_then_index_only_recovery(vault, data_dir, ident):
    fail = {"on": True}

    def hook():
        if fail["on"]:
            raise OSError("simulated overview write failure")

    p = make(vault, data_dir, index_writer_hook=hook)
    r1 = p.run(ident)
    assert r1.status == "INDEX_PENDING" and r1.state == "INDEX_PENDING"
    assert (vault / "步态研究/ABCD1234.md").is_file() and not (vault / INDEX_REL).exists()
    notes_before = snapshot(vault)
    fail["on"] = False
    r2 = p.retry_index(ident)
    assert r2.status == "RECOVERED" and r2.state == "COMPLETE"
    assert r2.counters.core_calls == 0
    assert r2.counters.vault_writes == 1  # only the overview
    after = snapshot(vault)
    assert {k: v for k, v in after.items() if k != INDEX_REL} == notes_before
    assert len(list(vault.rglob("ABCD1234.md"))) == 1  # no duplicate note
    assert p.run(ident).status == "EXISTS"


def test_T16_pending_stays_pending_if_retry_fails(vault, data_dir, ident):
    def hook():
        raise OSError("still failing")
    p = make(vault, data_dir, index_writer_hook=hook)
    p.run(ident)
    r = p.retry_index(ident)
    assert r.status == "INDEX_PENDING" and r.counters.core_calls == 0 and r.counters.vault_writes == 0


def test_T18_regenerate_preserves_old_note_and_annotations(vault, data_dir, ident):
    p = make(vault, data_dir); p.run(ident)
    note = vault / "步态研究/ABCD1234.md"
    note.write_text(note.read_text("utf-8").replace(f"{BEGIN}\n", f"{BEGIN}\n导师说：重点看验证集\n"), "utf-8", newline="\n")
    old_bytes = note.read_bytes()
    r = p.regenerate(ident, fake_render_v2)
    assert r.status == "COMPLETE" and r.note_path.startswith("_阅读版本/ABCD1234/")
    assert note.read_bytes() == old_bytes
    new_text = (vault / r.note_path).read_text("utf-8")
    assert "新版模板" in new_text
    assert extract(new_text) == extract(old_bytes.decode("utf-8"))
    assert r.counters.core_calls == 0 and r.counters.vault_writes == 1


def test_foreign_note_at_target_not_overwritten(vault, data_dir, ident):
    (vault / "步态研究").mkdir()
    (vault / "步态研究/ABCD1234.md").write_text("用户自己的旧笔记", "utf-8")
    r = make(vault, data_dir).run(ident)
    # G8-3: a dated file name is used instead of stopping; the user's note is never overwritten
    assert r.status == "COMPLETE" and r.note_path != "步态研究/ABCD1234.md" and "（" in r.note_path
    assert (vault / "步态研究/ABCD1234.md").read_text("utf-8") == "用户自己的旧笔记"


def test_user_edit_outside_managed_region_of_index_preserved(vault, data_dir, ident):
    p = make(vault, data_dir); p.run(ident)
    idxf = vault / INDEX_REL
    idxf.write_text("我的总览前言\n" + idxf.read_text("utf-8") + "\n我的结尾\n", "utf-8")
    from litreader.publish.store import PaperIdentity
    other = PaperIdentity("user:0", "ZZZZ9999", "PDF00002", "e" * 64)
    assert p.run(other).status == "COMPLETE"
    t = idxf.read_text("utf-8")
    assert t.startswith("我的总览前言") and t.rstrip().endswith("我的结尾") and "ZZZZ9999" in t


def test_index_with_broken_markers_goes_pending_not_overwritten(vault, data_dir, ident):
    (vault / INDEX_REL).write_text("用户完全手写的总览，无受管区", "utf-8")
    r = make(vault, data_dir).run(ident)
    assert r.status == "INDEX_PENDING"
    assert (vault / INDEX_REL).read_text("utf-8") == "用户完全手写的总览，无受管区"


def test_concurrent_index_modification_detected(vault, data_dir, ident, monkeypatch):
    p = make(vault, data_dir); p.run(ident)
    import litreader.publish.index as idx
    real = idx.merge_into_existing

    def racing(existing, fresh):
        (vault / INDEX_REL).write_text(existing + "\n并发写入", "utf-8")  # someone edits mid-update
        return real(existing, fresh)
    monkeypatch.setattr(idx, "merge_into_existing", racing)
    from litreader.publish.store import PaperIdentity
    r = p.run(PaperIdentity("user:0", "YYYY0000", "PDF3", "d" * 64))
    assert r.status == "INDEX_PENDING"
    assert (vault / INDEX_REL).read_text("utf-8").endswith("并发写入")


def test_index_excludes_unverified_records(vault, data_dir, ident):
    p = make(vault, data_dir); p.run(ident)
    note = vault / "步态研究/ABCD1234.md"
    note.write_text("篡改", "utf-8")  # breaks markers + hash
    from litreader.publish.store import PaperIdentity
    p.run(PaperIdentity("user:0", "QQQQ1111", "PDF4", "c" * 64))
    t = (vault / INDEX_REL).read_text("utf-8")
    assert "QQQQ1111" in t and "ABCD1234" not in t


def test_asset_name_with_path_rejected(vault, data_dir, ident):
    r = make(vault, data_dir, assets=lambda i, a: [("../../evil.png", b"x")]).run(ident)
    assert r.status == "STOP" and r.state == "NOTE_CREATED"
    assert not any("evil" in str(p) for p in vault.parent.rglob("*"))


def test_halted_run_requires_manual_review(vault, data_dir, ident):
    make(vault, data_dir, assets=lambda i, a: [("a/b.png", b"x")]).run(ident)
    r = make(vault, data_dir).run(ident)
    assert r.status == "STOP" and "manual review" in r.reason and r.counters.core_calls == 0


def test_receipts_append_only_one_per_run(vault, data_dir, ident):
    p = make(vault, data_dir); p.run(ident); p.run(ident)
    assert len(os.listdir(data_dir / "receipts")) == 2


def _ident(ident, **kw):
    from dataclasses import replace
    return replace(ident, **kw)


def test_chinese_filename_collisions_and_identity(vault, data_dir, ident):
    p = make(vault, data_dir)
    t = "步态：一项研究/初稿?"
    a = p.run(ident, t, "Zhong", "2021")
    assert a.note_path == "步态研究/步态——一项研究／初稿？.md"
    b = p.run(_ident(ident, parent_key="BBBB2222", pdf_sha256="b" * 64), t, "Zhong", "2021")
    assert b.note_path == "步态研究/步态——一项研究／初稿？——Zhong2021.md"
    c = p.run(_ident(ident, parent_key="CCCC3333", pdf_sha256="c" * 64), t, "Zhong", "2021")
    assert c.note_path == "步态研究/步态——一项研究／初稿？——Zhong2021CCCC3333.md"
    assert not list(vault.rglob("*(1)*"))
    # identity, not filename: same paper with a different display title -> EXISTS at the recorded path
    again = p.run(ident, "完全不同的标题")
    assert again.status == "EXISTS" and again.note_path == a.note_path
    d = p.run(_ident(ident, parent_key="CCCC3333", pdf_sha256="d" * 64), t, "Zhong", "2021")
    from datetime import date     # G8-3: dated last-resort name instead of stopping; nothing overwritten
    assert d.note_path == f"步态研究/步态——一项研究／初稿？——Zhong2021CCCC3333（{date.today().isoformat()}）.md"
