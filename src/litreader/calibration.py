"""Per-model token calibration (decision 3, 2026-10-18).

Token estimates start model-agnostic (paper length, figure count: estimate.RATIO). After every completed run the actual
usage of each role is recorded against the DEFAULT estimate for (vendor, model, role) in a local JSON store under the
app support dir (never inside the Obsidian vault; contains no paper text, only token counts and the Zotero item key).
Once a model has ≥ MIN_RUNS records, its own median actual/default ratios scale the default estimate and the range
comes from its measured scatter; until then the default ratios are used with a wider range, because tokenizers differ
between vendors and the defaults were measured on DeepSeek/MiniMax only.
Prices are never involved here: cost = tokens × the user's own price_in/price_out (元/百万 tokens) per slot.
"""
from __future__ import annotations

import json
import os
import statistics
from datetime import datetime
from pathlib import Path

MIN_RUNS = 3
KEEP = 20                 # newest records kept per model/role
SPREAD_DEFAULT = 0.6      # uncalibrated: wider than the 0.4 seen on the calibration models
SPREAD_MIN, SPREAD_MAX = 0.15, 0.6
FILE = "calibration.json"
ROLES = ("writer", "vision", "judge")


def key(vendor: str, model: str, role: str) -> str:
    return f"{(vendor or '?').strip()}|{(model or '?').strip()}|{role}"


class Store:
    def __init__(self, data_dir: Path, vault_root: Path | None = None):
        self.path = Path(data_dir) / FILE
        if vault_root is not None:
            vr = Path(vault_root).expanduser().resolve()
            p = self.path.expanduser().resolve()
            if p == vr or vr in p.parents:
                raise ValueError(f"校准记录不能放在 Obsidian 库里：{self.path}")

    def load(self) -> dict:
        try:
            d = json.loads(self.path.read_text("utf-8"))
            return d if isinstance(d, dict) and isinstance(d.get("models"), dict) else {"version": 1, "models": {}}
        except (OSError, ValueError):
            return {"version": 1, "models": {}}

    def records(self, k: str) -> list[dict]:
        return list(self.load()["models"].get(k) or [])

    def add(self, k: str, rec: dict) -> int:
        d = self.load()
        lst = (d["models"].get(k) or []) + [rec]
        d["models"][k] = lst[-KEEP:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self.path)          # atomic: a crash never leaves half a file
        return len(d["models"][k])


def _ratios(recs: list[dict], side: str) -> list[float]:
    return [r[f"act_{side}"] / r[f"est_{side}"] for r in recs if r.get(f"est_{side}") and r.get(f"act_{side}") is not None]


def status(recs: list[dict]) -> dict:
    """{'n', 'calibrated', 'in_ratio', 'out_ratio', 'spread', 'label'} for one model/role."""
    n = len(recs)
    if n < MIN_RUNS:
        need = MIN_RUNS - n
        return {"n": n, "calibrated": False, "in_ratio": 1.0, "out_ratio": 1.0, "spread": SPREAD_DEFAULT,
                "label": "按默认比例估算，误差较大" + (f"（本模型已实测 {n} 篇，还需 {need} 篇才启用本模型校准）" if n else
                                               "（本模型尚无实测；不同厂商分词器（tokenizer）不同，token 数会有差异）")}
    ri, ro = _ratios(recs, "in"), _ratios(recs, "out")
    mi, mo = statistics.median(ri or [1.0]), statistics.median(ro or [1.0])
    dev = max([abs(x / mi - 1) for x in ri] + [abs(x / mo - 1) for x in ro] + [0.0])
    spread = min(SPREAD_MAX, max(SPREAD_MIN, round(dev, 2)))
    return {"n": n, "calibrated": True, "in_ratio": round(mi, 4), "out_ratio": round(mo, 4), "spread": spread,
            "label": f"按本机 {n} 篇实测校准"}


def slot_line(recs: list[dict]) -> str:
    """One status line for `models list` / the GUI model slot."""
    n = len(recs)
    if n >= MIN_RUNS:
        return f"已实测 {n} 篇，已启用本模型校准"
    return f"已实测 {n} 篇，还需 {MIN_RUNS - n} 篇才启用本模型校准"


def apply(est: dict, models: dict[str, tuple[str, str]], store: Store | None) -> dict:
    """Scale each role's DEFAULT estimate by its primary model's calibration. `models`: role -> (vendor, model).
    The default numbers are kept as base_in/base_out: records are always made against them (no compounding)."""
    for role, t in est.get("roles", {}).items():
        vm = models.get(role)
        recs = store.records(key(*vm, role)) if (store and vm) else []
        st = status(recs)
        t["base_in"], t["base_out"] = t["in"], t["out"]
        t["in"], t["out"] = int(round(t["in"] * st["in_ratio"])), int(round(t["out"] * st["out_ratio"]))
        t["calibration"] = {"key": key(*vm, role) if vm else None, **st}
    return est


def record(store: Store, est: dict, used: dict[str, dict], *, item_key: str | None, chars=None, figures=None) -> dict:
    """After a completed run. `used`: role -> {'providers': set/list of (vendor, model), 'in', 'out'}.
    A role whose calls went to more than one model (backup took over mid-way) is not recorded: the split is unknown."""
    out = {}
    for role, a in used.items():
        t = (est.get("roles") or {}).get(role)
        provs = sorted(set(map(tuple, a.get("providers") or [])))
        if not t:
            out[role] = {"recorded": False, "reason": "无估算"}
            continue
        if len(provs) != 1:
            out[role] = {"recorded": False, "reason": "该角色用了多个模型（备用接替），无法分摊，不记录" if provs else "无调用"}
            continue
        k = key(*provs[0], role)
        rec = {"date": datetime.now().isoformat(timespec="seconds"), "item": item_key, "chars": chars, "figures": figures,
               "est_in": t.get("base_in", t["in"]), "est_out": t.get("base_out", t["out"]), "act_in": a["in"],
               "act_out": a["out"]}
        n = store.add(k, rec)
        out[role] = {"recorded": True, "key": k, "n": n, "calibrated_next": n >= MIN_RUNS}
    return out
