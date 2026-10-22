"""Mock layer: Zotero local API with a fake transport (shapes mirror Web API v3 item JSON)."""
import json
from pathlib import Path

import pytest

from litreader.errors import Stop
from litreader.zotero.client import Attachment, ZoteroClient, ZoteroUnavailable, norm_title, storage_path
from litreader.zotero.identity import build_identity, detect_source_version, isolate_copy


def item(key, title, added, doi=None, itype="journalArticle"):
    return {"key": key, "data": {"key": key, "itemType": itype, "title": title, "dateAdded": added,
                                 "DOI": doi or "", "date": "2021-05-01",
                                 "creators": [{"lastName": "Zhong", "creatorType": "author"}]}}


def att(key, parent, fn="paper.pdf", mode="imported_file", ct="application/pdf"):
    return {"key": key, "data": {"key": key, "itemType": "attachment", "parentItem": parent,
                                 "linkMode": mode, "filename": fn, "contentType": ct}}


class FakeZotero:
    def __init__(self, items, children, status=200):
        self.items, self.children, self.status, self.urls = items, children, status, []

    def __call__(self, url):
        self.urls.append(url)
        if self.status != 200:
            return self.status, b"{}"
        if "/children" in url:
            k = url.split("/items/")[1].split("/")[0]
            return 200, json.dumps(self.children.get(k, [])).encode()
        return 200, json.dumps(self.items).encode()


def test_only_get_urls_and_local_base():
    t = FakeZotero([item("AAAA1111", "Gait in MCI", "2026-01-01T00:00:00Z")], {"AAAA1111": [att("PDF00001", "AAAA1111")]})
    r = ZoteroClient(t).resolve("Gait in MCI")
    assert r.status == "RESOLVED" and r.attachment.key == "PDF00001"
    assert all(u.startswith("http://localhost:23119/api/") for u in t.urls)


def test_ambiguous_titles_return_candidates_with_date_added():
    t = FakeZotero([item("AAAA1111", "Gait in MCI", "2026-01-02T00:00:00Z"),
                    item("BBBB2222", "gait in mci.", "2026-01-01T00:00:00Z")], {})
    r = ZoteroClient(t).resolve("Gait in MCI")
    assert r.status == "NEEDS_CHOICE_ITEM" and len(r.candidates) == 2
    assert {c.date_added for c in r.candidates} == {"2026-01-02T00:00:00Z", "2026-01-01T00:00:00Z"}
    assert r.attachment is None


def test_no_exact_match_returns_all_candidates_not_autopick():
    t = FakeZotero([item("AAAA1111", "Gait in MCI and SCD", "2026-01-01T00:00:00Z")], {})
    r = ZoteroClient(t).resolve("Gait in MCI")
    assert r.status == "NEEDS_CHOICE_ITEM" and r.candidates[0].parent_key == "AAAA1111"


def test_not_found():
    assert ZoteroClient(FakeZotero([], {})).resolve("x").status == "NOT_FOUND"


def test_multiple_pdfs_need_choice():
    t = FakeZotero([item("AAAA1111", "T", "d")], {"AAAA1111": [att("PDF00001", "AAAA1111", "a.pdf"),
                                                              att("PDF00002", "AAAA1111", "a_zh.pdf")]})
    r = ZoteroClient(t).resolve("T")
    assert r.status == "NEEDS_CHOICE_ATTACHMENT" and len(r.attachments) == 2


def test_linked_or_nonpdf_attachments_ignored():
    t = FakeZotero([item("AAAA1111", "T", "d")], {"AAAA1111": [att("PDF00001", "AAAA1111", mode="linked_url"),
                                                              att("SNAP0001", "AAAA1111", "s.html", ct="text/html")]})
    assert ZoteroClient(t).resolve("T").status == "NO_PDF"


def test_parent_mismatch_stops():
    t = FakeZotero([item("AAAA1111", "T", "d")], {"AAAA1111": [att("PDF00001", "ZZZZ9999")]})
    with pytest.raises(Stop):
        ZoteroClient(t).resolve("T")


def test_api_disabled_403():
    with pytest.raises(ZoteroUnavailable):
        ZoteroClient(FakeZotero([], {}, status=403)).search("x")


def test_norm_title():
    assert norm_title("Gait  in MCI：A Study.") == norm_title("gait in mci a study")


def test_storage_path_and_attacks(tmp_path):
    a = Attachment("PDF00001", "AAAA1111", "imported_file", "x.pdf", "application/pdf")
    assert storage_path(tmp_path, a) == tmp_path / "PDF00001" / "x.pdf"
    for bad in ["../x.pdf", "a/b.pdf", "..", None]:
        with pytest.raises(Stop):
            storage_path(tmp_path, Attachment("PDF00001", "A", "imported_file", bad, None))
    with pytest.raises(Stop):
        storage_path(tmp_path, Attachment("../../etc", "A", "imported_file", "x.pdf", None))


@pytest.mark.parametrize("fn,flag", [("Zhong2021_zh.pdf", "TRANSLATION_SUSPECTED"), ("paper-cn.pdf", "TRANSLATION_SUSPECTED"),
                                     ("论文中文版.pdf", "TRANSLATION_SUSPECTED"), ("zhong2021.pdf", "ORIGINAL_UNVERIFIED"),
                                     ("zhang_2021.pdf", "ORIGINAL_UNVERIFIED")])
def test_translation_detection_filename(fn, flag):
    assert detect_source_version(fn).flag == flag


def test_translation_detection_by_text_ratio():
    assert detect_source_version("zhong2021.pdf", cjk_ratio=0.8).flag == "TRANSLATION_SUSPECTED"


def test_isolate_copy_and_identity(tmp_path):
    src = tmp_path / "s.pdf"; src.write_bytes(b"%PDF-1.4 fake")
    before = src.read_bytes()
    cp, sha = isolate_copy(src, tmp_path / "work")
    assert cp.read_bytes() == before and src.read_bytes() == before and cp != src
    from litreader.zotero.client import Candidate
    c = Candidate("AAAA1111", "T", "d", "journalArticle", None)
    a = Attachment("PDF00001", "AAAA1111", "imported_file", "s.pdf", "application/pdf")
    ident = build_identity("user:0", c, a, sha)
    assert ident.attachment_key == "PDF00001" and ident.parent_key == "AAAA1111" and ident.doi is None
    with pytest.raises(Stop):
        build_identity("user:0", c, Attachment("PDF00001", "OTHER000", "imported_file", "s.pdf", None), sha)
