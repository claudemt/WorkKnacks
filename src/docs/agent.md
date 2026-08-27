# AI 工作台

右侧 AI 是**整个项目的研究工作台**。它不是单篇论文的临时聊天框：手工对话和解析校对、译后校对、总结、元数据 AI 复核都会出现在同一份项目历史中。

## 第一次使用

WorkKnacks 调用本机 Claude Code CLI。先在终端确认：

```bash
claude --version
```

如果尚未登录，先按 Claude Code 自己的流程完成登录。WorkKnacks 不保存 Claude 账号密码。

项目 AI 的工作目录始终是当前项目根目录。点击文件右侧 **AI** 会把该文件作为上下文放进输入框；也可以自己输入：

```text
@file "相对路径"
```

Claude 可以自行读取项目里的普通文本文件和已经解析好的 `parsed/<附件>/main.tex`，因此聊天提示词不需要重复塞入整篇论文或 Skill 内容。

## 自动任务也会留下会话

下面这些自动动作都会进入右侧历史：

- MinerU 解析后的 AI 校对；
- 翻译后的对照校对；
- 论文总结；
- 元数据 AI 复核；
- 你自己发起的对话。

会话标题由 AI 自动生成。刷新项目后仍可继续旧会话，也能看到自动发送过的提示词和当时的答复。

## 写回文件时发生什么

Claude 不直接修改真实项目。WorkKnacks 先在 `.workknacks/tmp/` 的安全工作副本中让 Claude 编辑，再生成 diff；你确认后才写回真实文件，并在 `.workknacks/backups/` 留下可撤销备份。

`.env.local`、密钥、Cookie、Git 内部文件和 `.workknacks/` 自身状态不会作为普通项目文件暴露给 AI。

## 默认研究经验

程序内置两个全局 Skill：

- `summarize`：强调第一性原理、关键方程链、近似、尺度、物理图像和最小复现路线；
- `polish`：用于解析和翻译后的保守校对，优先忠实原文和数学结构。

普通用户不需要管理它们。

## 高级个性化：新增全局 Skill

如果你确实有稳定的个人研究方法，可以手工增加：

```text
~/.workknacks/skills/<名称>/SKILL.md
```

例如：

```text
~/.workknacks/skills/referee/SKILL.md
```

最小内容：

```markdown
---
name: referee
description: 审阅物理论文，重点检查推导、控制变量、不确定度和可复现性。
allowed-tools: Read,Glob,Grep
---

先核对核心结论和证据，再检查关键推导、近似、控制实验、误差和可复现性。
输出区分致命问题、重要问题和可选改进。
```

下一次 Agent 任务会自动发现这个 Skill。GUI 不提供 Skill 管理入口，避免把低频配置长期占在科研界面上。

如果确实需要调整模型、effort、turn 上限或预算，可编辑：

```text
<项目>/.workknacks/state/agent.json
```

这些都是低频高级选项；正常使用保持默认即可。
