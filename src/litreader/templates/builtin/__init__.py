"""Built-in templates shipped with the program (read-only). Their SHA-256 is pinned here; a mismatch means the
install was altered -> STOP (design §3-4). To add a built-in: drop the .md here, add it to FILES and SHA256."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ...errors import Stop

DIR = Path(__file__).parent
FILES = {
    "main.general": "main_general.md",
    "main.spec_appendix_a": "main_spec_appendix_a.md",
    "overview.v2": "overview_v2.md",
    "module.rct": "module_rct.md",
    "module.diagnostic": "module_diagnostic.md",
    "module.sysreview": "module_sysreview.md",
    "module.methods": "module_methods.md",
}
SHA256 = {
    "main.general": "28277010a0180d5b546aee803b04f498e2fe6c0a4aa2f04fa11508e0ba25cbfb",
    "main.spec_appendix_a": "a7067ae26fa4233e141b95d11a2392721ac3180da3421646a5e00f114edb26f2",
    "overview.v2": "dc378483591cc97a757b00f66047efed4b4e9104273ccc61ceacb87776c06931",
    "module.rct": "a17ac4fbefceca9f14e8368416f9382a106a502dc0f477afc528b1a91bf1ab6d",
    "module.diagnostic": "55f319f211b719a8a3c3b8a6845c41459ef2962e0ff13f579a022edf8ff7e0d4",
    "module.sysreview": "67cff94aca644fdb7a17a30cbbe0aa95c04c5fa5046e12bd63a748d00516a7ab",
    "module.methods": "9830ebfe16c25d63dfd09490980ecb7694908a197c5de2694e8b2eb2ce4d4621",
}
# export names follow spec §2 where the spec names the file
EXPORT_NAMES = {"main.general": "单篇科研精读笔记_V2.0.md", "overview.v2": "00-精读论文总览_V2.0.md",
                "main.spec_appendix_a": "单篇科研精读笔记_规范附录A.md"}
FALLBACK = "main.general"


def raw(tid: str) -> bytes:
    import hashlib
    b = (DIR / FILES[tid]).read_bytes()
    if hashlib.sha256(b).hexdigest() != SHA256[tid]:
        # W2: a Windows checkout/unzip may turn LF into CRLF. Same text, different bytes: accept it only if the
        # LF-normalised bytes match the pinned hash exactly, and hand out those canonical bytes. Any real edit
        # still fails.
        n = b.replace(b"\r\n", b"\n")
        if n != b and hashlib.sha256(n).hexdigest() == SHA256[tid]:
            return n
        raise Stop(f"内置模板 {tid} 的内容与安装时不一致（SHA-256 不符），停止。请重新安装 litreader")
    return b


@lru_cache(maxsize=None)
def load(tid: str):
    from ..format import parse_template
    t = parse_template(raw(tid), f"builtin:{FILES[tid]}")
    if t.status_hint() != "ACTIVE":
        raise Stop(f"内置模板 {tid} 未通过检查：{t.errors + t.review}")
    return t


def all_ids() -> list[str]:
    return list(FILES)
