"""Fake Zotero / MinerU / LLM for GUI tests and offscreen screenshots. No network, no paid API: every transport is
a local function. Titles are invented sample data (示例)."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_realrun import FakeMinerU, STATS, llm_fake, setup_run  # noqa: E402

from litreader.zotero.client import ZoteroClient  # noqa: E402

ITEMS = [("AAAA1111", "Dual-task gait features in community-dwelling older adults (sample)", "2021",
          "titleTranslation: 社区老年人双任务步态特征（示例）"),
         ("BBBB2222", "Gait variability and executive function: a cross-sectional study (sample)", "2024",
          "titleTranslation: 步态变异性与执行功能：横断面研究（示例）")]


def zotero(storage: Path, n: int = 2):
    items = [{"key": k, "data": {"key": k, "itemType": "journalArticle", "title": t, "date": y, "extra": e,
                                 "dateAdded": f"2026-0{i + 1}-0{i + 2}T00:00:00Z", "DOI": "", "publicationTitle": "J Sample",
                                 "creators": [{"lastName": "Zhong", "firstName": "Q", "creatorType": "author"}]}}
             for i, (k, t, y, e) in enumerate(ITEMS[:n])]

    def t(url):
        assert url.startswith("http://localhost:23119/api/users/0/"), url
        if url.endswith("/file/view/url"):
            return 200, (storage / "PDF00001" / "paper.pdf").as_uri().encode()
        if "/children" in url:
            parent = url.split("/items/")[1].split("/")[0]
            return 200, json.dumps([{"key": "PDF00001", "data": {"key": "PDF00001", "itemType": "attachment",
                                     "parentItem": parent, "linkMode": "imported_file", "filename": "paper.pdf",
                                     "contentType": "application/pdf"}}]).encode()
        for it in items:
            if url.endswith(f"/items/{it['key']}"):
                return 200, json.dumps(it).encode()
        return 200, json.dumps(items).encode()
    return ZoteroClient(t)


def llm(topic=("new", "老年步态力学", ["认知与步态", "步态与认知障碍"], False), writer_gate: threading.Event | None = None,
        calls: list | None = None):
    def tx(url, headers, body, timeout):
        if calls is not None:
            calls.append(url)
        req = json.loads(body)
        sysmsg = req["messages"][0]["content"]
        if "研究设计类型" in sysmsg:
            out = {"study_type": "cross_sectional", "confidence": 0.8, "reason": "单次测量比较两组",
                   "quote": "共纳入 89 名老年人", "block_id": "b1"}
        elif "主题文件夹" in sysmsg:
            out = {"choice": topic[0], "folder": topic[1], "reason": "与已有文件夹主题接近但不完全相同",
                   "alternatives": topic[2], "confident": topic[3]}
        else:
            if writer_gate is not None:
                writer_gate.wait(30)
            return llm_fake(url, headers, body, timeout)
        return 200, json.dumps({"choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}],
                                "usage": {"prompt_tokens": 11, "completion_tokens": 4}}).encode()
    return tx


def environment(tmp: Path, **kw):
    """-> (cfg, run_kwargs). Uses the same config/models examples as the CLI tests (prices 2 / 8 元 per 1M)."""
    vault, pdf, cfg = setup_run(tmp, prices=(2, 8))
    f = FakeMinerU()
    run_kwargs = {"zotero": zotero(tmp / "Zotero" / "storage", kw.get("n", 2)), "llm_tx": llm(**kw.get("llm", {})),
                  "mineru_kwargs": {"req": f.req, "put": f.put, "sleep": lambda s: None},
                  "pages_fn": lambda p: 2, "stats_fn": STATS}
    return cfg, run_kwargs, f


def sample_project(cfg, title: str = "示例课题：社区老年人步行速度与跌倒风险", default: bool = True):
    """An invented project (never a real user's) with a few items, for the read-only 项目库 tab."""
    from litreader.project import model
    from litreader.project import session as ps
    reg, views = ps.context(cfg)
    snap, rec = reg.create(title, make_default=default)
    obj = reg.load(rec)
    obj["items"]["discipline"] = [model.value("康复医学（示例）", "CONFIRMED", "用户输入")]
    obj["items"]["motivation"] = [model.value("社区老年人跌倒风险筛查需要简便指标（示例）", "PENDING", "AI 归纳", "其他")]
    snap, rec = reg.commit(obj, "SET", "示例：填写学科与动机")
    views.sync(reg, snap)
    return rec


def seed_recent(cfg):
    """Extra SAMPLE receipts (invented, marked 示例) so 最近精读 shows 已停止 / 已取消 rows too."""
    import json
    j = Path(cfg.data_dir) / "jobs" / "sample_extra"
    j.mkdir(parents=True, exist_ok=True)
    rows = [("20261016T091500", {"status": "STOPPED", "stopped_at": "parse", "reason": "E0：解析不到正文（示例）",
                                 "extraction": {"level": "E0"}, "finished": "2026-10-16T09:16:02",
                                 "paper": {"title_zh": "示例：跑步机训练对帕金森步态的影响（扫描版）", "author_last": "Chen",
                                           "year": "2019", "journal": "Sample Gait J", "item_key": "SAMPLE02"}}),
            ("20261015T201000", {"status": "CANCELLED", "stopped_at": "estimate", "finished": "2026-10-15T20:10:40",
                                 "paper": {"title_zh": "示例：可穿戴传感器评估老年人跌倒风险的系统综述与荟萃分析（很长的题名用于测试省略号）",
                                           "author_last": "Garcia", "year": "2022", "journal": "Sample Reviews in Aging Research",
                                           "item_key": "SAMPLE03"}})]
    for ts, r in rows:
        (j / f"receipt-{ts}.json").write_text(json.dumps(r, ensure_ascii=False), "utf-8")
