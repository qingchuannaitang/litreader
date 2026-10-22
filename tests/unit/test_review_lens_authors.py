"""Review fix 9 (Lens ADOPT subject) and 10 (Zotero vs PDF author order -> UNKNOWN + prompt)."""
from litreader.project.lens import ADOPT
from litreader.realrun import Cancelled, choose_first_author
from litreader.zotero.metadata import author_order_check, from_item
from tests.fixtures.deepgaitlab import BLOCKS


def test_adopt_subject_is_only_the_project():
    # the archived false rejection (supports[1])
    assert not ADOPT.search("该研究已纳入轻度认知障碍个体在跑步机上行走并接受扰动，提示课题在MCI人群中采集步态数据具有先例可行性")
    for t in ("课题已采用分带跑步机", "本课题将采用双任务范式", "当前项目已确定使用 Kinect", "该课题决定选用 OpenCap"):
        assert ADOPT.search(t), t


def _item(order):
    names = {"Halilaj": "Eni", "Shin": "Soyong", "Li": "Sijia"}
    return {"key": "GBLV2NPH", "data": {"creators": [{"creatorType": "author", "firstName": names[n], "lastName": n} for n in order]}}


def test_author_order_conflict_detected_from_author_line():
    zm = from_item(_item(["Halilaj", "Shin", "Li"]))
    c = author_order_check(zm, BLOCKS)
    assert c and c["zotero_first"] == "Eni Halilaj" and c["pdf_first"] == "Soyong Shin" and c["verified"] is True
    assert author_order_check(from_item(_item(["Shin", "Li", "Halilaj"])), BLOCKS) is None


def test_author_conflict_from_writer_string_when_no_author_line():
    zm = from_item(_item(["Halilaj"]))
    c = author_order_check(zm, [b for b in BLOCKS if b.order != 2], "Soyong Shin, Sijia Li, Zhixiong Li")
    assert c and c["pdf_first"] == "Soyong Shin" and c["verified"] is False
    assert author_order_check(zm, [], "Eni Halilaj, X") is None


class UI:
    def __init__(self, answers):
        self.a, self.said = list(answers), []

    def say(self, m):
        self.said.append(m)

    def ask(self, p):
        self.said.append(p)
        return self.a.pop(0)


def test_prompt_enter_uses_pdf_order_z_uses_zotero():
    c = {"zotero_first": "Eni Halilaj", "pdf_first": "Soyong Shin", "evidence": "x", "verified": True}
    assert choose_first_author(c, UI([""])) == "Soyong Shin"
    assert choose_first_author(c, UI(["?", "z"])) == "Eni Halilaj"
    try:
        choose_first_author(c, UI(["q"]))
        assert False
    except Cancelled:
        pass


def test_render_shows_conflict_as_unknown():
    from litreader.analysis.validator_v2 import validate_v2
    from litreader.render.l2_note_v2 import render
    zm = from_item(_item(["Halilaj", "Shin", "Li"]))
    zm["authors_conflict"] = author_order_check(zm, BLOCKS)
    v = validate_v2({"meta": {}, "sections": {}}, BLOCKS, [])
    md = render(v, blocks=BLOCKS, manifest=[], vision_obs=None, figure_paths={}, attachment_key="A", parent_key="P", e_level="E3",
                translation_notice=None, link_mechanism_verified=False, read_date="d", evidence_link="ev",
                model_info={"text": "m"}, zotero_meta=zm)
    assert "UNKNOWN（作者顺序冲突：Zotero 首位 Eni Halilaj，PDF 首位 Soyong Shin" in md
    assert "Eni Halilaj 等" not in md


def test_unverified_pdf_author_string_defaults_to_zotero_p_keeps_pdf():
    c = {"zotero_first": "Eni Halilaj", "pdf_first": "Soyong Shin", "evidence": "主笔从 PDF 读取的作者串（未通过逐字核对）",
         "verified": False}
    ui = UI([""])
    assert choose_first_author(c, ui) == "Eni Halilaj"
    assert "回车 = Zotero 顺序「Eni Halilaj」" in ui.said[-1] and "p = PDF 顺序「Soyong Shin」（未核实）" in ui.said[-1]
    assert choose_first_author(c, UI(["x", "p"])) == "Soyong Shin"
    assert choose_first_author(c, UI(["z"])) == "Eni Halilaj"
    assert choose_first_author({**c, "verified": True}, UI(["p"])) == "Soyong Shin"
