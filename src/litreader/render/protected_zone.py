"""Protected user-annotation zone (R8, T18).

The zone is delimited by exact marker lines. Machine regeneration must carry the
zone body over byte-for-byte; malformed markers => STOP.
"""
from __future__ import annotations

from ..errors import ProtectedZoneError
from ..hashing import sha256_bytes

BEGIN = "<!-- LIT:USER-NOTES:BEGIN — 以下为“我的批注”，程序不会修改 -->"
END = "<!-- LIT:USER-NOTES:END -->"


def _locate(text: str) -> tuple[int, int]:
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ProtectedZoneError("protected zone markers missing or duplicated")
    b = text.index(BEGIN) + len(BEGIN)
    e = text.index(END)
    if e < b:
        raise ProtectedZoneError("protected zone END before BEGIN")
    return b, e


def empty_zone() -> str:
    return f"{BEGIN}\n\n{END}"


def extract(text: str) -> str:
    b, e = _locate(text)
    return text[b:e]


def carry_over(old_text: str, new_text: str) -> str:
    """Return new_text with its zone body replaced by old_text's zone body."""
    body = extract(old_text)
    b, e = _locate(new_text)
    return new_text[:b] + body + new_text[e:]


def machine_sha(text: str) -> str:
    """Hash of the machine-managed content only (zone body blanked).

    Lets EXISTS recognise an unchanged machine note even after the user wrote
    annotations inside the zone.
    """
    b, e = _locate(text)
    return sha256_bytes((text[:b] + text[e:]).encode("utf-8"))
