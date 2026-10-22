"""Application config (config.local.toml): vault, Zotero, app data, MinerU, plus LLM providers/stations.
Personal values (vault path, keys) live only in the user's config.local.toml / keyring, never in code."""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import LitError, Stop
from .llm import models as model_settings
from .llm.config import LLMConfig, parse_config


@dataclass(frozen=True)
class AppConfig:
    path: Path
    vault_root: Path
    papers_dir: str
    dry_run_dir: str
    zotero_api: str
    zotero_data_dir: Path
    data_dir: Path
    mineru_token_name: str
    mineru_model: str
    mineru_timeout_s: int
    link_mechanism_verified: bool
    llm: LLMConfig | None
    models_path: Path
    models: "model_settings.ModelSettings | None"
    legacy_models: bool = False
    llm_error: str | None = None
    templates_dir: str | None = "模板库"     # relative to the vault root; READ-ONLY (spec §10 / §15.2-1)
    template_selection: str = "confirm"      # confirm = auto pick + Enter to confirm; ask = always pick by number
    translate_titles: bool = True            # [candidates] machine-translate English titles in the pick list
    translate_role: str = "judge"            # [candidates] translate_with = 交叉核对(judge) | 主笔(writer)

    def price(self, provider_id: str) -> tuple[float | None, float | None]:
        s = self.models.find(provider_id) if self.models else None
        return (s.price_in, s.price_out) if s else (None, None)

    def slot_label(self, provider_id: str) -> str:
        s = self.models.find(provider_id) if self.models else None
        return f"{s.vendor} {s.model}" if s else provider_id

    @property
    def dry_run_root(self) -> Path:
        return self.vault_root / self.dry_run_dir


def default_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "litreader"
    if os.name == "nt":  # pragma: no cover
        return Path(os.environ.get("APPDATA", Path.home())) / "litreader"
    return Path.home() / ".local" / "share" / "litreader"


DEFAULT_OUTPUT_DIR = "litreader"


def normalize_output_dir(raw) -> str:
    """Relative folder inside the vault (one or more levels). Absolute paths, '..', '.' and empty are refused."""
    s = str(raw or "").strip().replace("\\", "/").strip("/")
    parts = [x.strip() for x in s.split("/")]
    if not s or Path(str(raw).strip()).is_absolute() or any(x in ("", ".", "..") for x in parts):
        raise Stop("[vault] output_dir 必须是库根目录下的相对文件夹（如 litreader），不能是绝对路径或含 ..")
    return "/".join(parts)


def find_config(explicit: str | None) -> Path:
    cands = [explicit, os.environ.get("LITREADER_CONFIG"), "config.local.toml",
             str(Path.home() / "litreader" / "config.local.toml")]
    for c in cands:
        if c and Path(c).expanduser().is_file():
            return Path(c).expanduser().resolve()
    raise Stop("找不到配置文件 config.local.toml（可用 --config 指定）")


def load(explicit: str | None = None) -> AppConfig:
    p = find_config(explicit)
    with open(p, "rb") as f:
        d = tomllib.load(f)
    v, z, a, m, r = (d.get(k) or {} for k in ("vault", "zotero", "app", "mineru", "run"))
    tp = d.get("templates") or {}
    tdir = str(tp.get("dir", "模板库") or "").strip().strip("/") or None
    if tdir and (Path(tdir).is_absolute() or ".." in Path(tdir).parts):
        raise Stop("[templates] dir 必须是库根目录下的相对路径（不能是绝对路径或含 ..）")
    tsel = str(tp.get("selection") or "confirm")
    if tsel not in ("confirm", "ask"):
        raise Stop("[templates] selection 只能是 confirm 或 ask")
    cd = d.get("candidates") or {}
    trole = {"judge": "judge", "交叉核对": "judge", "writer": "writer", "主笔": "writer"}.get(str(cd.get("translate_with") or "judge"))
    if trole is None:
        raise Stop("[candidates] translate_with 只能是 交叉核对 或 主笔")
    root = str(v.get("root") or "").strip()
    if not root:
        raise Stop("config [vault] root 未填写（Obsidian 库路径）")
    # G10-1: output_dir (default litreader) is where notes/figures/evidence go; a config that still has the old
    # dry_run_dir (e.g. "_litreader_试运行") and no output_dir keeps writing there — nothing is moved.
    dry = normalize_output_dir(v.get("output_dir") or v.get("dry_run_dir") or DEFAULT_OUTPUT_DIR)
    mp = Path(str((d.get("models") or {}).get("file") or "models.toml")).expanduser()
    mp = mp if mp.is_absolute() else p.parent / mp
    ms, llm, legacy, err = None, None, False, None
    try:
        if mp.is_file():
            ms = model_settings.load(mp)
            llm = ms.to_llm_config()
        elif d.get("providers"):
            legacy, ms = True, model_settings.migrate_legacy(d)
            llm = parse_config(d)
        else:
            err = "尚未设置模型：运行 litreader models set 主笔"
    except LitError as e:
        err = str(e)
    return AppConfig(
        path=p, vault_root=Path(root).expanduser(), papers_dir=str(v.get("papers_dir") or "论文库"), dry_run_dir=dry,
        zotero_api=str(z.get("api_base") or "http://localhost:23119/api"),
        zotero_data_dir=Path(str(z.get("data_dir") or "~/Zotero")).expanduser(),
        data_dir=Path(str(a.get("data_dir"))).expanduser() if a.get("data_dir") else default_data_dir(),
        mineru_token_name=str(m.get("token_name") or "MINERU_API_TOKEN"), mineru_model=str(m.get("model_version") or "vlm"),
        mineru_timeout_s=int(m.get("timeout_s") or 900), link_mechanism_verified=bool(r.get("link_mechanism_verified", False)),
        llm=llm, models_path=mp, models=ms, legacy_models=legacy, llm_error=err,
        templates_dir=tdir, template_selection=tsel,
        translate_titles=bool(cd.get("translate_titles", True)), translate_role=trole)
