"""Publication records + run receipts, kept in the app data dir (not the vault).

Records are rewritten atomically (temp + os.replace); receipts are append-only
(exclusive create, one file per run).
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .state_machine import State, check


@dataclass(frozen=True)
class PaperIdentity:
    library: str
    parent_key: str
    attachment_key: str
    pdf_sha256: str
    doi: str | None = None

    @property
    def key(self) -> str:
        # Identity = library + Parent Key + PDF SHA (DOI is auxiliary only).
        return f"{self.library}__{self.parent_key}__{self.pdf_sha256[:16]}"


@dataclass
class PublicationRecord:
    identity: dict
    state: str = State.NEW.value
    note_path: str | None = None
    note_machine_sha: str | None = None
    note_sha_at_write: str | None = None
    assets: list = field(default_factory=list)
    history: list = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        (self.dir / "records").mkdir(parents=True, exist_ok=True)
        (self.dir / "receipts").mkdir(parents=True, exist_ok=True)

    def _rec_path(self, ident: PaperIdentity) -> Path:
        return self.dir / "records" / f"{ident.key}.json"

    def load(self, ident: PaperIdentity) -> PublicationRecord | None:
        p = self._rec_path(ident)
        if not p.exists():
            return None
        return PublicationRecord(**json.loads(p.read_text("utf-8")))

    def save(self, rec: PublicationRecord, ident: PaperIdentity) -> None:
        p = self._rec_path(ident)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".rec-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(rec), f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)

    def transition(self, rec: PublicationRecord, ident: PaperIdentity, nxt: State, note: str = "") -> None:
        check(State(rec.state), nxt)
        rec.history.append({"from": rec.state, "to": nxt.value, "at": _now(), "note": note})
        rec.state = nxt.value
        self.save(rec, ident)

    def all_records(self) -> list[PublicationRecord]:
        return [PublicationRecord(**json.loads(p.read_text("utf-8")))
                for p in sorted((self.dir / "records").glob("*.json"))]

    def write_receipt(self, payload: dict) -> Path:
        run_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        payload = {"run_id": run_id, "finished_at": _now(), "test_layer": payload.pop("test_layer", "unknown"), **payload}
        p = self.dir / "receipts" / f"{run_id}.json"
        with open(p, "x", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return p
