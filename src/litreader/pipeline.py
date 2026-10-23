"""Stage 1 orchestrator: wires sandbox, writer, state machine, index, receipts.

The research core (parse + LLM analysis) and the renderer are *injected*;
Stage 1 tests use deterministic fakes. No network, no Zotero access here.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .errors import AlreadyExists, HashMismatch, LitError, Stop
from .hashing import sha256_file
from .permissions import Sandbox
from .publish import index as idx
from .publish.state_machine import State
from .publish.store import PaperIdentity, PublicationRecord, Store
from .render.protected_zone import carry_over, machine_sha
from .vault import naming
from .vault.writer import VaultWriter

CoreFn = Callable[[PaperIdentity], dict]
RenderFn = Callable[[PaperIdentity, dict], str]
AssetsFn = Callable[[PaperIdentity, dict], list[tuple[str, bytes]]]

INDEX_REL = "00-精读论文总览.md"


@dataclass
class Counters:
    core_calls: int = 0
    index_attempts: int = 0
    vault_writes: int = 0


@dataclass
class RunResult:
    status: str  # COMPLETE | EXISTS | INDEX_PENDING | RECOVERED | STOP
    state: str | None
    note_path: str | None = None
    note_sha: str | None = None
    reason: str = ""
    counters: Counters = field(default_factory=Counters)
    receipt: str | None = None


class Pipeline:
    def __init__(self, vault_root: Path, data_dir: Path, core: CoreFn, render: RenderFn,
                 assets: AssetsFn | None = None, topic: str = "未分类",
                 index_writer_hook: Callable[[], None] | None = None,
                 test_layer: str = "mock"):
        self.sb = Sandbox(vault_root)
        self.writer = VaultWriter(self.sb, replace_allowlist={INDEX_REL})
        self.store = Store(data_dir)
        self.core, self.render, self.assets = core, render, assets or (lambda i, a: [])
        self.topic = topic
        self.index_writer_hook = index_writer_hook  # fault-injection point for tests
        self.test_layer = test_layer
        self.counters = Counters()

    # ---------- public API ----------
    def run(self, ident: PaperIdentity, title_display: str = "UNKNOWN",
            first_author: str | None = None, year: str | None = None) -> RunResult:
        self.counters = Counters()
        w0 = self.writer.write_count
        try:
            res = self._run(ident, title_display, first_author, year)
        except LitError as e:
            rec = self.store.load(ident)
            res = RunResult("STOP", rec.state if rec else None, reason=f"{type(e).__name__}: {e}")
        self.counters.vault_writes = self.writer.write_count - w0
        res.counters = self.counters
        res.receipt = str(self.store.write_receipt({
            "test_layer": self.test_layer, "identity": asdict(ident), "status": res.status,
            "state": res.state, "reason": res.reason, "note_path": res.note_path,
            "note_sha": res.note_sha, "counters": asdict(self.counters)}))
        return res

    def retry_index(self, ident: PaperIdentity) -> RunResult:
        return self.run(ident)  # run() routes INDEX_PENDING to index-only recovery

    def regenerate(self, ident: PaperIdentity, new_render: RenderFn) -> RunResult:
        """T18: new reading version from stored analysis; old note and annotations untouched."""
        self.counters = Counters()
        w0 = self.writer.write_count
        rec = self.store.load(ident)
        if not rec or rec.state != State.COMPLETE.value:
            return RunResult("STOP", rec.state if rec else None, reason="regenerate requires COMPLETE")
        analysis = json.loads(self._analysis_path(ident).read_text("utf-8"))
        old_text = self.sb.resolve(rec.note_path).read_text("utf-8")
        new_text = carry_over(old_text, new_render(ident, analysis))
        ts = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        rel = f"_阅读版本/{ident.parent_key}/{ts}.md"
        wr = self.writer.create_exclusive(rel, new_text.encode("utf-8"))
        self.counters.vault_writes = self.writer.write_count - w0
        return RunResult("COMPLETE", rec.state, rel, wr.sha256, "new reading version", self.counters)

    # ---------- internals ----------
    def _analysis_path(self, ident: PaperIdentity) -> Path:
        p = self.store.dir / "jobs" / ident.fs_key
        p.mkdir(parents=True, exist_ok=True)
        return p / "analysis.json"

    def _run(self, ident: PaperIdentity, title_display: str, first_author=None, year=None) -> RunResult:
        rec = self.store.load(ident)
        if rec is not None:
            if rec.state == State.COMPLETE.value:
                return self._exists(rec)
            if rec.state == State.INDEX_PENDING.value:
                return self._index_only(rec, ident, recovered=True)
            raise Stop(f"previous run halted at {rec.state}; manual review required (no auto-resume in Stage 1)")

        # Filename is display only (Chinese title, collision suffixes); identity comes from the record.
        # A foreign file at a candidate path is never touched: the next candidate is used, or Stop.
        stem = naming.choose(title_display, first_author, year, ident.parent_key,
                             taken=lambda c: self.sb.resolve(f"{self.topic}/{c}.md").exists())
        note_rel = f"{self.topic}/{stem}.md"

        rec = PublicationRecord(identity={**asdict(ident), "title_display": title_display})
        self.counters.core_calls += 1
        analysis = self.core(ident)
        self._analysis_path(ident).write_text(json.dumps(analysis, ensure_ascii=False), "utf-8")
        self.store.transition(rec, ident, State.CORE_PASS)

        text = self.render(ident, analysis)
        wr = self.writer.create_exclusive(note_rel, text.encode("utf-8"))
        rec.note_path, rec.note_sha_at_write, rec.note_machine_sha = note_rel, wr.sha256, machine_sha(text)
        self.store.transition(rec, ident, State.NOTE_CREATED)

        for name, data in self.assets(ident, analysis):
            if "/" in name or "\\" in name:
                raise Stop(f"asset name must be a bare filename: {name!r}")
            a = self.writer.create_exclusive(f"_图表/{ident.parent_key}/{name}", data)
            rec.assets.append({"path": a.rel_path, "sha256": a.sha256})
        for a in rec.assets:  # re-verify all assets on disk
            if sha256_file(self.sb.resolve(a["path"])) != a["sha256"]:
                raise HashMismatch(f"asset verify failed: {a['path']}")
        self.store.transition(rec, ident, State.ASSETS_VERIFIED, note=f"{len(rec.assets)} assets")
        return self._index_only(rec, ident, recovered=False)

    def _index_only(self, rec: PublicationRecord, ident: PaperIdentity, recovered: bool) -> RunResult:
        self.counters.index_attempts += 1
        try:
            if self.index_writer_hook:
                self.index_writer_hook()
            self._update_index()
        except (LitError, OSError) as e:
            self.store.transition(rec, ident, State.INDEX_PENDING, note=str(e))
            return RunResult("INDEX_PENDING", rec.state, rec.note_path, rec.note_sha_at_write,
                             f"{type(e).__name__}: {e}")
        self.store.transition(rec, ident, State.INDEX_UPDATED)
        self.store.transition(rec, ident, State.COMPLETE)
        return RunResult("RECOVERED" if recovered else "COMPLETE", rec.state, rec.note_path, rec.note_sha_at_write)

    def _exists(self, rec: PublicationRecord) -> RunResult:
        p = self.sb.resolve(rec.note_path)
        if not p.is_file() or machine_sha(p.read_text("utf-8")) != rec.note_machine_sha:
            raise Stop("note machine content drifted from record; not returning EXISTS")
        return RunResult("EXISTS", rec.state, rec.note_path, rec.note_sha_at_write)

    def _update_index(self) -> None:
        entries = idx.verified_entries(self.store.all_records(), self.sb)
        fresh = idx.render_index(entries)
        path = self.sb.resolve(INDEX_REL)
        if not path.exists():
            self.writer.create_exclusive(INDEX_REL, fresh.encode("utf-8"))
            return
        old_sha = sha256_file(path)
        merged = idx.merge_into_existing(path.read_text("utf-8"), fresh)
        if merged.encode("utf-8") == path.read_bytes():
            return  # no change => no write
        self.writer.replace_atomic(INDEX_REL, merged.encode("utf-8"), old_sha)
