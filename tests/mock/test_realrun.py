"""Mock layer: Stage 4/5 real-run plumbing (CLI, config, secrets, Zotero file path, MinerU API, dry-run orchestrator).
No network: Zotero, MinerU and LLM are fakes; every write must land inside <vault>/<dry_run_dir>/."""
import io
import json
import zipfile
from pathlib import Path

import pytest

from litreader import appconfig, cli, realrun, secrets
from litreader.errors import Stop
from litreader.hashing import sha256_file
from litreader.parse.mineru_api import parse_pdf
from litreader.zotero.client import ZoteroClient

ROOT = Path(__file__).resolve().parents[2]


class MemKeyring:
    def __init__(self):
        self.d = {}

    def get_password(self, s, n):
        return self.d.get((s, n))

    def set_password(self, s, n, v):
        self.d[(s, n)] = v

    def delete_password(self, s, n):
        self.d.pop((s, n))

    def get_keyring(self):
        return self


@pytest.fixture
def kr(monkeypatch):
    k = MemKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    return k


def write_cfg(tmp_path, vault, vision=False, prices=None):
    s = (ROOT / "config.example.toml").read_text("utf-8")
    s = s.replace('root = ""', f'root = "{Path(vault).as_posix()}"', 1)
    s = s.replace('data_dir = ""', f'data_dir = "{(tmp_path / "appdata").as_posix()}"')
    p = tmp_path / "config.local.toml"
    p.write_text(s, "utf-8")
    m = (ROOT / "models.example.toml").read_text("utf-8").replace('model = ""', 'model = "user-model"')
    if not vision:
        m = m.replace("[[vision]]", "[[vision_disabled]]")
    if prices:
        m = m.replace('key_ref = "DEEPSEEK_API_KEY"', f'key_ref = "DEEPSEEK_API_KEY"\nprice_in = {prices[0]}\nprice_out = {prices[1]}')
    (tmp_path / "models.toml").write_text(m, "utf-8")
    return p


def test_example_config_has_no_personal_values_and_loads(tmp_path):
    s = (ROOT / "config.example.toml").read_text("utf-8")
    assert 'root = ""' in s
    for f in ["config.example.toml", "models.example.toml", "docs/MAC_RUN_GUIDE.md", "scripts/mac_install.sh"]:
        t = (ROOT / f).read_text("utf-8")
        assert not __import__("re").search(r"/Users/(?!<)", t), f      # only "/Users/<你的用户名>" placeholders
    with pytest.raises(Stop):
        appconfig.load(str(tmp_path / "nope.toml"))
    (tmp_path / "v").mkdir()
    cfg = appconfig.load(str(write_cfg(tmp_path, tmp_path / "v")))
    assert cfg.dry_run_root == tmp_path / "v" / "litreader" and cfg.llm.chain("extract")[0].model == "user-model" and not cfg.legacy_models


def test_empty_vault_root_stops(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text((ROOT / "config.example.toml").read_text("utf-8"), "utf-8")
    with pytest.raises(Stop, match="root"):
        appconfig.load(str(p))


def test_secrets_env_first_then_keyring_and_selftest(kr, monkeypatch):
    monkeypatch.delenv("X_KEY", raising=False)
    assert secrets.get("X_KEY") is None
    secrets.set_secret("X_KEY", "from-keyring")
    assert secrets.get("X_KEY") == "from-keyring" and secrets.SecretEnv().get("X_KEY") == "from-keyring"
    monkeypatch.setenv("X_KEY", "from-env")
    assert secrets.get("X_KEY") == "from-env"
    ok, _ = secrets.selftest()
    assert ok and ("litreader", "litreader-selftest") not in kr.d


def test_key_set_never_prints_value(kr, monkeypatch, capsys):
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "sk-SECRET-123456")
    assert cli.main(["key", "set", "DEEPSEEK_API_KEY"]) == 0
    out = capsys.readouterr().out
    assert "SECRET" not in out and kr.d[("litreader", "DEEPSEEK_API_KEY")] == "sk-SECRET-123456"
    assert cli.main(["key", "test"]) == 0


def test_zotero_file_path_from_local_api():
    def t(url):
        assert url.endswith("/items/PDF00001/file/view/url")
        return 200, b"file:///Users/me/Zotero/storage/PDF00001/My%20Paper.pdf\n"
    assert ZoteroClient(t).file_path("PDF00001") == Path("/Users/me/Zotero/storage/PDF00001/My Paper.pdf")
    assert ZoteroClient(lambda u: (404, b"")).file_path("PDF00001") is None
    with pytest.raises(Stop):
        ZoteroClient(t).file_path("../etc")


def mineru_zip(evil=False):
    cl = [{"type": "text", "text": "Gait study title", "text_level": 1, "page_idx": 0, "bbox": [0, 0, 100, 10]},
          {"type": "text", "text": "共纳入 89 名老年人。", "page_idx": 0},
          {"type": "text", "text": "结果显示步速下降。", "page_idx": 1}]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x_content_list.json", json.dumps(cl, ensure_ascii=False))
        z.writestr("layout.json", json.dumps({"pdf_info": [{}, {}]}))
        if evil:
            z.writestr("../evil.txt", "x")
    return b.getvalue()


class FakeMinerU:
    def __init__(self, evil=False):
        self.calls, self.evil, self.uploaded = [], evil, None

    def req(self, method, url, token=None, json_body=None, timeout=120):
        self.calls.append((method, url, bool(token)))
        if url.endswith("/file-urls/batch"):
            return 200, json.dumps({"code": 0, "data": {"batch_id": "B1", "file_urls": ["https://up.example/s"]}}).encode()
        if "/extract-results/" in url:
            return 200, json.dumps({"code": 0, "data": {"extract_result": [
                {"state": "done", "full_zip_url": "https://cdn.example/r.zip"}]}}).encode()
        return 200, mineru_zip(self.evil)

    def put(self, url, data):
        self.uploaded = data
        return 200


def test_mineru_requires_consent_and_token(tmp_path):
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(b"%PDF-1.4")
    f = FakeMinerU()
    with pytest.raises(Stop, match="allow-upload"):
        parse_pdf(pdf, tmp_path / "o", "tok", consent=False, req=f.req, put=f.put)
    with pytest.raises(Stop, match="Token"):
        parse_pdf(pdf, tmp_path / "o", "", consent=True, req=f.req, put=f.put)
    assert f.calls == [] and f.uploaded is None
    ext = parse_pdf(pdf, tmp_path / "o", "tok", consent=True, req=f.req, put=f.put, sleep=lambda s: None, log=lambda m: None)
    assert (ext / "x_content_list.json").is_file() and f.uploaded == b"%PDF-1.4"


def test_mineru_zip_slip_rejected(tmp_path):
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(b"%PDF")
    f = FakeMinerU(evil=True)
    with pytest.raises(Stop, match="不安全"):
        parse_pdf(pdf, tmp_path / "o", "tok", consent=True, req=f.req, put=f.put, sleep=lambda s: None, log=lambda m: None)
    assert not (tmp_path / "evil.txt").exists()


def zot_fake(storage):
    items = [{"key": "AAAA1111", "data": {"key": "AAAA1111", "itemType": "journalArticle", "title": "Gait study title",
              "dateAdded": "2026-01-01T00:00:00Z", "DOI": "", "date": "2021",
              "creators": [{"lastName": "Zhong", "firstName": "Q", "creatorType": "author"}],
              "publicationTitle": "J Test"}}]
    child = [{"key": "PDF00001", "data": {"key": "PDF00001", "itemType": "attachment", "parentItem": "AAAA1111",
              "linkMode": "imported_file", "filename": "paper.pdf", "contentType": "application/pdf"}}]
    urls = []

    def t(url):
        urls.append(url)
        assert url.startswith("http://localhost:23119/api/users/0/")
        if url.endswith("/file/view/url"):
            return 200, (storage / "PDF00001" / "paper.pdf").as_uri().encode()
        if "/children" in url:
            return 200, json.dumps(child).encode()
        if url.endswith("/items/AAAA1111"):
            return 200, json.dumps(items[0]).encode()
        return 200, json.dumps(items).encode()
    return t, urls


def llm_fake(url, headers, body, timeout):
    out = {"meta": {"title_zh": {"value": "步态研究", "label": "INFERENCE"}}, "facts": [
        {"field": "sample_size_total", "value": "89", "context": "共纳入 89 名老年人", "block_id": "b1",
         "physical_page": 1, "label": "PAPER"}]}
    return 200, json.dumps({"choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}],
                            "usage": {"prompt_tokens": 7, "completion_tokens": 3}}).encode()


class ScriptUI:
    def __init__(self, answers):
        self.answers, self.out, self.prompts = list(answers), [], []

    def say(self, m):
        self.out.append(m)

    def ask(self, p):
        self.prompts.append(p)
        assert self.answers, f"unexpected prompt: {p}"
        return self.answers.pop(0)

    @property
    def text(self):
        return "\n".join(self.out)


def setup_run(tmp_path, first_question_done=True, **kw):
    """first_question_done: a user who already answered/skipped the Stage 7 first-use project question."""
    vault = tmp_path / "vault"; vault.mkdir()
    (vault / "我的旧笔记.md").write_text("keep", "utf-8")
    (vault / "论文库" / "认知与步态").mkdir(parents=True)
    (vault / "论文库" / "_阅读版本").mkdir()
    storage = tmp_path / "Zotero" / "storage"; (storage / "PDF00001").mkdir(parents=True)
    pdf = storage / "PDF00001" / "paper.pdf"; pdf.write_bytes(b"%PDF-1.4 original")
    cfg = appconfig.load(str(write_cfg(tmp_path, vault, **kw)))
    if first_question_done:
        from litreader.project.session import context
        context(cfg)[0].set_prefs("FIRST_QUESTION", first_question="skipped")
    return vault, pdf, cfg


STATS = lambda p: {"pages": 2, "chars": 3000, "figures": 0, "source": ["fake"]}


def topic_llm(choice, folder):
    def tx(url, headers, body, timeout):
        req = json.loads(body)
        if "研究设计类型" in req["messages"][0]["content"]:
            out = {"study_type": "cross_sectional", "confidence": 0.8, "reason": "单次测量比较两组",
                   "quote": "共纳入 89 名老年人", "block_id": "b1"}
            return 200, json.dumps({"choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}],
                                    "usage": {"prompt_tokens": 11, "completion_tokens": 4}}).encode()
        if "主题文件夹" in req["messages"][0]["content"]:
            out = {"choice": choice, "folder": folder, "reason": "主题相近"}
            return 200, json.dumps({"choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}],
                                    "usage": {"prompt_tokens": 5, "completion_tokens": 2}}).encode()
        return llm_fake(url, headers, body, timeout)
    return tx


def go(cfg, tmp_path, answers, command="精读zotero中的Gait study title，并将精读笔记存入obsidian中",
       tx=None, mineru=None):
    zt, urls = zot_fake(tmp_path / "Zotero" / "storage")
    ui = ScriptUI(answers)
    f = mineru or FakeMinerU()
    r = realrun.run(cfg, command, ui, zotero=ZoteroClient(zt), llm_tx=tx or topic_llm("existing", "认知与步态"),
                    mineru_kwargs={"req": f.req, "put": f.put, "sleep": lambda s: None}, pages_fn=lambda p: 2,
                    stats_fn=STATS)
    return r, ui, f, urls


def test_nl_command_end_to_end_confined_to_test_folder(tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path, prices=(2, 8))
    sha0 = sha256_file(pdf)
    before = set(vault.rglob("*"))
    r, ui, f, urls = go(cfg, tmp_path, ["y", ""])
    assert r["status"] == "DRY_RUN_COMPLETE", r
    assert "本次使用：单篇科研精读笔记V2.0（内置 v1） ＋ 无专业模块" in ui.text and "横断面研究（模型判定" in ui.text
    assert r["template"]["template_id"] == "main.general" and r["template"]["study"]["page"] == 1
    assert "理解为：精读 Zotero 中的「Gait study title」（规则解析）" in ui.text
    assert "运行前估算（ESTIMATE" in ui.text and "将上传 PDF 副本" in ui.text and "约 ¥" in ui.text
    assert "复用已有「认知与步态」" in ui.text and "实际用量" in ui.text
    new = set(vault.rglob("*")) - before
    assert new and all(cfg.dry_run_root in p.parents or p == cfg.dry_run_root for p in new)
    assert (vault / "我的旧笔记.md").read_text("utf-8") == "keep"
    assert sha256_file(pdf) == sha0 == r["pdf_sha_after"] and f.uploaded == b"%PDF-1.4 original"
    assert "论文库/认知与步态/" in r["note"].replace("\\", "/") and Path(r["receipt"]).is_file()
    note = Path(r["note"]).read_text("utf-8")
    assert "zotero://open-pdf/library/items/PDF00001" in note
    assert "[[litreader/论文库/_证据档案/AAAA1111/" in note
    assert all(u.startswith("http://localhost:23119/api/") for u in urls)
    assert r["actual"]["writer"]["in"] == 7 and r["actual"]["writer"]["priced"]
    # second run: cached parse (no upload), new file name, old note untouched
    r2, ui2, f2, _ = go(cfg, tmp_path, ["y", ""])
    assert f2.calls == [] and "已有解析缓存，不上传" in ui2.text
    assert r2["note"] != r["note"] and Path(r["note"]).read_text("utf-8") == note


def test_decline_estimate_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")   # fake (W2: env is hermetic)
    vault, pdf, cfg = setup_run(tmp_path)
    calls = []
    def tx(*a):
        calls.append(a)
        return llm_fake(*a)
    with pytest.raises(realrun.Cancelled):
        go(cfg, tmp_path, ["n"], tx=tx)
    assert calls == [] and not cfg.dry_run_root.exists()


def test_new_topic_requires_confirmation_and_can_pick_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")   # fake (W2: env is hermetic)
    vault, pdf, cfg = setup_run(tmp_path)
    r, ui, _, _ = go(cfg, tmp_path, ["y", "", "1"], tx=topic_llm("new", "老年步态力学"))
    assert "建议新建主题文件夹「老年步态力学」" in ui.text and "论文库/认知与步态/" in r["note"].replace("\\", "/")
    assert not (cfg.dry_run_root / "论文库" / "老年步态力学").exists()
    r, ui, _, _ = go(cfg, tmp_path, ["y", "", "y"], tx=topic_llm("new", "老年步态力学"))
    assert "论文库/老年步态力学/" in r["note"].replace("\\", "/")
    assert not (vault / "论文库" / "老年步态力学").exists()   # real library untouched


def test_hallucinated_existing_folder_becomes_new_proposal(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")   # fake (W2: env is hermetic)
    vault, pdf, cfg = setup_run(tmp_path)
    with pytest.raises(realrun.Cancelled):
        go(cfg, tmp_path, ["y", "", "q"], tx=topic_llm("existing", "不存在的文件夹"))


def test_batch_and_unknown_commands_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")   # fakes
    vault, pdf, cfg = setup_run(tmp_path)
    with pytest.raises(Stop, match="一次只能精读一篇"):
        go(cfg, tmp_path, [], command="批量精读zotero中所有步态论文")
    with pytest.raises(Stop, match="没看懂"):
        go(cfg, tmp_path, ["n"], command="今天天气怎么样")


def test_no_match_stops(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")   # fakes
    vault, pdf, cfg = setup_run(tmp_path)
    def t(url):
        return 200, b"[]"
    with pytest.raises(Stop, match="没有找到"):
        realrun.run(cfg, "精读 不存在的论文", ScriptUI([]), zotero=ZoteroClient(t), llm_tx=llm_fake, stats_fn=STATS)


def test_multiple_candidates_numbered_pick(tmp_path):
    from litreader.zotero.client import ZoteroClient as ZC
    items = [{"key": k, "data": {"key": k, "itemType": "journalArticle", "title": t, "dateAdded": d, "date": y,
              "extra": e, "creators": []}}
             for k, t, d, y, e in [("AAAA1111", "Gait A", "2026-01-02T00:00:00Z", "2021", "titleTranslation: 步态甲"),
                                   ("BBBB2222", "Gait B", "2025-05-01T00:00:00Z", "2024", "")]]
    def t(url):
        if "/children" in url:
            return 200, b"[]"
        return 200, json.dumps(items).encode()
    ui = ScriptUI(["x", "2"])
    with pytest.raises(Stop, match="没有存储在本机的 PDF"):
        realrun.choose_item(ZC(t), "Gait", ui)
    assert "1. Gait A" in ui.text and "中文：步态甲" in ui.text and "2021 · 加入 Zotero：2026-01-02" in ui.text
    assert "请输入 1–2" in ui.text
    with pytest.raises(realrun.Cancelled):
        realrun.choose_item(ZC(t), "Gait", ScriptUI(["q"]))


def test_cli_entry_point_declared():
    s = (ROOT / "pyproject.toml").read_text("utf-8")
    assert 'litreader = "litreader.cli:main"' in s and "keyring" in s
