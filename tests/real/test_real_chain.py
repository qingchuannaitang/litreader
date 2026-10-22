"""Real-chain layer (L-real). Intentionally NOT_RUN in Stage 1: no real Zotero/Obsidian."""
import pytest

pytestmark = pytest.mark.real


@pytest.mark.skip(reason="NOT_RUN: Stage 1 is offline; real Zotero/Obsidian chain starts Stage 2/8")
@pytest.mark.parametrize("tid", ["T16_real", "T17_real", "T18_real", "T19prime_real"])
def test_real_placeholder(tid):
    pass
