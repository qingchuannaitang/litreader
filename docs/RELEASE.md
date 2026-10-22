# 发布与更新检查（G8-9）

Litreader 的「检查更新」只做一件事：GET 一个公开的 `latest.json`，比较版本号。不上传任何数据（无用户 ID、无 Cookie、无统计），失败时静默。

## latest.json 格式

```json
{
  "version": "0.6.0",
  "notes": "本版更新说明（一两句，界面最多显示 80 字）",
  "download_url": "https://…/litreader-0.6.0.zip",
  "qq_group": "1126184965"
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `version` | 是 | 点分数字，如 `0.6.0`；比本机新时才提示 |
| `notes` | 否 | 更新说明 |
| `download_url` | 否 | 必须 `https://`；「查看更新」在浏览器打开它。为空时不显示该按钮 |
| `qq_group` | 否 | 5–12 位数字；有值时覆盖应用内默认群号 1126184965 |

文件最大读取 64 KB；格式不对等同于"没查到"。

## 地址

`src/litreader/update.py` 的 `DEFAULT_URLS` 依次尝试，第一个返回有效 JSON 的为准：

1. GitHub raw：`https://raw.githubusercontent.com/qingchuannaitang/litreader/main/latest.json` —— **已生效**（v1.0.1 起，仓库根目录的 `latest.json`）。GitHub raw 有几分钟缓存，推送后稍等再测。
2. VPS：`https://example.invalid/litreader/latest.json` —— **占位**，`.invalid` 永远不会被请求；VPS 与域名（需 ICP 备案）定稿后再填。

也可以在 `<应用数据目录>/gui/prefs.json` 里设置 `"update_urls": [...]` 覆盖；`"feedback_url"` 覆盖「提建议」链接，默认 `https://github.com/qingchuannaitang/litreader/issues`（已可用）。

## 发布步骤

开发在私有工作仓库（完整历史）；公开仓库 `qingchuannaitang/litreader` 只接收每个版本一个提交，内容由 `git archive`（遵守 `.gitattributes` 的 `export-ignore`，不含内部开发记录）导出。

1. **改版本号：** `src/litreader/__init__.py` 与 `pyproject.toml`；README 里的示例文件名。
2. **测试与检查：** `./.venv/bin/python -m pytest -q`；隐私检查（无密钥、无个人路径 / vault 名 / 课题名 / 论文 PDF）。
3. **源码包：** `git archive --format=zip --prefix=litreader/ -o dist/litreader-<版本>.zip HEAD`。
4. **生成 latest.json：**
   ```bash
   python scripts/make_latest_json.py --notes "本版更新说明" \
     --download-url https://github.com/qingchuannaitang/litreader/releases/latest -o latest.json
   ```
   `download_url` 固定指向「最新发布页」，用户点「查看更新」即可看到 .app 与源码包。
5. **公开仓库提交：** 在公开仓库的克隆里，在 `origin/main` 之上清空工作区、解压 `git archive` 的内容（含新的 `latest.json`），提交 `litreader v<版本>`，作者 `晴川奶糖 <263959002+qingchuannaitang@users.noreply.github.com>`；确认 diff 后 `git push origin main`。
6. **GitHub Release：**
   ```bash
   gh release create v<版本> dist/litreader-<版本>.zip --repo qingchuannaitang/litreader \
     --title "litreader v<版本>" --notes-file release_notes.md
   ```
   发布说明里写清 .app 首次打开方法（点「完成」不要点「移到废纸篓」→ 系统设置「仍要打开」或 `xattr -dr com.apple.quarantine`）与钥匙串「始终允许」。
7. **Mac 应用：** 在 Mac 上 `sh scripts/build_app.sh`，然后
   `cd dist && ditto -c -k --keepParent Litreader.app Litreader-<版本>-mac.zip`，再
   `gh release upload v<版本> dist/Litreader-<版本>-mac.zip --repo qingchuannaitang/litreader`。
8. **验证：** 几分钟后打开 raw 地址确认 `version` 已更新；应用内「检查更新」应提示新版本。用户端每天最多自动检查一次。

## 用户端行为

- 设置「自动检查更新」默认开，每天最多一次；「检查更新」立即检查。
- 有新版本：侧栏版本号旁出现红点，内容区顶部出现提示条：查看更新 / 跳过此版本 / 稍后提醒（3 天）。
- 网络失败：自动检查完全静默；手动检查显示「暂时无法检查（网络不可用）」。
