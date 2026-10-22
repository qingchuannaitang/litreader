# litreader：Zotero 论文 → AI 精读笔记 → Obsidian

litreader 是一个 macOS 桌面工具（GUI，图形界面）。你用一句话指定 Zotero 里的一篇论文，它会：

1. 在 Zotero（文献管理软件）里找到这篇论文和它的 PDF 附件（**只读**，不修改 Zotero）；
2. 用 MinerU（云端 PDF 解析服务）或 PaddleOCR 把 PDF 解析成文字块和图表；
3. 调用你自己配置的大模型（LLM，大语言模型，如 DeepSeek；看图可选 MiniMax 等视觉模型）写一篇结构化精读笔记；
4. 逐条核对笔记里的数字和说法是否能在原文中找到（找不到的标为 `UNKNOWN`，被拒绝的说法单独存档）；
5. 把笔记、图表和证据档案（evidence file，所有原始值与核对记录）写进你的 Obsidian（笔记软件）库。

每次运行前都会显示费用估算（cost estimate），等你确认后才调用收费接口。

## 运行要求（Requirements）

- macOS（Apple Silicon 或 Intel），Python 3.11 及以上（推荐用 Homebrew 安装 `python@3.12`）
- Zotero 7，并在设置中打开「允许其他应用程序与 Zotero 通讯」（local API，本地接口）
- 一个 Obsidian 库（vault，库文件夹）
- 你自己的 API Key（接口密钥）：大模型（如 DeepSeek）、MinerU Token；看图模型可选

## 在 macOS 上安装（Install）

```bash
cd ~ && unzip -o -q ~/Downloads/litreader-1.0.1.zip   # 或：git clone https://github.com/qingchuannaitang/litreader.git
cd ~/litreader
python3 -m venv .venv
./.venv/bin/pip install -e ".[mac,gui]"
./.venv/bin/litreader doctor      # 环境自检：不写文件、不上传、不调用收费接口
./.venv/bin/litreader gui         # 打开图形界面
```

首次打开后，在「基础设置」里选择 Zotero 数据目录和你的 Obsidian 库（路径由你自己选择，程序里没有任何写死的个人路径），并填写各个 API Key。更详细的新手分步说明见 [`docs/MAC_RUN_GUIDE.md`](docs/MAC_RUN_GUIDE.md)。

## 安全与隐私（Security & Privacy）

- **API Key 只存在 macOS 钥匙串（Keychain）或环境变量（environment variables）里**，不会写进配置文件、日志或笔记；本软件不内置任何 Key。
- **Zotero 只读**：只读取条目信息和 PDF，绝不修改 Zotero 数据库或原文件。
- **写入范围受限**：笔记、图表和证据档案只写进库中的 `litreader/` 文件夹（笔记在 `litreader/论文库/<主题>/`，可在「基础设置 → Obsidian → 笔记文件夹」改成库里的任意文件夹；旧版的 `_litreader_试运行/` 设置继续有效，已有笔记不会被移动）；同名文件不会被静默覆盖（自动加后缀）。
- 使用 MinerU 时会把 PDF 的**副本**上传到其云端解析，运行前会明确提示并征得同意；已解析过的论文使用本地缓存，不再上传。

## 反馈（Feedback）

- 问题与建议：[GitHub Issues](https://github.com/qingchuannaitang/litreader/issues)
- QQ 交流群：1126184965（软件内左下角 💬 也可一键复制）

## 开发与测试（Development）

```bash
./.venv/bin/pip install -e ".[dev,mac,gui]"
LITREADER_NO_UPDATE_CHECK=1 QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m pytest -q
```

测试全部使用假数据和假模型（fakes），不会调用任何收费接口。

## 许可证（License）

Copyright (C) 2026 王鸿涛 (qingchuannaitang)。以 GNU AGPL-3.0-or-later（GNU Affero 通用公共许可证 第 3 版或更新版本）发布，见 [`LICENSE`](LICENSE)；第三方组件见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

贡献代码前须同意 [`CONTRIBUTING.md`](CONTRIBUTING.md) 中的贡献者许可协议（CLA，Contributor License Agreement）。
