"""Shared store core (TEMPLATE_LIBRARY §6.4, PROJECT_LIBRARY §2.1): content-addressed immutable objects, numbered
immutable snapshots, CURRENT pointer (atomic os.replace), append-only journal, single-writer lock, audited recovery
(never deletes, never relaxes SHA checks). Subclasses define LABEL / CMD / EXT and _empty().

A snapshot is {"n", "created", "records": [{..., "sha256"}], "prefs": {...}}; every record with "object" != False
must have objects/<sha256><EXT> whose bytes hash to sha256.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ..errors import Stop

STALE_S = 600


class Locked(Stop):
    pass


class Corrupt(Stop):
    pass


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Store:
    LABEL = "登记"
    CMD = "litreader recover"
    EXT = ".bin"

    def __init__(self, root: Path, *, now=None, pid: int | None = None, host: str | None = None,
                 stale_s: int = STALE_S, pid_alive=None):
        self.root = Path(root)
        self._now = now or time.time
        self.pid = pid or os.getpid()
        self.host = host or socket.gethostname()
        self.stale_s = stale_s
        self._alive = pid_alive or _pid_alive
        self.objects = self.root / "objects"
        self.snaps = self.root / "snapshots"
        self.current_file = self.root / "CURRENT"
        self.journal = self.root / "journal.log"
        self.lockfile = self.root / ".lock"
        self.quarantine = self.root / "quarantine"

    def _empty(self) -> dict:
        return {"n": 0, "created": None, "records": [], "prefs": {}}

    # ------------------------------------------------------------------ read side
    def ts(self) -> str:
        return datetime.fromtimestamp(self._now()).astimezone().isoformat(timespec="seconds")

    def current_n(self) -> int:
        if not self.current_file.exists():
            if self.snaps.is_dir() and any(self.snaps.glob("*.json")):
                raise Corrupt(f"{self.LABEL}缺少 CURRENT 指针但已有快照 → 运行 {self.CMD}")
            return 0
        t = self.current_file.read_text("utf-8").strip()
        if not t.isdigit():
            raise Corrupt(f"{self.LABEL} CURRENT 内容损坏 → 运行 {self.CMD}")
        return int(t)

    def read_snapshot(self, n: int) -> dict:
        if n == 0:
            return self._empty()
        p = self.snaps / f"{n}.json"
        try:
            return json.loads(p.read_text("utf-8"))
        except (OSError, ValueError) as e:
            raise Corrupt(f"{self.LABEL}快照 {n} 无法读取（{e.__class__.__name__}）→ 运行 {self.CMD}")

    def obj_path(self, digest: str) -> Path:
        return self.objects / f"{digest}{self.EXT}"

    def verify(self, snap: dict) -> list[str]:
        bad = []
        for r in snap["records"]:
            if not r.get("object", True):
                continue
            p = self.obj_path(r["sha256"])
            if not p.is_file():
                bad.append(f"缺少对象 {r['sha256'][:12]}（{r.get('id')}@{r.get('registry_version', r.get('version'))}）")
            elif sha(p.read_bytes()) != r["sha256"]:
                bad.append(f"对象内容与 SHA 不符 {r['sha256'][:12]}（{r.get('id')}）")
        return bad

    def snapshot(self, verify: bool = True) -> dict:
        snap = self.read_snapshot(self.current_n())
        if verify:
            bad = self.verify(snap)
            if bad:
                raise Corrupt(f"{self.LABEL}校验失败：" + "；".join(bad[:3]) + f" → 运行 {self.CMD}")
        return snap

    def object_bytes(self, digest: str, what: str) -> bytes:
        p = self.obj_path(digest)
        b = p.read_bytes() if p.is_file() else None
        if b is None or sha(b) != digest:
            raise Corrupt(f"{what} 的快照对象缺失或被改动，停止")
        return b

    # ------------------------------------------------------------------ lock
    @contextmanager
    def lock(self, op: str, *, auto_recover: bool = True):
        self.root.mkdir(parents=True, exist_ok=True)
        for attempt in (1, 2):
            try:
                fd = os.open(self.lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                break
            except FileExistsError:
                state, info = self.lock_state()
                if state == "stale" and auto_recover and attempt == 1:
                    rep = self.recover(apply=False)
                    if not rep["ok"]:
                        raise Locked(f"{self.LABEL}上次中断且无法自动确认旧状态完整 → 运行 {self.CMD} 查看")
                    self.recover(apply=True, _auto=True)
                    continue
                raise Locked(self._lock_msg(state, info))
        with os.fdopen(fd, "w") as f:
            json.dump({"pid": self.pid, "host": self.host, "started": self._now(), "op": op}, f)
        try:
            yield
        finally:
            try:
                self.lockfile.unlink()
            except FileNotFoundError:
                pass

    def lock_state(self) -> tuple[str, dict]:
        if not self.lockfile.exists():
            return "free", {}
        try:
            info = json.loads(self.lockfile.read_text("utf-8") or "{}")
        except ValueError:
            info = {}
        age = self._now() - float(info.get("started") or 0)
        info["age_s"] = int(age)
        if info.get("host") != self.host:
            return "foreign", info
        if info.get("pid") and self._alive(int(info["pid"])):
            return "live", info
        return ("stale" if age > self.stale_s else "young"), info

    def _lock_msg(self, state, info) -> str:
        who = f"进程 {info.get('pid')}@{info.get('host')}，操作 {info.get('op')}，已持续 {info.get('age_s', '?')} 秒"
        L, C = self.LABEL, self.CMD
        return {"live": f"{L}正被另一个 litreader 使用（{who}），请等它结束后再试",
                "foreign": f"{L}锁来自另一台电脑（{who}），不能自动判断，请运行 {C} 查看",
                "young": f"{L}锁的进程已不存在但时间很近（{who}），请稍后再试或运行 {C}",
                "stale": f"{L}上次中断（{who}）"}.get(state, f"{L}被锁")

    # ------------------------------------------------------------------ commit
    def _put_object(self, b: bytes) -> None:
        self.objects.mkdir(parents=True, exist_ok=True)
        p = self.obj_path(sha(b))
        if p.exists():
            if sha(p.read_bytes()) != sha(b):
                raise Corrupt(f"已有对象 {p.name} 内容被改动，停止")
            return
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
        with os.fdopen(fd, "wb") as f:
            f.write(b)
            f.flush()
            os.fsync(f.fileno())
        if sha(p.read_bytes()) != sha(b):
            raise Corrupt(f"写入对象 {p.name} 后校验失败")

    def _commit(self, snap: dict, events: list[dict], blobs: list[bytes] = ()) -> dict:
        """Caller holds the lock. Objects -> snapshot tmp -> fsync -> rename -> CURRENT replace -> journal."""
        for b in blobs:
            self._put_object(b)
        n = self.current_n() + 1
        snap = {**snap, "n": n, "created": self.ts()}
        self.snaps.mkdir(parents=True, exist_ok=True)
        tmp = self.snaps / f"{n}.json.tmp"
        with open(tmp, "x", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        final = self.snaps / f"{n}.json"
        if final.exists():
            raise Corrupt(f"快照 {n} 已存在（并发写入？），停止")
        os.rename(tmp, final)
        ctmp = self.root / "CURRENT.tmp"
        ctmp.write_text(str(n), "utf-8")
        os.replace(ctmp, self.current_file)
        self._log(events, n)
        return snap

    def _log(self, events: list[dict], n: int | None) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.journal, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps({"t": self.ts(), "snapshot": n, "pid": self.pid, **e}, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ recovery
    def recover(self, apply: bool = False, to: int | None = None, _auto: bool = False) -> dict:
        """Audited recovery. Never deletes; never relaxes SHA checks. Report: {ok, lock, current, problems[],
        residue[], actions[]}"""
        rep: dict = {"ok": True, "problems": [], "residue": [], "actions": []}
        state, info = self.lock_state()
        rep["lock"] = {"state": state, **info}
        if state in ("live", "foreign", "young"):
            rep["ok"] = False
            rep["problems"].append(self._lock_msg(state, info))
            return rep
        try:
            n = self.current_n()
            snap = self.read_snapshot(n)
            bad = self.verify(snap)
        except Corrupt as e:
            n, snap, bad = None, None, [str(e)]
        rep["current"] = n
        if bad:
            rep["problems"] += bad
            good = [k for k in self._snapshot_numbers() if k != n and not self._verify_n(k)]
            rep["verified_snapshots"] = good
            if to is None or to not in good:
                rep["ok"] = False
                rep["hint"] = (f"可回退到已校验完整的快照：{good[-1]}（{self.CMD} --to {good[-1]}）"
                               if good else "没有校验完整的快照；请保留现场并联系维护者")
                return rep
            n = to
            rep["actions"].append(f"CURRENT 指向快照 {to}（已校验完整）")
        referenced = set()
        for k in self._snapshot_numbers():
            if k <= (n or 0):
                try:
                    referenced |= {r["sha256"] for r in self.read_snapshot(k)["records"]}
                except Corrupt:
                    pass
        for p in sorted(self.snaps.glob("*")) if self.snaps.is_dir() else []:
            stem = p.name.split(".")[0]
            if p.name.endswith(".tmp") or (stem.isdigit() and int(stem) > (n or 0)):
                rep["residue"].append(str(p.relative_to(self.root)))
        if (self.root / "CURRENT.tmp").exists():
            rep["residue"].append("CURRENT.tmp")
        for p in sorted(self.objects.glob(f"*{self.EXT}")) if self.objects.is_dir() else []:
            if p.name[: -len(self.EXT)] not in referenced:
                rep["residue"].append(str(p.relative_to(self.root)))
        if state == "stale":
            rep["residue"].append(".lock")
        if not apply:
            return rep
        qdir = self.quarantine / datetime.fromtimestamp(self._now()).strftime("%Y%m%dT%H%M%S")
        for rel in rep["residue"]:
            src = self.root / rel
            dst = qdir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
            rep["actions"].append(f"移入隔离区 {rel}")
        if to is not None and bad:
            ctmp = self.root / "CURRENT.tmp"
            ctmp.write_text(str(to), "utf-8")
            os.replace(ctmp, self.current_file)
        self._log([{"op": "RECOVERED", "auto": _auto, "current": n, "lock": state, "moved": rep["residue"],
                    "actions": rep["actions"]}], n)
        return rep

    def _snapshot_numbers(self) -> list[int]:
        if not self.snaps.is_dir():
            return []
        return sorted(int(p.stem) for p in self.snaps.glob("*.json") if p.stem.isdigit())

    def _verify_n(self, k: int) -> list[str]:
        try:
            return self.verify(self.read_snapshot(k))
        except Corrupt as e:
            return [str(e)]


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
