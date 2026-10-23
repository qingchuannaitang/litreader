"""MinerU precise API client (local-file upload flow, verified in Stage 0 spike docs/spikes/S0_mineru.md).

POST /api/v4/file-urls/batch -> PUT signed URL (NO Content-Type) -> poll extract-results -> download zip.
Token from secrets (env/keyring); never printed. Uploads only happen when the caller passes consent=True.
HTTP functions are injectable for tests.
"""
from __future__ import annotations

import io
import json
import os
import time
import urllib.error
import urllib.request
import shutil
import zipfile
from pathlib import Path

from ..errors import Stop

API = "https://mineru.net/api/v4"


def _req(method, url, token=None, json_body=None, timeout=120):  # pragma: no cover - real network
    headers = {"Accept": "*/*"}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, resp.read()


def _put(url: str, data: bytes) -> int:  # pragma: no cover - real network
    import http.client
    from urllib.parse import urlsplit
    u = urlsplit(url)
    c = http.client.HTTPSConnection(u.netloc, timeout=300)
    c.putrequest("PUT", u.path + ("?" + u.query if u.query else ""), skip_accept_encoding=True)
    c.putheader("Content-Length", str(len(data)))
    c.endheaders()
    c.send(data)
    return c.getresponse().status


def parse_pdf(pdf: Path, out_dir: Path, token: str, *, consent: bool, model_version="vlm", timeout_s=900,
              req=_req, put=_put, sleep=time.sleep, log=print) -> Path:
    """Upload `pdf` (an isolated copy), wait, extract into out_dir/extracted. Returns the extracted dir."""
    if not consent:
        raise Stop("未获上传许可：MinerU 是云端服务，需加 --allow-upload 才会上传 PDF 副本")
    if not token:
        raise Stop("缺少 MinerU Token（MINERU_API_TOKEN）：请用 `litreader key set MINERU_API_TOKEN` 保存")
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        st, raw = req("POST", f"{API}/file-urls/batch", token,
                      json_body={"files": [{"name": pdf.name, "data_id": pdf.stem[:64]}], "model_version": model_version})
        j = json.loads(raw)
        if j.get("code") != 0:
            raise Stop(f"MinerU 申请上传地址失败：code={j.get('code')} msg={j.get('msg')}")
        batch_id, up = j["data"]["batch_id"], j["data"]["file_urls"][0]
        st = put(up, pdf.read_bytes())
        if st not in (200, 201):
            raise Stop(f"MinerU 上传失败：HTTP {st}")
        t0 = time.monotonic()
        while True:
            st, raw = req("GET", f"{API}/extract-results/batch/{batch_id}", token)
            j = json.loads(raw)
            if j.get("code") != 0:
                raise Stop(f"MinerU 查询失败：code={j.get('code')} msg={j.get('msg')}")
            res = j["data"]["extract_result"][0]
            state = res.get("state")
            log(f"  MinerU 状态：{state}")
            if state == "done":
                zip_url = res["full_zip_url"]
                break
            if state == "failed":
                raise Stop(f"MinerU 解析失败：{res.get('err_msg')}")
            if time.monotonic() - t0 > timeout_s:
                raise Stop(f"MinerU 超时（{timeout_s}s，batch {batch_id}）")
            sleep(5)
        st, data = req("GET", zip_url, None, timeout=300)
    except urllib.error.HTTPError as e:  # pragma: no cover
        raise Stop(f"MinerU HTTP {e.code}") from e
    except urllib.error.URLError as e:  # pragma: no cover
        raise Stop(f"MinerU 网络错误：{e.reason}") from e
    (out_dir / "result.zip").write_bytes(data)
    ext = out_dir / "extracted"
    tmp = out_dir / "extracted.partial"
    if tmp.exists():
        shutil.rmtree(tmp)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            if n.startswith("/") or ".." in Path(n).parts:
                raise Stop(f"MinerU 压缩包含不安全路径：{n}")
        z.extractall(tmp)
    if ext.exists():
        shutil.rmtree(ext)
    os.replace(tmp, ext)   # the cache counts only once fully extracted (an interrupted unzip is never "cached")
    (out_dir / "run_meta.json").write_text(json.dumps({"batch_id": batch_id, "model_version": model_version}, indent=1),
                                          "utf-8")
    return ext


PROBE_TASK = "00000000-0000-0000-0000-000000000000"   # deliberately non-existent task id


def check_token(token: str, req=None) -> tuple[bool | None, str]:
    """Free auth check (official docs, 精准解析 API 「获取任务结果」 + 常见错误码): GET /extract/task/<non-existent id>.
    No upload, no parsing, no quota. A0202 (Token 错误) / A0211 (Token 过期) -> False; a task-level answer
    (-60012 找不到任务 / -60013 没有权限 / code 0) means the token was accepted -> True; anything else -> None."""
    if not token:
        return False, "未保存 Token"
    req = req or _req
    try:
        st, raw = req("GET", f"{API}/extract/task/{PROBE_TASK}", token=token, timeout=20)
    except urllib.error.HTTPError as e:   # pragma: no cover - real network
        st, raw = e.code, e.read()
    except Exception as e:  # noqa: BLE001  pragma: no cover - real network
        return None, f"网络错误：{type(e).__name__}"
    try:
        code = str(json.loads(raw or b"{}").get("code"))
    except ValueError:
        code = ""
    if code in ("A0202", "A0211") or st in (401, 403):
        return False, "Token 错误或已过期（" + (code or f"HTTP {st}") + "）"
    if code in ("0", "-60012", "-60013"):
        return True, "Token 有效（查询了一个不存在的任务，未上传、未计费）"
    return None, f"无法判断（HTTP {st}，code {code or '—'}）"
