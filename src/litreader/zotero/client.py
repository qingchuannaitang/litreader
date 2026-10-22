"""Read-only Zotero local API client (http://localhost:23119/api/).

Only GET is ever issued. Transport is injectable so tests never touch the network.
Response shapes follow Web API v3 item JSON: {"key":..., "data": {...}}.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from ..errors import LitError, Stop

DEFAULT_BASE = "http://localhost:23119/api"


class ZoteroUnavailable(LitError):
    pass


class Transport(Protocol):
    def __call__(self, url: str) -> tuple[int, bytes]: ...


def urllib_transport(url: str) -> tuple[int, bytes]:  # pragma: no cover - real network
    req = urllib.request.Request(url, method="GET", headers={"Zotero-API-Version": "3"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        raise ZoteroUnavailable(f"Zotero local API unreachable: {e}") from e


@dataclass(frozen=True)
class Attachment:
    key: str
    parent_key: str | None
    link_mode: str
    filename: str | None
    content_type: str | None

    @property
    def is_stored_pdf(self) -> bool:
        return self.link_mode == "imported_file" and (self.content_type == "application/pdf"
                                                      or (self.filename or "").lower().endswith(".pdf"))


@dataclass(frozen=True)
class Candidate:
    parent_key: str
    title: str
    date_added: str
    item_type: str
    doi: str | None
    creators: tuple[str, ...] = ()
    year: str | None = None
    title_zh: str | None = None   # translated title if the user stored one (Extra: titleTranslation / 标题翻译)


@dataclass
class Resolution:
    """Either resolved to exactly one (parent, attachment) or a list needing a human choice."""
    status: str  # RESOLVED | NEEDS_CHOICE_ITEM | NEEDS_CHOICE_ATTACHMENT | NOT_FOUND | NO_PDF
    candidates: list[Candidate] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    item: Candidate | None = None
    attachment: Attachment | None = None


def norm_title(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    s = re.sub(r"[.。:：,，;；!?！？\"'“”‘’()（）\[\]]", " ", s)
    return re.sub(r"[\s\u3000]+", " ", s).strip()


class ZoteroClient:
    def __init__(self, transport: Transport = urllib_transport, base: str = DEFAULT_BASE,
                 library_prefix: str = "users/0"):
        self.t, self.base, self.lib = transport, base.rstrip("/"), library_prefix
        self.calls: list[str] = []

    def _get(self, path: str, **params) -> object:
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{self.base}/{self.lib}/{path}" + (f"?{q}" if q else "")
        self.calls.append(url)
        status, body = self.t(url)
        if status == 403:
            raise ZoteroUnavailable("Zotero local API disabled (403); enable it in Zotero settings")
        if status != 200:
            raise ZoteroUnavailable(f"Zotero GET {path} -> HTTP {status}")
        return json.loads(body)

    @staticmethod
    def _cand(it: dict) -> Candidate:
        d = it["data"]
        creators = tuple(f"{c.get('lastName') or c.get('name','')}" for c in d.get("creators", []))
        y = re.search(r"\d{4}", d.get("date", "") or "")
        tz = None
        for line in (d.get("extra") or "").splitlines():
            m = re.match(r"\s*(?:titleTranslation|标题翻译|中文标题|译名)\s*[:：]\s*(.+)", line)
            if m:
                tz = m.group(1).strip()
                break
        return Candidate(it["key"], d.get("title", ""), d.get("dateAdded", ""), d.get("itemType", ""),
                         d.get("DOI") or None, creators, y.group(0) if y else None, tz)

    def search(self, query: str, limit: int = 25, qmode: str | None = None) -> list[Candidate]:
        items = self._get("items/top", q=query, qmode=qmode, itemType="-attachment", sort="dateAdded",
                          direction="desc", limit=limit)
        return [self._cand(i) for i in items if i["data"].get("itemType") not in ("attachment", "note")]

    def recent(self, limit: int = 5) -> list[Candidate]:
        items = self._get("items/top", itemType="-attachment", sort="dateAdded", direction="desc", limit=limit)
        return [self._cand(i) for i in items]

    def attachments(self, parent_key: str) -> list[Attachment]:
        kids = self._get(f"items/{parent_key}/children")
        out = []
        for k in kids:
            d = k["data"]
            if d.get("itemType") != "attachment":
                continue
            out.append(Attachment(k["key"], d.get("parentItem"), d.get("linkMode", ""),
                                  d.get("filename"), d.get("contentType")))
        return out

    def _get_raw(self, path: str) -> tuple[int, bytes]:
        url = f"{self.base}/{self.lib}/{path}"
        self.calls.append(url)
        return self.t(url)

    def item_json(self, key: str) -> dict:
        """Full item JSON (for bibliographic metadata)."""
        return self._get(f"items/{key}")

    def file_path(self, attachment_key: str) -> Path | None:
        """Local API only: GET items/<key>/file/view/url returns the file:// URL as plain text. None if unavailable."""
        if not re.fullmatch(r"[A-Z0-9]{8}", attachment_key):
            raise Stop(f"unexpected attachment key format: {attachment_key!r}")
        status, body = self._get_raw(f"items/{attachment_key}/file/view/url")
        if status != 200:
            return None
        url = body.decode("utf-8", "replace").strip()
        if not url.startswith("file://"):
            return None
        return Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path))

    def resolve(self, title: str) -> Resolution:
        """Never auto-picks among ambiguous options."""
        cands = self.search(title)
        if not cands:
            return Resolution("NOT_FOUND")
        exact = [c for c in cands if norm_title(c.title) == norm_title(title)]
        if len(exact) != 1:
            return Resolution("NEEDS_CHOICE_ITEM", candidates=exact or cands)
        item = exact[0]
        atts = self.attachments(item.parent_key)
        for a in atts:  # consistency: every child must point back to this parent
            if a.parent_key != item.parent_key:
                raise Stop(f"attachment {a.key} parentItem={a.parent_key} != {item.parent_key}")
        pdfs = [a for a in atts if a.is_stored_pdf]
        if not pdfs:
            return Resolution("NO_PDF", item=item, attachments=atts)
        if len(pdfs) > 1:
            return Resolution("NEEDS_CHOICE_ATTACHMENT", item=item, attachments=pdfs)
        return Resolution("RESOLVED", item=item, attachment=pdfs[0])


def storage_path(storage_root: Path, att: Attachment) -> Path:
    """<storage_root>/<attachmentKey>/<filename>; rejects path tricks in filename."""
    if not att.filename or "/" in att.filename or "\\" in att.filename or att.filename in (".", ".."):
        raise Stop(f"unsafe or missing attachment filename: {att.filename!r}")
    if not re.fullmatch(r"[A-Z0-9]{8}", att.key):
        raise Stop(f"unexpected attachment key format: {att.key!r}")
    return Path(storage_root) / att.key / att.filename
