<p align="center">
  <img src="https://img.shields.io/badge/Windows-支持-blue?logo=windows" alt="Windows">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
  <img src="https://img.shields.io/badge/文档处理-一站式工具-orange" alt="文档处理">
</p>

<h1 align="center">🧰 WorkKnacks</h1>
<p align="center">翻译 · 转写 · 解析 · AI 润色，一个工作台全部搞定</p>

---

## 💡 为什么做这个项目？

你有没有遇到过这样的时刻：

- 收集了英文文献，为了逐行翻译、解释忙得焦头烂额
- 下载了宝藏课程，听了一遍后真正记住的寥寥无几
- 别人分享的 PDF 很想拿来直接用，却因格式问题难以下手
- 找了一堆网站，翻译、转写、解析都做完了，结果却是一堆语法和排版错误
  
真正消耗人的，往往不是某一个按钮，而是**文档处理链条之间的来回搬运**。

WorkKnacks 只做一件事：接入你自己的翻译、转写、文档解析 API，打开你的项目文件夹，在每个文件旁边直接提供翻译、转写、解析和 AI 润色，结果就落在原文件旁边。

这些 API 都可以申请到可观的免费额度，足够个人用户日常工作学习使用。

---

## ✨ 功能

| 功能 | 说明 |
|------|------|
| 📂 **项目工作台** | 像资源管理器一样浏览本地文件夹，随时进入或返回上级目录 |
| 🌐 **翻译** | DeepL · 腾讯 TMT · 百度翻译，支持分块和断点续传 |
| 🎙️ **会议转写** | 转写腾讯会议云录制，导出总结与逐字稿 |
| 📄 **文档解析** | MinerU 将 PDF、图片、DOCX、PPTX 转成 Markdown |
| ✨ **AI 润色** | 为翻译稿、转写稿或解析稿选用对应 Skill，本机 Claude 多轮处理 |
| 🔄 **状态恢复** | 每个项目独立保存处理状态、翻译进度和 AI 对话记录 |
| 🧹 **原地交付** | 结果直接写入源文件所在目录，无需统一输出目录 |

---

## 🚀 快速上手

```bash
pip install -r requirements.txt
python main.py
```

启动后点击“打开项目文件夹”，选择要处理的本地目录。

第一次使用某个能力时，在“配置”窗口完成对应设置：

- 翻译：默认使用 DeepL 免费额度，改用腾讯或百度翻译则需填写密钥
- 解析：默认使用 MinerU 免费额度，precise 模式需要填写 Token
- 转写：需自行将会议音视频上传到腾讯会议“录制”模块，平台会自动导出
- AI 润色：默认使用本机 Claude Agent，内置常用润色 Skill，可一键修复单独调用 API 时常见的排版和语法错误

---

## 🧭 怎么工作？

1. 打开一个项目文件夹
2. 在文档列表中找到目标文件
3. 点击右侧的“翻译 / 转写 / 解析 / AI 润色”
4. 选择供应商或 Skill
5. 处理完成后，结果直接写入源文件所在目录

---

## 🛠️ 项目结构

```text
main.py        启动入口
config/        本机配置与密钥模板
skills/        翻译、转写、解析 Skill
src/           应用代码
tests/         自动化测试
```

运行测试：

```bash
pytest -q
```

WorkKnacks 会在每个项目目录下使用 `.workknacks/` 保存工作记忆：

```text
.workknacks/
├── state.json       # 文档处理状态与输出记录
├── progress.json    # 翻译断点
└── ai-logs/         # AI 润色对话记录
```

---

## 🤝 贡献

欢迎提 Issue 和 PR！如果你有想法，欢迎来聊：

- 希望接入更多供应商的适配接口
- 希望集成更强大的 AI 润色 Skill

---

<p align="center">
  <b>如果这个项目对你有帮助，欢迎 ⭐ Star ⭐ 让更多人看到</b>
</p>
