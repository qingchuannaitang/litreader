# litreader 界面原型（UI prototype）

文件：`docs/design/ui_prototype/litreader_ui_prototype.html`。这是一个单文件、可离线打开的原型：CSS/JS 都内嵌，不连网，在 Mac 上双击用浏览器打开即可。
全部数据都是**示例数据**：数字来自 DeepGaitLab 第 3 次 Mac 实跑（c69a7ad）和 Zhong 2021 golden，其余标了“示例/示意”。原型不连接 Zotero，也不调用模型。Key 只显示掩码；课题名用「我的课题（示例）」代替。
截图时可以直接打开某一页：在文件地址后加 `#flow-3`（第 3 步）、`#flow-8`、`#result-ev`、`#models-vision`，再加 `-dark` 是深色模式。

## 页面与 CLI 对应

| 页面 | 用途 | 对应 CLI / 函数 |
|---|---|---|
| 主页 | 一句话指令，最近精读（状态、主题文件夹、日期、E 级） | `litreader read "…"` → `intent` 解析、`psession.split_directive`、`tsession.split_request`；最近列表取自回执（receipt） |
| 精读流程 ① 选择论文 | 英文题名、机翻中文题名、年份、加入日期、条目 Key | `realrun.choose_item`、`translate_candidates` |
| ② 关联课题 | 选课题快照 / 不关联 / 新建 | `project.session.resolve`（QUESTION、`ensure_location`） |
| ③ 费用估算 | 各角色输入/输出 token 区间（±40%）、单价或“未填单价”、MinerU 缓存/上传、上传同意、继续/取消 | `estimate.estimate`、`realrun.show_estimate`、`_yes("是否继续？")`、`parse_pdf(consent=True)` |
| ④ 解析 | E0–E3、无正文但已覆盖的页面、图注提示 | `extraction_level`、`KIND_ZH`；E0/E1 时停止（`Stop`） |
| ⑤ 类型与模板 | 论文类型、原文依据、置信度；主模板列表 + 用 m 调整模块 | `templates.classify`、`templates.session.prepare`（“回车确认 / 序号 / m / q”） |
| ⑥ 进度 | 看图 / 主笔 / 交叉核对与措辞审查 / 项目视角 | `vision`、writer、`crosscheck` + `wording_judge`、`project.lens.run` |
| ⑦ 作者冲突 | PDF 未核实时默认 Zotero，p 改用 PDF | `realrun.choose_first_author` |
| ⑧ 主题文件夹 | 用建议 / 选已有 / 新建（需再确认） | `realrun.choose_topic`、`naming.sanitize` |
| ⑨ 完成 | 写入路径（不覆盖） | `render`、`write_*`（独占创建） |
| 结果页 | 笔记预览（三分钟、问题式标题、图块、PAPER/INFERENCE/UNKNOWN、页码链接）、证据摘要、实际与估算用量、打开按钮、试运行横幅 | `l2_note_v2.render`、`render_evidence`、`realrun.show_actual` / `actual_usage` |
| 模型设置 | 三个角色 × 主用 + 3 个备用；厂商/模型名/URL/Key（钥匙串）、可选单价、测试连接 | `litreader models set/test/list`、`llm.models`（SLOT_NAMES、presets） |
| 模板库 & 项目库 | 模板列表、设为默认、查看/审核；课题快照版本、已确认/待定、写入位置 | `litreader templates list/export/approve`、`registry.prefer`；`litreader project review/init` |
| 基础设置 | Zotero 目录与本地接口、Obsidian 库、解析器（MinerU/PaddleOCR 各自的 Key）、题名机翻、写入模式（正式写入锁定） | `doctor`、`config.local.toml`（[zotero] [vault] [mineru] [candidates] [templates]）、`key set` |

## 鸿涛的决定（2026-10-18）

1. **框架**：现在用 PySide6；以后再做原生 macOS 设计。
2. **流程**：保留分步向导（stepper）。
3. **估算同意**：每篇都要点“继续”。没上传过的论文另需勾选“同意上传”。费用估算按以下规则（已实现，4bea3c7）：
   - token 估算与模型无关，只看论文长度和图数；界面注明“不同厂商分词器（tokenizer）不同”。
   - 价格只来自每个模型槽位里用户自己填的 price_in/price_out（元 / 1M tokens），程序不内置价格；没填时只显示 token，并标“未填单价”。
   - 每个模型单独校准：每次跑完，在本机应用支持目录的 `calibration.json` 里记录实际用量与默认估算，按（厂商, 模型名, 角色）分开。这个文件不放在 Obsidian 库里，也不含论文内容。
     - 满 3 篇后改用该模型自己的实测中位数比例，范围取实测离散度（±15%–60%），并标“按本机 N 篇实测校准”。
     - 不满 3 篇时按默认比例估算，范围放宽到 ±60%，并标“按默认比例估算，误差较大”，同时注明还差几篇。
     - 每次都以“默认估算”为基准记录，避免越校越偏；某个角色中途由备用模型接替时，这次不记录。
     - 回执（receipt）里记录本次用到的校准和新增的记录。`litreader models list` 每个槽位都显示“已实测 N 篇，还需 M 篇才启用本模型校准”。
4. **作者冲突、主题文件夹不自动接受**；默认值预选，回车即可。主题文件夹拿不准时（新名字，或模型自己说不确定）：
   - 列出 a/b/c 三个建议，再列出已有文件夹的序号，并允许直接输入新名称。
   - 新名称会被整理（去掉文件名不允许的字符），并校验：不能为空，不能以 _ 或 . 开头，最多 40 个字符，不能用保留名。
   - 新名称与已有文件夹同名时（不区分大小写）直接复用；否则确认后，在试运行文件夹里独占创建。
   - 模型很确定、而且是复用已有文件夹时，和以前一样直接用。
5. **结果页**：简版自己渲染，完整效果在 Obsidian 里看。
6. **正式写入**：继续锁定。
7. **模型设置**：GUI 和 CLI 共用 `models.toml`，Key 只放钥匙串。
8. **外观**：跟随系统深浅色（也可以手动选），侧栏保持精简。风格参考 Gemini 桌面版：留白多、圆角卡片、柔和配色、主页中央一个大输入框。不使用 Google 的商标或图标。

## v0.3 修改（鸿涛 2026-10-18 第二轮反馈）

### 1. 头像（app icon）
- 侧栏左上显示柴犬“猛男”头像，下面是名称 “Litreader”。小图存放在 `assets/app_icon.png`（256 px）和 `assets/app_icon_128.png`；原型 HTML 内嵌 128 px 的 base64 版本，打开时不需要联网。
- **仅供个人使用**：这张图可能是第三方作品，版权不明。若以后公开分发（GitHub Release、送给同学等），必须换成原创或有授权的图标。
- PySide6 计划：`QApplication.setWindowIcon(QIcon("assets/app_icon.png"))`；打包成 .app 时用 `iconutil` 从 16–1024 px 的 iconset 生成 `.icns`（以后再做）。

### 2. “获取 Token” 链接（2026-10-18 已核实，curl 返回 200）
| 用途 | 链接 |
|---|---|
| MinerU 获取 Token | https://mineru.net/apiManage/token |
| MinerU 接口文档 | https://mineru.net/apiManage/docs |
| PaddleOCR：飞桨 AI Studio 访问令牌（access token） | https://aistudio.baidu.com/index/accessToken |
| PaddleOCR 服务页 | https://aistudio.baidu.com/paddleocr/task |
| AI Studio 访问令牌说明 | https://ai.baidu.com/ai-doc/AISTUDIO/slmkadt9z |
| Zotero 本地接口（local API）文档 | https://www.zotero.org/support/dev/web_api/v3/local_api |

- 这些链接在系统浏览器中打开（PySide6 用 `QDesktopServices.openUrl`），程序不嵌网页、不代填账号。拿到 Token 后点“更换”粘贴，Token 存进钥匙串（Keychain），界面只显示打码后的样子。
- 以后要加新链接，必须先核实是官方地址，再写进这张表。

### 3. Zotero 一键设置
- 后端是 `litreader setup zotero [--data-dir 路径]`（`src/litreader/zotero/setup.py`），**只读**：
  1. 找 prefs.js。macOS 在 `~/Library/Application Support/Zotero/Profiles/*/prefs.js`，Windows 在 `%APPDATA%\Zotero\Zotero\Profiles`，Linux 在 `~/.zotero/zotero`。有多个时用最近修改的那个。
  2. 确定数据目录：`extensions.zotero.useDataDir`=true 时用 `extensions.zotero.dataDir`，否则用 `~/Zotero`。
  3. 检查目录里有没有 `zotero.sqlite` 和 `storage/`。
  4. 探测 `http://localhost:23119/api/`。返回 200 表示可用；403 表示本地接口没开；连不上表示 Zotero 没在运行。
  5. 接口没开时给出开启步骤。步骤按 Zotero 源码核实过：设置 → 高级 → 勾选「允许此计算机上的其他应用程序与 Zotero 通讯」，对应偏好 `extensions.zotero.httpServer.localAPI.enabled`。**litreader 从不替你改 Zotero 的设置**。
  6. 检测到的值和 config 不同时，会问“保存吗？”，回答 y 才写入 `config.local.toml` 的 `[zotero]`。写入前先备份为 `.bak-时间戳`，再校验 TOML，然后原子替换。
- 原型中“基础设置 → Zotero → 一键设置”演示三种状态（可用 / 接口未开 / 未运行），可以用下拉框切换。

### 4. 主页 → 流程页自动跳转 + 交互面板
- 主页提交“精读 XXXX”后直接跳到“精读流程”页。在步骤条（stepper）和本步内容之间加一个**交互面板**：
  - **决策模式**（需要你决定）：问题和选项都做成按钮，括号里是 CLI 对应的按键。包括选择候选论文、关联课题、上传同意、费用确认、模板确认、作者顺序、主题文件夹。
  - **流式模式**（运行中）：上面是数据流向图（Zotero PDF → 解析 → 看图 → 主笔 → 交叉核对 → Obsidian），下面是滚动日志，显示“看图 n/9”、主笔 token 实时计数、“交叉核对 n/15”。系统开启“减少动态效果”（prefers-reduced-motion）时，动画和脉冲全部关闭，日志一次性显示出来。
  - “▶ 演示运行”从第 1 步自动走到第 9 步。每个决策等 2 秒后自动选默认项；不点演示时一切照常由你手动选。
- 原型里的数字都是示例数据。

### 5. PySide6 架构与事件总线（event bus，CLI 和 GUI 共用）
现在 `UI.say / UI.ask` 直接 print / input。改为：流程（pipeline）只发出事件，由前端适配器（adapter）负责显示和回答。

| 事件 | 字段 | CLI 适配器 | GUI 适配器 |
|---|---|---|---|
| `stage` | `{stage: "parse"/"vision"/"writer"/"judge"/"lens"/"write", status: "start"/"done"/"skip"}` | 打印标题行 | 步骤条 + 流向图 |
| `progress` | `{stage, done, total, tokens_in?, tokens_out?}` | 覆盖同一行 `看图 3/9` | 日志计数 / 进度条 |
| `log` | `{level: info/warn/error, text}` | 打印 | 追加到日志 |
| `decision_request` | `{id, kind: candidate/topic_link/consent/cost/template/author/topic_folder, prompt, options:[{key,label,detail}], default, allow_custom}` | 现有的 input() 提示 | 交互面板按钮（+ 后台时发系统通知） |
| `decision_response` | `{id, choice, custom_text?}` | input() 的返回值 | 点击按钮 |
| `done` | `{note_path, receipt_path, usage}` | 打印结果 | 结果页 + 通知 |
| `error` | `{stage, message, recoverable}` | 打印 | 错误卡片 + 通知 |

- GUI：流程在 `QThread` 的工作对象（worker）里运行，事件通过 Qt 信号（signal）传到主线程。遇到 `decision_request` 时，worker 阻塞在 `threading.Event` 或 `concurrent.futures.Future` 上，主线程收到按钮点击后 `set_result`，再把 `decision_response` 送回 worker。取消时 Future 收到 `Cancelled`，worker 中止，不写任何笔记。
- CLI：适配器同步调用 input()，行为与现在完全一致，所以现有测试不用改。
- 重构要分小步做：先加 `EventSink` 接口和 CLI 适配器，测试保持全绿，再写 GUI 适配器。**本轮只写了文档和原型模拟，后端还没重构。**

### 6. macOS 行为
- **⌘Q**：有精读在进行时，先弹窗确认：“已调用模型消耗的 token 不会退回；未完成的笔记不会写入 Obsidian”，解析缓存保留。没有进行中的精读就直接退出。PySide6 中在 `closeEvent` / `QApplication.aboutToQuit` 之前拦截（`QCoreApplication` 的 quit 事件）。
- **标准菜单栏**：Litreader（关于 / 设置… ⌘, / 退出 ⌘Q）、文件（新的精读 ⌘N / 打开结果文件夹）、编辑（撤销、复制、粘贴等标准项）、显示（切换深浅色）、窗口（最小化 ⌘M）、帮助（使用指南 / 获取 Token 链接 / 导出诊断包）。Qt 会自动把“关于 / 设置 / 退出”放进应用菜单（QAction.MenuRole）。
- **系统通知**：只在应用不在前台时发送。设置页有总开关（默认开）和三个事件开关：需要抉择 / 完成 / 出错。原型中勾选“模拟：应用在后台”就能看到通知横幅。
  - 方案 A：`QSystemTrayIcon.showMessage`。优点是简单、跨平台、不需要额外依赖。缺点是必须有托盘或菜单栏图标；macOS 上只能显示标题和正文，没有动作按钮；系统通知中心里显示的样式和来源名不太稳定。
  - 方案 B：通过 pyobjc 调用 `UNUserNotificationCenter`。优点是原生通知，可以带“去选择”等动作按钮，权限状态也能查询。缺点是要多装 pyobjc；必须是带 bundle ID 的 .app（最好签名）才稳定，直接 `python` 运行时会失败或没有反应。
  - 建议：先用方案 A，打包成签了名的 .app 以后再换成 B。
  - 权限：macOS 第一次发通知时会询问是否允许。之后可以在“系统设置 → 通知 → Litreader”里修改；用户拒绝后程序不再弹通知，界面内照常提示。

## GUI v1（PySide6，已实现，2026-10-18）

和原型相比有这些改动：
- **步骤顺序**：选择论文 → 费用确认 → 解析与精读 → 主题文件夹 → 完成。后端要先读完论文才能给出主题建议，所以主题文件夹放在精读之后。
- **头像**：默认改为原创的 “L” 字母图标（src/litreader/gui/avatar.py，导出在 assets/litreader_icon*.png）。柴犬图有版权风险，已停用，并在 .gitattributes 里设为 export-ignore，不进发布包。用户可以自选图片，裁剪后存一份副本，也可以恢复默认。
- **终端输出**：CLI 对 stage / progress 事件不额外打印，终端输出和以前完全一样；GUI 用这些事件驱动步骤条、流程节点和进度条。

### 厂商预设（OpenAI 兼容 Base URL；litreader 会在后面拼上 `/chat/completions`）

| 厂商 | Base URL | 核实来源（2026-10-18） |
|---|---|---|
| OpenAI（ChatGPT） | `https://api.openai.com/v1` | platform.openai.com 的 API 参考 |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | ai.google.dev/gemini-api/docs/openai |
| Anthropic Claude | `https://api.anthropic.com/v1` | docs.anthropic.com 的 OpenAI SDK compatibility |
| MiniMax 中国站 | `https://api.minimaxi.com/v1` | 此前 spike 中真实调用验证（官方中文文档链接未能核实，所以没有放文档链接） |
| MiniMax 国际站 | `https://api.minimax.io/v1` | platform.minimax.io 文档 |
| DeepSeek | `https://api.deepseek.com` | api-docs.deepseek.com |
| 自定义 / 中转站 | 用户自己填 | — |

- Claude Code 是命令行工具，不是 API。这里选择 Anthropic 官方的 OpenAI 兼容层（Anthropic 说明它主要用于测试和比较，并且会忽略 response_format），所以这个预设的 json_mode 设为 false，靠提示词和解析器约束输出格式。原生 Messages API 还没有实现。
- 新厂商（OpenAI、Gemini、Anthropic）默认不开 JSON 模式，需要实测后再决定。

## GUI v2 打磨（G3/G4，2026-10-19）
- 视觉上和原型 v0.3 对齐，做法：
  - 用 headless Chrome 把原型渲染成截图，和 offscreen 截图左右对比（compare_*.png）；
  - 设计变量和样式全部在 gui/theme.py；
  - 图标用 Lucide（ISC）。
- 和原型还有这些差别：
  - 没有 License 页（付费版已暂停）；
  - 头像改为原创 “L”；
  - 最近精读没有“状态”列（只列已完成的试运行）；
  - 主页的输入框里显示固定的提示标签（一次一篇 / 只写试运行文件夹 / Zotero 只读），没有课题和模板选择器；
  - 精读流程是 5 步，原型是 9 步；
  - 模型设置采用左侧列表 + 右侧表单，原型是把各个槽位依次往下排；
  - 没有动画（脉冲、流动），节点状态改用静态的虚线和描边表示。
- 模板库 & 项目库：只读的两个标签页（列表 + 详情），刷新模板库 = `templates refresh`。
