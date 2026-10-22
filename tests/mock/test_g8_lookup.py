"""G8-1: quotes/book-title marks stripped before search; no full match -> keyword fallback with a candidate list."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_realrun import ScriptUI  # noqa: E402

from litreader import realrun  # noqa: E402
from litreader.errors import Stop  # noqa: E402
from litreader.zotero.client import Candidate  # noqa: E402

ITEMS = [Candidate("K1", "DeepGaitLab: accurate markerless motion tracking", "2026-01-01", "journalArticle", None),
         Candidate("K2", "Markerless gait analysis in stroke", "2025-01-01", "journalArticle", None),
         Candidate("K3", "Cooking with tracking devices", "2024-01-01", "journalArticle", None)]


class Z:
    def __init__(self):
        self.queries = []

    def search(self, q, limit=25, qmode=None):
        self.queries.append(q)
        ql = q.lower()
        return [c for c in ITEMS if ql in c.title.lower()]

    def attachments(self, key):
        self.picked = key
        return []


def test_clean_query_and_keywords():
    assert realrun.clean_query("《DeepGaitLab》") == "DeepGaitLab"
    assert realrun.clean_query("“Markerless gait”") == "Markerless gait"
    assert realrun.keywords("《Markerless motion tracking in the wild》")[:3] == ["Markerless", "tracking", "motion"]


def test_brackets_stripped_before_search():
    z = Z()
    with pytest.raises(Stop):                       # no PDF attachment -> stops after picking
        realrun.choose_item(z, "《DeepGaitLab》", ScriptUI(["1"]))
    assert z.queries[0] == "DeepGaitLab" and z.picked == "K1"


def test_keyword_fallback_shows_candidates_for_pick():
    z = Z()
    ui = ScriptUI(["1"])
    with pytest.raises(Stop):
        realrun.choose_item(z, "「markerless tracking framework」", ui)
    assert "按关键词" in ui.text and ui.prompts and z.picked == "K1"   # K1 hits 2 keywords; K3 only 1 -> dropped
    assert "Cooking" not in ui.text


def test_nothing_found_message_lists_keywords():
    with pytest.raises(Stop) as e:
        realrun.choose_item(Z(), "完全不存在的题目 xyzzy", ScriptUI([]))
    assert "按关键词" in str(e.value) and "xyzzy" in str(e.value)
