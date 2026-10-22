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

## 地址（TODO：可配置，当前均为占位）

`src/litreader/update.py` 的 `DEFAULT_URLS` 依次尝试，第一个返回有效 JSON 的为准：

1. GitHub raw：`https://raw.githubusercontent.com/qingchuannaitang/litreader/main/latest.json` —— **占位**，仓库尚未创建。
2. VPS：`https://example.invalid/litreader/latest.json` —— **占位**，`.invalid` 永远不会被请求。

正式发布前把它们改成真实地址；也可以在 `<应用数据目录>/gui/prefs.json` 里设置 `"update_urls": [...]` 覆盖（同理 `"feedback_url"` 覆盖「提建议」链接，默认 `https://github.com/qingchuannaitang/litreader/issues`，仓库待建）。

## 发布步骤

1. 改 `src/litreader/__init__.py` 与 `pyproject.toml` 的版本号，跑全量测试与密钥检查。
2. 打包 `dist/litreader-<版本>.zip`，上传到下载地址。
3. `python scripts/make_latest_json.py --download-url https://…/litreader-<版本>.zip --notes "…"` 生成 `latest.json`。
4. 把 `latest.json` 放到上面的地址（GitHub 仓库根目录 / VPS）。用户端每天最多自动检查一次，也可在「基础设置 → 关于与反馈」点「检查更新」。

## 用户端行为

- 设置「自动检查更新」默认开，每天最多一次；「检查更新」立即检查。
- 有新版本：侧栏版本号旁出现红点，内容区顶部出现提示条：查看更新 / 跳过此版本 / 稍后提醒（3 天）。
- 网络失败：自动检查完全静默；手动检查显示「暂时无法检查（网络不可用）」。
