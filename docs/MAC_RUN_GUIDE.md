# 在你的 Mac 上运行 litreader（新手版）

> 这份说明只做一件事：**在你自己的 Mac 上，用一篇论文跑一次精读**。
> 精读只会在你的 Obsidian 库里新建（或使用）一个文件夹 `litreader/`（可在「基础设置」里改），**不碰库里任何已有文件**，也**不修改 Zotero**。
> 不满意的话，把这个文件夹整个删掉就恢复原样。

每一步都写成可以**整段复制**的命令。打开“终端”的方法：按 `⌘ + 空格`，输入 `终端`（或 `Terminal`），回车。
复制一个灰色代码框 → 在终端窗口里按 `⌘ + V` 粘贴 → 按回车。看到 `✅` 就是成功，看到 `❌` 就停下来，把整屏文字截图发给我。

---

## 0. 你需要准备的东西

| 项目 | 说明 |
|---|---|
| Zotero 7（已打开） | 里面已有要读的论文和 PDF 附件 |
| Obsidian 库 | 你的库文件夹（只需在第 4 步把它拖进终端一次） |
| DeepSeek API Key | 正文分析、交叉核对 |
| MinerU API Token | PDF 解析（云端服务，会上传 PDF **副本**，见第 8 节） |
| MiniMax API Key（可选） | 看图；没有也能跑，图的“主要发现”会标“未经视觉模型看图” |
| 代码压缩包 `litreader.zip` | 我会单独发给你，下载到“下载”文件夹即可 |

---

## 1. 安装 Homebrew 和 Python 3.12（只需做一次）

你的 Mac 自带 Python 是 3.9.6，太旧（本工具需要 3.11 或更高），所以要装一个新的，**不会影响系统自带的那个**。

**1.1 先检查是否已经装过 Homebrew：**

```zsh
brew --version
```

- 如果显示 `Homebrew 4.x.x` 之类 → 已安装，跳到 1.3。
- 如果显示 `command not found: brew` → 做 1.2。

**1.2 安装 Homebrew**（会要求输入你的开机密码，输入时屏幕上不显示，正常现象；过程可能 5–15 分钟）：

```zsh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

装完后，**把 Homebrew 加入路径**（Apple 芯片 M1/M2/M3/M4 的 Mac 需要；Intel 芯片的 Mac 执行了也无害）：

```zsh
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
brew --version
```

**1.3 安装 Python 3.12 和 PDF 页数工具 poppler：**

```zsh
brew install python@3.12 poppler
python3.12 --version
```

看到 `Python 3.12.x` 即成功。（poppler 用来核对 PDF 总页数；它是抽取完整度 E 级判断的一部分。）

---

## 2. 放好代码

把 `litreader.zip` 下载到“下载”文件夹，然后：

```zsh
cd ~
unzip -q ~/Downloads/litreader.zip
cd ~/litreader
ls
```

能看到 `README.md  config.example.toml  docs  scripts  src ...` 即可。

> 以后每次使用前，都先执行一次 `cd ~/litreader`。

**更新到新版本**（以后收到新的 `litreader.zip` 时）：

```zsh
cd ~
unzip -o -q ~/Downloads/litreader.zip     # -o = 用新文件覆盖旧文件
cd ~/litreader
```

你的 `config.local.toml`、`models.toml`、`.venv`、钥匙串里的 Key 都不在压缩包里，不会被覆盖；程序是“可编辑安装”，一般不用重新运行安装脚本（只有说明里特别提到时才需要）。

---

## 3. 打开 Zotero 的本地接口（只需做一次）

1. 打开 Zotero → 菜单 **Zotero → 设置…**（Settings）→ **高级**（Advanced）。
2. 勾选 **“允许此计算机上的其他应用程序与 Zotero 通讯”**（Allow other applications on this computer to communicate with Zotero）。
3. 保持 Zotero 开着，在终端测试：

```zsh
curl -s "http://localhost:23119/api/users/0/items/top?limit=1" | head -c 200; echo
```

- 显示一段以 `[{"key":` 开头的文字 → 成功。
- 显示 `Forbidden` 或空白 → 回到第 1、2 步检查勾选，并确认 Zotero 正在运行。

本工具**只向这个本地地址发送“读取”（GET）请求**，不会修改、删除 Zotero 里的任何条目或文件。

---

## 4. 安装 litreader

```zsh
cd ~/litreader
zsh scripts/mac_install.sh
```

脚本会：找到 Python 3.12 → 在 `~/litreader/.venv` 建一个独立环境 → 安装 litreader 和钥匙串组件（keyring）。

中途会提示：**“请把你的 Obsidian 库文件夹从访达拖进这个窗口”**。
这时打开访达，找到你的 Obsidian 库文件夹（就是 Obsidian 里“管理仓库”显示的那个文件夹），**用鼠标把这个文件夹拖进终端窗口**，路径会自动出现，然后按回车。

看到 `✅ 已生成 config.local.toml` 和 `root = "<你的库路径>"`（与你拖进去的文件夹一致），以及 `✅ 已生成 models.toml（主笔/交叉核对：DeepSeek，看图：MiniMax 中国站）` 就对了。

> 你的库路径**只写在** `~/litreader/config.local.toml` 这一个本地文件里，不在代码里。
> 脚本可以重复运行；已有的 `config.local.toml`、`models.toml` 不会被覆盖。

---

## 5. 模型和 Key（只需做一次）

程序有三个“岗位”，每个岗位 1 个**主用**模型 + 最多 **3 个备用**（主用失败时按顺序自动换下一个）：

| 岗位 | 做什么 | 安装后默认 |
|---|---|---|
| 主笔 | 读全文、写精读笔记 | DeepSeek |
| 看图 | 看论文里的图 | MiniMax（中国站） |
| 交叉核对 | 核对看图结论、审查比较措辞、选主题文件夹 | DeepSeek |

每个模型有 4 项：**厂商名称**（随便写，只用于显示）、**模型名**、**URL**、**API Key**。
Key 存在 macOS 自带的“钥匙串”里，**不写进任何文件**。

**5.1 保存 Key**：每条命令运行后，粘贴对应的 Key 再按回车（**粘贴时屏幕不显示，正常**）：

```zsh
cd ~/litreader
./.venv/bin/litreader key set DEEPSEEK_API_KEY
```

```zsh
./.venv/bin/litreader key set MINIMAX_API_KEY
```

```zsh
./.venv/bin/litreader key set MINERU_API_TOKEN
```

首次使用时 macOS 可能弹窗“python 想要访问钥匙串…”，点 **“始终允许”**。

**5.2 钥匙串自检**（存入一个测试项 → 读回 → 删除）：

```zsh
./.venv/bin/litreader key test
```

看到 `✅ 钥匙串自检：Keyring` 即成功。

**5.3 看看现在的模型设置：**

```zsh
./.venv/bin/litreader models list
```

**5.4 实际测试每个模型能不能用**（每个模型发一次极小的请求，和正式精读用**完全相同**的请求设置；看图的发一张白底红色圆形的小图；会产生极少量费用）：

```zsh
./.venv/bin/litreader models test
```

示例：

```
✅ 主笔·主用（DeepSeek deepseek-flash）：OK，JSON 正常，1.2s
✅ 看图·主用（MiniMax（中国站） MiniMax-M3）：OK，识别正确（红），2.0s
✅ 交叉核对·主用（DeepSeek deepseek-flash）：OK，JSON 正常，0.9s
```

`❌ … AUTH` = Key 不对；`❌ … MODEL_OR_URL_NOT_FOUND` = 模型名或 URL 不对；`❌ … KEY_MISSING` = 没存 Key；`❌ … NOT_JSON` = 模型回复了但不是合法 JSON。

想看细节（发给我排查时用）：`./.venv/bin/litreader models test --verbose`，会多显示每个模型的请求设置（JSON 模式、max_tokens、关闭思考等，不含 Key）和原始回复片段（Key 自动隐去）。

**5.5 添加备用模型 / 换模型（可选）**

例如给“主笔”加一个备用（会依次询问 4 项；方括号里是可直接回车保留的值）：

```zsh
./.venv/bin/litreader models set 主笔
```

```
设置 主笔·备用1（直接回车保留方括号里的值）
厂商名称（随便写，例如 DeepSeek / Gemini / 通义）：Gemini
   这个厂商没有预设 URL：请从厂商文档找到 “OpenAI 兼容” 的 Base URL（通常以 /v1 结尾）
URL（OpenAI 兼容 Base URL）：<从厂商文档复制>
模型名（从厂商文档/控制台复制模型 ID）：<从厂商控制台复制>
（可选）单价：输入“输入价 输出价”（元/百万 tokens），例如 2 8；直接回车跳过：
API Key（存入钥匙串，名称 GEMINI_API_KEY；屏幕不显示）：
✅ 已保存 主笔·备用1：…
   下一步：litreader models test 主笔 2
```

- 只有 DeepSeek、MiniMax（中国站/国际站）会自动填好 URL（已核实）；其他厂商请自己从官方文档复制，程序**不会猜**。
- 改某一个：`models set 主笔 1`（1=主用，2–4=备用）；删除：`models remove 主笔 2`。
- **单价**是可选的：填了，运行前后会显示费用估算；不填只显示 token 数。程序里没有任何内置价格，请照厂商价目表自己填。

---

## 6. 环境体检

```zsh
./.venv/bin/litreader doctor
```

正常应全部是 ✅，例如：

```
✅ Python 3.12.x（需要 3.11 或更高）
✅ 配置文件：/Users/<你的用户名>/litreader/config.local.toml
✅ Obsidian 库：<你的库路径>
   笔记只会写入：<你的库路径>/litreader（首次精读时创建）
✅ Zotero 本地接口可用（最近条目：……）
✅ Zotero 附件目录：/Users/<你的用户名>/Zotero/storage
✅ 钥匙串（keyring）：Keyring
✅ MinerU Token（MINERU_API_TOKEN）：已保存
✅ 模型设置：/Users/<你的用户名>/litreader/models.toml
✅ 主笔·主用：DeepSeek / deepseek-flash  Key DEEPSEEK_API_KEY：已保存
...
➖ 模板库（只读）：<你的库路径>/模板库（不存在：只用内置模板）
✅ 模板登记：~/Library/Application Support/litreader/templates（快照 #0，可用主模板 0，待审 0，锁 free） → 首次精读或 litreader templates refresh 时登记
```

`doctor` 不写文件、不上传、不调用任何模型。
如果“Zotero 附件目录”是 ❌（你把 Zotero 数据放在别处），见第 10 节。

---

## 6.5 图形界面（不想用终端时，可选）

图形界面和终端用的是**同一套程序、同一份 models.toml 和估算校准记录**：在界面里改的模型设置，终端里 `models list` 也能看到，反过来也一样。界面同样只写 `litreader/` 文件夹（或你在基础设置里选的笔记文件夹），Zotero 只读。

**第一次安装界面组件（只需做一次，大约下载 100 MB）：**

1. 打开“终端”（启动台里搜“终端”）。
2. 复制下面两行，粘贴到终端里，按回车：

```zsh
cd ~/litreader
./.venv/bin/python -m pip install -e ".[mac,gui]"
```

3. 最后一行出现 `Successfully installed ... PySide6 ...`（或 `Requirement already satisfied`）就装好了。

**打开界面（以后每次都这样）：**

```zsh
cd ~/litreader
./.venv/bin/litreader gui
```

- 会弹出 Litreader 窗口。**用界面期间不要关掉这个终端窗口**（关掉终端，界面也会跟着关）。
- 退出：按 **⌘Q**，或菜单 **Litreader → 退出**。正在精读时退出会先问你，确认后安全停止（不会写半截笔记）。
- 如果终端显示 `还没有安装图形界面组件`，回到上面第 2 步再装一次。
- 收到新版本（例如界面改版）后：按第 2 节解压覆盖，再重新打开 `./.venv/bin/litreader gui` 即可，不用重装界面组件。

**界面里怎么用：**

1. **主页**：在中间的大输入框里输入和终端一样的一句话，例如 `精读zotero中的步态运动学，并将精读笔记存入obsidian中`，按回车或右边的 ↑。
2. 自动跳到**精读流程**页，上方 5 步：选择论文 → 费用确认 → 解析与精读 → 主题文件夹 → 完成。
   - 需要你决定时，中间卡片会显示“需要你决定”和几个按钮（和终端里输入的序号 / 回车 / y、n 一一对应），点按钮即可；带“回车”的是默认选项。
   - 费用确认每篇都会出现：表格列出每个模型的预计 tokens 和费用，点 **[y] 继续精读** 才会上传 PDF、调用模型；点 **[n] 取消** 什么都不上传。
   - 主题文件夹：可以点建议（回车 / b / c）、点已有文件夹的序号，或在下面输入框里直接写新名字。
   - 下方“实时日志”和终端里显示的文字一样，排查时可以整段复制发给我。
   - 随时可以点左下角 **取消精读**。
3. 完成后点 **查看结果 →**：结果页显示笔记路径、实际用量和估算对比、简版预览；**打开笔记** 会用默认程序打开 .md，**在访达中显示** 会定位到文件。完整排版（图片、页码链接、折叠块）请在 Obsidian 里看。
4. **模型设置**：每个角色（主笔 / 看图 / 交叉核对）1 个主用 + 最多 3 个备用。
   - “厂商”下拉框可选：OpenAI（ChatGPT）、Google Gemini、Anthropic Claude、MiniMax 中国站、MiniMax 国际站、DeepSeek、自定义 / 中转站。选厂商会自动填官方 Base URL（可以改）；选“自定义 / 中转站”要自己填中转站给你的地址。
   - API Key 填进去点 **保存**，Key 只存进 Mac 的“钥匙串”，界面和 models.toml 里都不会出现明文；留空保存 = 保留原来的 Key。
   - **测试连接** 会真的发一条很短的请求（花极少的钱），确认 Key 和模型名可用。
   - 关于 Claude：Claude Code 是一个命令行工具，不是 API；这里用的是 Anthropic API（它官方提供的 OpenAI 兼容地址），Key 在 Anthropic 控制台申请。
5. **基础设置**：深浅色（默认跟随系统）、头像、系统通知开关。
   - 头像：点 **更换头像…**（或直接点左上角头像），选一张 png / jpg / webp 图片，拖动和缩放选好范围后确定。程序只在 `~/Library/Application Support/litreader/gui/` 保存一份 256×256 的副本，原图不动。**恢复默认** 回到 “L” 图标。
   - 通知：窗口不在最前面时，需要你决定 / 精读完成 / 出错时会发系统通知。第一次 macOS 可能会问是否允许，之后可在“系统设置 → 通知”里修改。
   - **Zotero 一键检测**：点 **一键检测 Zotero**。程序只读取 Zotero 的配置文件，检查数据目录（`zotero.sqlite`、`storage/`），再访问一次 `http://localhost:23119/api/`。它不会修改 Zotero 的任何设置。
     - 显示“找到数据目录”和“本地接口可用”：说明一切正常。
     - 显示“本地接口未开启”：按卡片里的步骤操作：Zotero 设置 → 高级 → 勾选「允许此计算机上的其他应用程序与 Zotero 通讯」，然后点 **重新检测**。
     - 显示“Zotero 没有运行”：先打开 Zotero，再点 **重新检测**。
     - 显示“没找到数据目录”：在 Zotero 设置 → 高级 里看“数据目录”是哪个文件夹，再点 **手动选择数据目录…** 选中它。
     - 如果检测结果和 config.local.toml 不一样，会列出要改的行。点 **保存到 config.local.toml**，确认后才会写入，原文件会先备份成 `config.local.toml.bak-时间`。新设置从下一次精读开始生效。这个功能和终端里的 `litreader setup zotero` 是同一套逻辑。
   - **解析器 Token**：MinerU 和百度飞桨（PaddleOCR）各占一行。点 **获取 Token ↗** 会打开官网的 Token 页面，复制 Token 后粘贴到输入框，点 **保存**。
     - Token 只存进钥匙串（名称是 MINERU_API_TOKEN、PADDLE_API_KEY），和终端里的 `litreader key set` 共用。
     - 界面不会显示 Token 的内容，只显示“已保存”或“未保存”。
     - 粘贴新的 Token 再点保存，就会替换旧的。
6. **模板库 & 项目库**（只读）：
   - “模板库”标签：左边列出所有模板（★ = 默认主模板），点一个，右边显示它的章节预览、适用类型和版本。放入或改了模板后点右上角 **刷新模板库**（等于终端里的 `templates refresh`，模板文件本身只读）。
   - “项目库”标签：列出你的课题档案（★ = 默认课题），右边按模块显示每一项内容和状态（已确认 / 待确认 / 未定）。
   - 这一版只能查看；新建、修改、批准模板和课题，继续用终端命令（见 7.1、7.2）。

**更新程序后**：按第 2 节解压新的 zip 覆盖即可，界面组件不用重装；只有说明里写了“需要重装界面组件”时再执行一次上面的安装命令。

> **2026-10-19 这一版需要重装一次界面组件**：新增 pyobjc-framework-Cocoa（只在 Mac 上安装），用来把程序坞里的图标换成 “L”。请执行上面那条 `pip install -e ".[mac,gui]"`。
>
> 不装也能打开界面，只是程序坞里会继续显示 Python 的火箭图标。
>
> 因为现在是从终端启动、还没有打包成 .app，所以有两点限制：
> - 程序坞里鼠标悬停时显示的名字仍然是 “Python”。
> - 退出程序后，程序坞里的图标会变回火箭。
>
> 菜单栏左上角通常会显示 “Litreader”。

**界面打不开时：**

| 现象 | 处理 |
|---|---|
| `还没有安装图形界面组件` | 执行上面的安装命令 |
| `zsh: no such file or directory: ./.venv/bin/litreader` | 先 `cd ~/litreader`；还不行就重新执行第 4 节安装脚本 |
| 主页顶部出现黄色提示“请先按《Mac 运行指南》完成安装” | 在终端运行 `./.venv/bin/litreader doctor`，把输出发给我 |
| 一直停在某一步不动 | 看“实时日志”最后几行；点“取消精读”，把日志复制发给我 |

---

## 6.6 更新到新版本（以 1.0.3 为例）

从 0.4.0 开始，安装包的名字带版本号：`litreader-0.4.0.zip`。这样「下载」文件夹里就不会再出现 `litreader (1).zip`，也不会解压到旧的那个。

在「终端」里一行一行复制运行：

```
cd ~
ls -lt ~/Downloads/ | grep -i litreader
```

第二条会列出下载文件夹里所有 litreader 文件，最新的在最上面，确认里面有 `litreader-1.0.3.zip`。然后：

```
unzip -o -q ~/Downloads/litreader-1.0.3.zip
grep '^version' ~/litreader/pyproject.toml
```

最后一条应显示 `version = "1.0.3"`，说明新版本已经覆盖进去了。接着重装一次组件，再打开界面：

```
cd ~/litreader
./.venv/bin/python -m pip install -e ".[mac,gui]"
./.venv/bin/litreader gui
```

重装那一步 1.0.0–1.0.3 **可以不做**（没有新增依赖；做一次也无妨，会刷新版本号与许可证信息）。0.5.0 及更早升级上来的必须做过一次（0.5.0 新增了 Mac 通知组件）。以后的更新如果没写「需要重装」，只做 unzip 和最后一条就行。

怎么确认装对了：侧边栏左下角显示 `Litreader v1.0.3`，旁边有 💬 按钮（关于与反馈）；「基础设置」最下面有「关于与反馈」卡片。

覆盖只会替换程序文件，`.venv`、`config.local.toml`、`models.toml` 和钥匙串里的 key 都不会动。

## 6.7 做成真正的 Mac 应用 Litreader.app（可选，0.5.0 起）

不想每次在终端里运行 `litreader gui` 的话，可以在你的 Mac 上把它打包成 `Litreader.app`（名字、程序坞图标、通知都是 Litreader 自己的）。这一步只在 Mac 上能做；开发这边是 Linux，**没有办法实际验证打包结果**，第一次请按下面步骤做，并把出错信息发给我。

```
cd ~/litreader
./scripts/build_app.sh
```

脚本会做这几件事：
1. 往 `.venv` 里装打包工具 PyInstaller（只用于打包）；
2. 用「L」图标生成 `build/Litreader.icns`；
3. 打包成 `dist/Litreader.app`，应用标识（CFBundleIdentifier）为 `io.github.litreader.app`，并打印出标识和版本号；
4. 做一个本机「临时签名」（不涉及 Apple ID，不上传任何东西）。

为什么用 PyInstaller 而不用 py2app：PyInstaller 自带 PySide6 的打包规则，Qt 的插件会被放进 `.app` 里正确的位置（方便签名）；py2app 打包 PySide6 需要手工补很多规则。

打开方式：在「访达」里找到 `~/litreader/dist/Litreader.app`，**第一次右键 → 打开**（本地构建没有经过苹果公证，直接双击会被拦）。可以把它拖进「应用程序」文件夹。

注意：
- 应用不包含你的配置和 key。它和终端里的 `litreader gui` 一样读取 `~/litreader/config.local.toml`、`models.toml` 和钥匙串（服务名 litreader）。第一次读钥匙串时 macOS 可能问「Litreader 想访问钥匙串」，选「始终允许」。
- 在 `.app` 里运行时，「精读完成 / 需要你决定 / 已停止」通知走系统「通知中心」，第一次会询问是否允许通知（在「系统设置 → 通知 → Litreader」里可随时改）。在终端里运行时仍用原来的方式。
- 更新版本后需要重新运行一次 `./scripts/build_app.sh`，`.app` 不会自动更新。

## 7. 精读一篇论文（一句话指令）

**一次精读一篇。** 在终端里直接用中文说要读哪篇（题名或关键词都行，**整句放在英文双引号里**）：

```zsh
cd ~/litreader
./.venv/bin/litreader "精读zotero中的步态运动学，并将精读笔记存入obsidian中"
```

或者先进入**交互模式**，再一句一句输入（输入 `q` 退出）：

```zsh
./.venv/bin/litreader
```

接下来程序会一步步问你，下面是一次完整对话的样子（你输入的只有 `1`、`y` 和选模板时的一次回车）：

```
理解为：精读 Zotero 中的「步态运动学」（规则解析）
找到 2 篇候选，请选择：
  1. 轻度认知障碍与主观认知下降老年人的步态运动学及动力学特征：一项横断面研究
      2021 · 加入 Zotero：2026-09-30 · 条目 AAAA1111
  2. Gait kinematics during dual-task walking in older adults
      中文：老年人双任务行走的步态运动学
      2024 · 加入 Zotero：2026-08-02 · 条目 BBBB2222
请输入序号（q 取消）：1
—— 运行前估算（ESTIMATE，按 Zhong 2021 与 DeepGaitLab 实测比例推算，实际可能 ±40% 或更多）——
  PDF：11 页；正文约 32187 字；图约 2 个
  MinerU：将上传 PDF 副本（云端），约 11 页计入 MinerU 额度
  主笔（DeepSeek deepseek-flash）：输入 约 14,612（8,767–20,456），输出 约 8,767（5,260–12,273） tokens；费用：未填单价
  交叉核对（DeepSeek deepseek-flash）：输入 约 23,118（…），输出 约 2,090（…） tokens；费用：未填单价
  看图（MiniMax（中国站） MiniMax-M3）：输入 约 2,900（…），输出 约 500（…） tokens；费用：未填单价
  写入位置：<你的库路径>/litreader/论文库/<主题文件夹>/
是否继续？(y/n)：y
… 正在上传 PDF 副本到 MinerU 解析（可能需要几分钟）
✔ 解析完成，抽取完整度 E3
… 判定论文类型并选择模板
论文类型：横断面研究（模型判定；依据：「……一项横断面研究」p1；置信度 0.95；关键词交叉验证一致）
本次使用：单篇科研精读笔记V2.0（内置 v1） ＋ 无专业模块
  理由：通用主模板（没有适用于横断面研究的专用主模板）
  未用模块：诊断准确性与预测模型评价模块（适用于次要类型，可按 m 手动添加）
可选主模板：
  1. 单篇科研精读笔记V2.0（内置 v1） —— 通用主模板 ← 本次
  2. 单篇科研精读笔记（规范附录A九章）（内置 v1） —— 通用主模板
回车确认 / 输入序号改选主模板 / m 调整专业模块 / q 取消：
… 看图
… 主笔精读
… 交叉核对与措辞审查
主题文件夹：复用已有「认知与步态」（同为认知衰退老年人步态研究）
—— 实际用量 ——
  主笔（DeepSeek deepseek-flash）：输入 14,626，输出 8,842 tokens（估算 14,612/8,767）；费用：未填单价
  …
✅ 精读完成
   笔记：<你的库路径>/litreader/论文库/认知与步态/<中文题名>.md
```

要点：

- **候选题名自动机翻**：有多篇候选时，英文题名（而且 Zotero“其他”里没有中文题名）会在列表里多一行 `中文：……（机翻）`。所有需要翻译的题名合成**一次**小调用（默认用交叉核对模型；约 300 token，1–2 秒），列表上方显示一行用量，不需要输入 y。翻译结果保存在 `~/Library/Application Support/litreader/title_translations.json`，同一篇论文（题名不变）以后不再翻译；**从不写回 Zotero**。数字和缩写（如 12、MCI、IMU、COVID-19）必须原样保留，否则该条只显示英文；没网或调用失败时整张列表只显示英文，精读照常继续。不想要：`config.local.toml` 里 `[candidates] translate_titles = false`；想改用主笔模型：`translate_with = "主笔"`。
  ```
    （3 个英文题名已机翻：DeepSeek deepseek-flash，输入 261/输出 91 tokens，1.7 秒）
    2. Wearable IMU-Based Gait Analysis for Fall Risk Prediction in Community-Dwelling Elderly
        中文：基于可穿戴IMU的步态分析用于社区居住老年人跌倒风险预测（机翻）
  ```
- **找不到** → 直接停止，什么都不做。**有多篇** → 列出编号（题名、中文译名〔如果你在 Zotero“其他”(Extra) 里写了 `titleTranslation: …`〕、年份、加入 Zotero 的日期），你输入序号；输入 `q` 取消。一个条目有多个 PDF 时也会让你选。
- **运行前估算**：在上传和调用任何模型**之前**显示。这是按实测比例（2026-10-17 用 DeepGaitLab 的真实用量重新校准）推算的**估算**；只有在 5.5 里填了单价才显示费用。输入 `n` → 不上传、不调用模型、不写任何文件。
- 输入 `y` 就表示**同意把 PDF 副本上传到 MinerU**。同一篇论文第二次运行会显示“已有解析缓存，不上传”。
- **主题文件夹**：程序会看你 `论文库/` 下已有的主题文件夹（不含 `_阅读版本`、`_证据档案`、`_图表` 等系统文件夹），有相近的就直接复用；如果建议**新建**，会先问你：

  ```
  建议新建主题文件夹「老年步态力学」（无相近的已有文件夹）
  也可以改用已有文件夹：
    1. 认知与步态
    2. 跌倒风险
  回车 = 新建「老年步态力学」 / 序号改用已有 / 直接输入其他新名称 / q 取消：
  ```
  直接**回车**（或 `y`）= 按建议新建。
- **选模板**（解析之后、主笔之前）：程序先判断论文类型（随机对照试验、横断面、诊断准确性、系统综述、方法学/AI……）。判断依据必须是原文里逐字找得到的一句话，否则置信度记 0；你在 Zotero 里给条目加了类型标签（如 `随机对照试验`、`横断面研究`、`type:cohort`）时直接用标签，不调用模型。然后选一份主模板＋若干专业模块：
  - 直接**回车** = 用推荐的；输入标着“← 本次”的那个**序号**也等于确认；输入**其他序号** = 改用别的主模板；输入 **`m`** = 增减专业模块（RCT/干预、诊断准确性与预测模型、系统综述/Meta、方法学/技术/AI）；`q` = 取消（不调用主笔模型、不写笔记）。
  - 类型不确定或两个模板一样合适时，程序**不会替你随便选**，会要求你输入序号。
  - 也可以在一句话里直接指定：`litreader "用规范附录A模板精读zotero中的步态运动学，并将精读笔记存入obsidian中"`。
  - 内置两份主模板：**单篇科研精读笔记V2.0**（默认，十章，就是你确认过的样稿版式）和**规范附录A九章**（章节标题逐字照规范附录 A）。想以后默认用九章版：`./.venv/bin/litreader templates prefer main.spec_appendix_a`。
  - 无论用哪份模板，PAPER/INFERENCE/UNKNOWN 标注、逐字核对、页码链接、真实原图、你的批注保护区都由程序强制保留，模板删不掉。
- 如果你说的话程序没看懂，它会问你“要让模型帮忙理解这句话吗？”，输入 `y` 才会调用模型（一次很小的调用）。
- 一句话里说“批量/全部/这几篇”会被拒绝：目前只支持一次一篇。
- **抽取完整度**：解析后显示 E0–E3。没有正文的页面会逐页说明类型（如“第 8 页 整页图（无正文）”）；整页图、表格、公式、图注、参考文献、附录/补充材料页都算已读到。真正什么都没读到的页（空白或只有页眉页脚）：如果不在方法/结果部分、且不超过全文 20%，照常精读，这些页记为 **UNKNOWN 页面**列在证据档案里；否则停止并写明是哪几页。排查用：`./.venv/bin/litreader inspect-parse`（最近一次）或 `inspect-parse <Zotero条目Key>`，只读本机缓存，打印每页各类块的数量，不上传、不含论文内容。
- 只想在 Zotero 里查一下有没有某篇（不精读）：`./.venv/bin/litreader find "关键词"`。

### 7.1 模板库（可选）

想用自己的版式时，在 Obsidian 库根目录建一个 `模板库/` 文件夹，放入模板 `.md` 文件。**程序只读这个文件夹，从不修改里面的文件**；登记信息保存在 `~/Library/Application Support/litreader/templates/`。

```zsh
./.venv/bin/litreader templates export main.general     # 把内置模板导出到 litreader/模板导出/ 作参考
./.venv/bin/litreader templates lint ~/某个模板.md       # 只检查，不登记
./.venv/bin/litreader "刷新模板库"                        # 或 templates refresh：登记新放入/改过的模板（不会跑论文）
./.venv/bin/litreader templates list                     # 看有哪些模板、哪些“待审”
./.venv/bin/litreader templates show <模板ID>            # 详情：章节、会送给模型的（已清洗）提示、版本历史
```

- 复制内置模板修改时，请把 front matter 里的 `id` 改成 `user.` 开头的新名字（如 `user.my_rct`）、改 `title`。
- 模板里出现“忽略规则”、命令、网址、“没有就编”等内容，或缺少 front matter（角色/适用类型），会被标为**待审**，不会被自动选用；你看过后：`templates approve <ID>@<版本>`（缺角色时加 `--role main --types any`），或 `templates reject <ID>@<版本>`。
- AI 帮你起草：`templates draft 示例笔记.md --id user.my_style --title 我的版式`（调用一次交叉核对模型，结果为待审）。
- 改了模板文件 = 新版本，旧版本保留；用旧版：`templates rollback <ID>`（或 `templates pin <ID>@1`，取消用 `unpin`）。已生成的笔记永远不变。
- 设首选：`templates prefer <ID>`（默认主模板）、`templates prefer <ID> --for rct`（某论文类型的首选）；清除加 `--clear`。停用 / 启用：`templates disable|enable <ID>`。
- 想每次都自己选模板：在 `config.local.toml` 的 `[templates]` 里写 `selection = "ask"`。

### 7.2 科研项目库（可选：让笔记多一节“与我的课题的关系”）

**第一次精读时**（选好论文之后、估算之前）程序只问一次：

```
你目前研究的课题是什么？可以只说题目、给出开题报告/研究方案文件的路径（可以把文件拖进终端），或直接回车跳过（使用通用精读）。
>
```

- **直接回车** = 以后不再问，这次及以后都用通用精读（随时可用 `新建课题：…` 或 `litreader project init` 再建）。
- **输入题目** = 只建一个“题目已确认、其余未定”的最小档案，不调用模型。
- **把开题报告 / 研究方案拖进终端**（`.docx`、`.pdf`、`.md`、`.txt`、`.pptx`；`.doc/.ppt/.wps` 请先另存为新格式）= 本地读取、显示段数和字数，**先问你是否同意把全文发给 DeepSeek 提取**，再问是否同意在 `litreader/科研项目库/` 建档。提取出的每一条都带原文逐字引文和位置（段/页/幻灯片）；对不上原文的降为“AI 归纳”。然后只让你核对 **5 项**（下面是一个**虚构示例课题**，不是谁的真实课题）：

```
从《示例 开题报告.md》（6 段）提取到 6 条候选（明确写出 5，AI 归纳 1；文件内冲突 0）
请确认以下关键信息（其余条目保存为“待确认”，可稍后用 litreader project review 逐条处理）：
  1. 题目：【示例课题·虚构，仅供演示】社区老年人日常步行速度与认知功能的关系（段1，文件明确写出）
  2. 科学问题：日常步行速度是否与认知功能评分相关（段2，文件明确写出）
  3. 研究对象：60 岁以上社区老年人（段3，文件明确写出）
  4. 已定方法：横断面研究（段4，文件明确写出）
  5. 重要指标：日常步行速度（段5，文件明确写出）
回车 = 确认以上无冲突的项；输入序号 = 修改该项 / 标为未定；s = 先存草稿不确认；q = 放弃导入：
```

  文件里自相矛盾的项（例如两处写了不同的科学问题）不会被回车一并确认，要你输入序号选。AI 归纳的内容永远不会被自动当成“已确认”。

**之后每次精读**：终端会显示本次用哪个课题，估算里多一行（这就是发送前的同意，输入 `y` 即同意一并发送）：

```
课题：《…》v1（默认课题；已确认 5 项，未定 24 项）
  项目视角（含在主笔内）：将发送课题《…》v1 摘要（约 426 字，已确认 5 项）＋本篇分析要点；输入 约 3,489，输出 约 1,300 tokens（未实测，估算）
```

- 只发送 `当前项目摘要.md` 里的内容（只含“已确认”项，其余写“未定”），**所见即所发**。主笔分析论文时**看不到**课题内容；论文事实写完后，再单独调用一次“项目视角”，结果只能标 INFERENCE，不改任何论文事实。
- 笔记里的位置：V2.0 模板在“八、最值得借鉴”末尾加一小节“与当前课题的关联”，三分钟速览里多一行“当前课题价值”；规范附录 A 模板放在“七、与当前科研项目的关系”。YAML 里记录 `project_id / project_version / project_snapshot_sha256`。
- 项目视角失败时笔记照常生成，该节显示“项目视角未生成”。
- 一句话里可以临时指定：`…，本次不关联课题`（这次不用课题，默认不变）；`用《另一个课题》的角度精读…`（这次用另一个课题）。有多个课题又没设默认时会让你选，输入 `1*` = 选 1 并设为默认。

**课题档案在哪里**：`<你的库路径>/litreader/科研项目库/<课题名>/`，包括 `课题档案.md`（可以直接在 Obsidian 里改；下次运行会先列出你的改动请你确认）、`当前项目摘要.md`、`来源记录.md`、`待确认建议.md`、`历史版本/v001.md…`、`导入草稿/`。历史版本只增不改；每篇笔记永远指向当时那一版。

```zsh
./.venv/bin/litreader project list                        # 所有课题与默认课题
./.venv/bin/litreader project show [课题]                 # 当前版本各项及状态
./.venv/bin/litreader project init --title "题目"         # 新建（也可说：新建课题：题目）
./.venv/bin/litreader project import ~/方案v2.docx         # 导入新版文件（会显示与上一版的差异，逐项确认）
./.venv/bin/litreader project review                      # 逐条处理“待确认”
./.venv/bin/litreader project set 核心问题 "……"            # 改一项（也可说：把课题的核心问题改为……）
./.venv/bin/litreader project set 题目 "新题目"            # 改题目（也可说：把课题的题目改为新题目）；文件夹名不变
./.venv/bin/litreader project undecide 统计方法            # 标为未定
./.venv/bin/litreader project diff --v1 1 --v2 2          # 两个版本的差异
./.venv/bin/litreader project revert 1                    # 以第 1 版内容生成新版本（旧版本保留）
./.venv/bin/litreader project switch <课题>               # 换默认课题（也可说：把默认课题切换为……）
./.venv/bin/litreader project sync                        # 读入你在 Obsidian 里的手动修改（也可说：刷新课题档案）
./.venv/bin/litreader project archive|unarchive <课题>     # 归档（文件全部保留）
./.venv/bin/litreader project summary                     # 看下次会发送给模型的摘要
./.venv/bin/litreader project recover                     # 登记中断/校验失败时的审计恢复
./.venv/bin/litreader templates prefer <模板ID> --project <课题>   # 这个课题优先用某个主模板
```

**写入位置**：笔记写在 `<你的库路径>/litreader/论文库/` 里，不碰库里其他文件夹。旧版配置里的 `dry_run_dir = "_litreader_试运行"` 仍然有效；想换到新位置，在「基础设置 → Obsidian → 笔记文件夹」修改，已有笔记不会被移动。

**精读会写哪些文件（全部在 `litreader/` 里）：**

```
litreader/
├── 科研项目库/                                     ← 只有你建了课题档案才会出现
│   ├── 00-当前科研项目.md
│   └── <课题名>/课题档案.md、当前项目摘要.md、来源记录.md、待确认建议.md、历史版本/、导入草稿/
└── 论文库/
    ├── <主题文件夹>/<中文题名>.md                    ← 阅读笔记
    ├── _证据档案/<条目Key>/<中文题名>——证据档案.md
    └── _图表/<条目Key>/Fig1-1.jpg …                ← MinerU 裁出的原图
```

再跑一次同一篇论文**不会覆盖**旧文件，而是新建“——姓+年份”后缀的新文件，例如“——Shin2026”（中文/日文/韩文作者用全名，例如“——王鸿涛2026”；没有作者时只有年份；第三次再加条目 Key，例如“——Shin2026GBLV2NPH”；三个名字都被占用时程序停止，不会覆盖）。

### 7.2 更新程序后重新生成同一篇（不覆盖旧笔记）

1. 按第 2 节“更新到新版本”解压新的 `litreader.zip`。
2. 照常运行同一句精读指令，选同一篇。估算里会显示“已有解析缓存，不上传”（MinerU 不再计费）；主笔、看图、交叉核对**会重新调用**（会产生新的模型费用，输入 `y` 前请看估算）。
3. 如果程序发现 Zotero 与 PDF 的第一作者不一致，会问你文件名后缀用哪位作者：PDF 顺序是从 PDF 原文作者行逐字找到的 → 回车 = PDF 顺序，`z` = Zotero 顺序；PDF 顺序只来自模型读取、未通过逐字核对的作者串 → 回车 = Zotero 顺序，`p` = PDF 顺序（未核实）；笔记里作者一栏会写成 UNKNOWN 并提示你去 Zotero 核对。
   - **核对后如果 PDF 是对的（Zotero 里的作者顺序录错了），请你自己在 Zotero 里改**：选中条目 → 右侧“信息”栏 → 在要调整的作者那一行用作者旁的菜单“上移/移到顶部”（或直接拖动）。litreader **从不修改 Zotero**，也不会替你改；改好后再精读一次，冲突提示就不会出现。
4. 新笔记写在同一个主题文件夹里，文件名多一个“——姓+年份”后缀（如“——Shin2026”）；旧笔记和旧证据档案原样保留，可以并排比较。

---

## 8. 程序具体做了什么（安全说明）

1. **找 PDF**：向 Zotero 本地接口读取条目信息，并用 `…/items/<附件Key>/file/view/url` 得到 PDF 在硬盘上的位置（通常是 `~/Zotero/storage/<附件Key>/文件名.pdf`）；拿不到时按 `config.local.toml` 里 `[zotero] data_dir` 拼出路径。
2. **保护原文件**：先算原 PDF 的哈希（指纹），复制一份到 `~/Library/Application Support/litreader/jobs/` 再处理；结束时再算一次，**指纹变了会立即停止报错**。原 PDF 从不被打开写入。
3. **上传**：只有你在估算后输入 `y`，才把**副本**上传到 MinerU（mineru.net，云端）解析；解析结果存在上面的 jobs 文件夹。
4. **AI 分析**：解析出的文字发给 DeepSeek；图片（如配置了视觉模型）发给 MiniMax。每条事实都要逐字对上原文和页码才能标 PAPER，读图结论还要与正文交叉核对，冲突会以 `[!warning] 冲突` 显示。
5. **模板**：模板文件只当数据读，不执行其中任何命令、网址或“指令”；送给模型的只有清洗过的章节标题和写作提示，并且明确声明“与程序规则冲突时以程序规则为准”。每次运行开始时固定模板版本（运行中你改了模板也不会混用），笔记属性里的 `litreader:` 记录 `template_id`，证据档案的「笔记元数据（程序用）」记录 `template_id / template_version / template_sha256`。
6. **课题档案**：导入的开题报告只在本机读取（读前读后核对指纹，不改原文件）；只有你同意后才把全文发给 DeepSeek 提取，文件里的“指令”、网址只当文字保存，不执行。每次精读冻结一个课题版本，只发送“当前项目摘要”（已确认项）。登记信息在 `~/Library/Application Support/litreader/projects/`。
7. **写入**：只经“独占创建”写入 `litreader/` 内；遇到符号链接、`..` 等路径技巧一律拒绝。
8. **Key**：只从钥匙串（或环境变量）读取，从不打印、不写文件。

---

## 9. 在 Obsidian 里检查（请帮我核对）

打开 Obsidian，左侧找到 `litreader/论文库/<主题文件夹>/` 下的笔记，逐项看：

| # | 检查项 | 结果（✅/❌/备注） |
|---|---|---|
| 1 | 标题是中文，下面一行斜体英文原题 | |
| 2 | 图片能显示，且图号、所在页与 PDF 一致 | |
| 3 | 表格、彩色提示框（callout）显示正常 | |
| 4 | 随便点 3 个不同位置的页码链接（方法、关键数字、图表），Zotero 打开**这个附件**并跳到**对应页** | |
| 5 | “证据档案”链接能打开 | |
| 6 | 笔记开头 YAML 里有 `template_id`（本次用的模板）和 `study_type`，与终端显示一致 | |
| 6b | （建了课题时）“与当前课题的关联”一节：矩阵里“本篇已证实内容”与上文一致；“当前项目已确认情况”只出现你确认过的内容，其余写“未定” | |
| 7 | 阅读评分：满意 / 需修改 / 不接受 | |

> 页码链接 `?page=N` 指 PDF 文件里的**第 N 页（物理页，从封面算第 1 页）**，不是论文版面上印的页码。很多预印本第 1 页是封面，印刷页码会比物理页小 1 或更多；Zotero 顶部的页码框也可能显示印刷页码。核对时请以“点链接后实际打开的那一页”为准。

第 4 项全部正确后，才可以把 `config.local.toml` 里的 `link_mechanism_verified = false` 改成 `true`（之前所有链接都显示“未验证”）。

---

### 9.1 图号或图片与 PDF 对不上时（只读排查，不上传、不花钱）

例：笔记把“第 21 页、无图注”的 3 张小图放进了某张图，但 PDF 那页没有这些图。

0. 先按第 2 节“更新到新版本”解压新的 `litreader.zip`（`--page` 是新功能，旧版本会报 `unrecognized arguments: --page`）。
1. 打开“终端”，进入程序目录：
   ```bash
   cd ~/litreader
   ```
2. 列出这几页的全部块（把 `GBLV2NPH` 换成该论文的 Zotero 条目 Key，页码换成你要查的页，前后各多看一页）：
   ```bash
   ./.venv/bin/litreader inspect-parse GBLV2NPH --page 20-22
   ```
   每页会显示：MinerU 的块类型（image/chart/table/equation…）、位置 bbox（0–1000）、占页面百分比、裁剪图片文件的完整路径和像素大小、被归入笔记里的哪张图、像图注的段落（如“图 7. …”，含类型和位置），以及这一页的“页码/页眉/页脚文字”（能看出印刷页码和物理页差几页）。
3. 想亲眼看某个裁剪图，复制上一步输出里“图片：”后面的路径：
   ```bash
   open "/把/路径/粘贴在这里.jpg"
   ```
4. 如果还需要看这几页正文的开头（判断图注是否被识别成正文），加 `--text`（这一步的输出含论文内容，只在你愿意时发给我）：
   ```bash
   ./.venv/bin/litreader inspect-parse GBLV2NPH --page 21 --text
   ```
5. 把第 2 步的终端输出（截图或复制）发给我，并告诉我：在 Zotero 里点笔记中的 `p21` 链接，打开的那一页上有没有这 3 张图；如果没有，它们实际在第几页、是什么（公式、表格、标志、某张图的一部分）。

这个命令只读本机缓存：不上传、不调用模型、不写任何文件。

**笔记里出现“图注请在 Zotero 原页阅读”**：说明 MinerU 的解析结果里根本没有这段图注（例：DeepGaitLab 第 21 页图 7，`--text` 和 discarded 列表里都找不到）。这是解析器遗漏，程序不会转录或猜测图注和图号；请点提示里的页码链接，在 Zotero 中直接读图注。图注藏在分图标签后面（如 “(C) 图4. …”）的情况程序已能自动识别。

## 10. 常见问题

| 现象 | 原因 / 解决 |
|---|---|
| `command not found: brew` | 第 1.2 步没完成，或没执行“加入路径”那两行；关掉终端重开再试 `brew --version` |
| `❌ 没找到 Python 3.11+` | 执行 `brew install python@3.12`，再重跑 `zsh scripts/mac_install.sh` |
| `Python 3.9.6` / 语法错误 | 用了系统自带 Python。始终用 `./.venv/bin/litreader`，不要用 `python3 …` |
| Zotero 本地接口 ❌ / `Forbidden` | Zotero 没开，或第 3 步没勾选 |
| 浏览器打开 `localhost:23119/api/…` 显示 Forbidden | 正常：Zotero 拒绝浏览器访问，只用终端 `curl` 测试 |
| Zotero 附件目录 ❌ | 你的 Zotero 数据不在 `~/Zotero`。Zotero → 设置 → 高级 → 文件和文件夹 → “数据存储位置”，把路径填到 `config.local.toml` 的 `[zotero] data_dir` |
| 指令里的题名带英文双引号 | 整句外面用英文双引号，句子里面改用中文引号“ ”或《》 |
| `⛔ 已停止：抽取完整度 E0/E1` | E0 = 扫描件/加密，没有可用文字。E1 = 有页面解析器什么都没读到（只有页眉页脚或空白），而且这些页在“方法/结果”部分、或超过全文 20%；提示会逐页写明。整页图、表格、公式、图注、参考文献、附录页**不算**缺页。请运行 `./.venv/bin/litreader inspect-parse` 把输出发给我（只有每页的块数统计，不含论文内容）。MinerU 结果已缓存，修好后重跑**不会重新上传** |
| 钥匙串弹窗 | 点“始终允许” |
| 不想读图 / 没有 MiniMax Key | `./.venv/bin/litreader models remove 看图 1`（图的“主要发现”会标“未经视觉模型看图”） |
| `models test` 提示“可能不支持 JSON 模式” | 在 `models.toml` 该模型下面加一行 `json_mode = false` |
| 提示“模型设置仍在旧格式” | `./.venv/bin/litreader models migrate` |
| 模板显示“待审” | 模板里有可疑内容或缺 front matter：`templates show <ID>` 看原因，确认没问题再 `templates approve <ID>@<版本>` |
| “模板登记正被另一个 litreader 使用” | 另一个终端还在运行；等它结束。精读本身会继续用上一次完整的模板登记 |
| 候选列表显示“题名机翻失败，只显示英文” | 没网、Key 未设置或模型暂时不可用；不影响精读。关掉：`[candidates] translate_titles = false` |
| 你的旧 `config.local.toml` 里没有 `[candidates]` | 不用改：默认开启机翻；需要关闭时自己加上 `[candidates]` 和 `translate_titles = false` 两行 |
| 课题题目里不想被识别为文件路径 | 文件路径要以 `/`、`~` 或 `./` 开头；题目直接输入即可 |
| “课题登记上次中断” / “校验失败” | `./.venv/bin/litreader project recover`（同模板登记，残留移到 `quarantine/`，不删除） |
| “模板登记上次中断” / “校验失败” | 运行 `./.venv/bin/litreader templates recover`：先列出要做的事，确认后把残留移到 `quarantine/`（不删除任何文件） |

**编辑 `config.local.toml`：**

```zsh
open -e ~/litreader/config.local.toml
```

在“文本编辑”里，先点菜单 **编辑 → 替换 → 取消勾选“智能引号”**，否则英文引号 `"` 会变成弯引号导致出错。改完 `⌘ + S` 保存。

---

## 11. 撤销 / 清理

- **删除精读结果**：在访达或 Obsidian 里删除库中的 `litreader` 文件夹即可，库里其他文件从未被改动。
- **删除解析缓存与回执**：

  ```zsh
  open ~/Library/Application\ Support/litreader
  ```
  在打开的窗口里删除 `jobs` 文件夹（模板登记在 `templates` 文件夹，删除后下次会重新登记，固定/首选设置会丢失）。
- **删除题名机翻缓存**：删除上面窗口里的 `title_translations.json`（下次有英文候选时会重新翻译）。
- **删除课题档案**：删除 `litreader/科研项目库/` 和上面窗口里的 `projects` 文件夹（两者一起删；只删其一时运行 `litreader project recover --from-vault` 可从库里的历史版本重建登记）。
- **删除钥匙串里的 Key**（每个 Key 一条）：

  ```zsh
  security delete-generic-password -s litreader -a DEEPSEEK_API_KEY
  ```
- **卸载程序**：删除 `~/litreader` 文件夹。Homebrew 和 Python 3.12 可以保留。

---

## 12. 跑完后发给我

1. 第 7 步终端里的全部输出（截图或复制文字；里面没有 Key）。
2. 第 9 节核对表的结果；以及 `models test` 的输出。
3. 回执文件（第 7 步显示的 `receipt-….json`，里面有 PDF 前后指纹与 token 用量，不含 Key）。

> 目前这些真实环境检查（Zotero 跳页、Obsidian 显示、Mac 钥匙串）在开发环境里都**没有运行过**（NOT_RUN），要以你这次的结果为准。
