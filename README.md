<p align="center">
  <img src="https://img.shields.io/badge/Windows-科研工作台-0078D4?logo=windows" alt="Windows">
  <img src="https://img.shields.io/badge/AI-Claude%20Code-D97757" alt="Claude Code">
  <img src="https://img.shields.io/badge/Library-Local--first-2ea44f" alt="Local">
</p>

<h1 align="center">📚 WorkKnacks</h1>
<p align="center"><b>一个基于 Zotero 的本地论文管理、解析、翻译平台</b></p>

---

## 它做什么

**1. 文献管理**

WorkKnacks 最基础的功能便是文献管理，它的数据抓取、元数据识别、命名归档和 BibTeX 导出都沿用 Zotero 的规则，所以你在 Zotero 里熟悉的习惯在这里也通用；而它与区别是：WorkKnacks 是一个操作文件夹的工具，它不会像 Zotero 那样把文献放到一个很难找到的专门的库中。

**2. 解析与翻译**

基于**免费的 MinerU api**，WorkKnacks 可以把论文解析成结构完整的 LaTeX（含图片）；基于**公开的薅 DeepL 项目**，WorkKnacks 可以把解析稿翻成中文。

**3. AI 总结润色**

WorkKnacks 集成了**Claude Code CLI**，可以使用本机的**Claude agent**，可以把当前论文的解析源码交给 AI，并使用内置 skill，从第一性原理重建问题、关键方程链、近似条件与复现路径。

WorkKnacks 更是模拟真实的 ai 对话环境，让你在 python 的 gui 中，也可以继续追问、比较文献、改笔记。解析润色、译后润色、总结、元数据复核等后台 AI 操作都进入可追溯的历史。

## 安装

```bash
pip install -r requirements.txt
python main.py
```

想要实现后两个功能，需要外部依赖：**MinerU api**、**Claude Code CLI**、**LaTeX/latexmk**。

## 🤝 贡献

欢迎提 Issue 和 PR！如果你有想法，欢迎来聊：

- 有其他的文献管理功能更需求？
- 有更好的解析、翻译拆组算法？

---

<p align="center">
  <b>如果这个项目对你有帮助，欢迎 ⭐ Star ⭐ 让更多人看到</b>
</p>