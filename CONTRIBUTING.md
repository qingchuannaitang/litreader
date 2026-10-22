# 参与贡献 / Contributing

欢迎提 Issue 和 Pull Request（仓库地址待公开：https://github.com/qingchuannaitang/litreader）。

## 开发约定

- 开发与测试只用假数据（fakes），不调用真实付费 API；不提交任何密钥、个人论文题名或本机路径。
- 提交前运行 `python -m pytest -q` 与 `python scripts/check_no_secrets.py`。
- 内置模板必须保持逐字节不变。

## 贡献者许可声明（CLA）

本项目以 GNU AGPL-3.0-or-later 发布，版权人为 王鸿涛 (qingchuannaitang)。

向本项目提交贡献（代码、文档、图标、模板或其他内容）即表示你同意：

1. 你有权提交该贡献，且它不侵犯他人的权利；
2. 你的贡献以 AGPL-3.0-or-later 授权给所有人；
3. 同时，你授予项目作者 王鸿涛 一项永久、全球、免费、不可撤销、非独占的许可，可以使用、修改、再许可并以**任何许可证**（包括专有/商业许可证）发布你的贡献；
4. 你保留自己贡献的版权。

如果不同意以上条款，请不要提交贡献。在 Pull Request 描述中写上 "I agree to the CLA in CONTRIBUTING.md" 即视为确认。

---

By submitting a contribution you confirm you have the right to do so, license it under AGPL-3.0-or-later, and grant
the author (王鸿涛 / qingchuannaitang) a perpetual, worldwide, royalty-free, irrevocable, non-exclusive right to use,
modify, sublicense and relicense it under any terms, including proprietary ones. You keep your copyright.
