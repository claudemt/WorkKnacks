# AI 润色

AI 润色使用本机 Claude Code CLI，不经过 WorkKnacks 的第三方 API。

## 使用

1. 在项目工作台选择文本类文档
2. 点击“AI 润色”
3. 选择 Skill：
   - 翻译稿润色
   - 转写稿整理
   - 解析稿校对
4. 在对话窗口中输入要求并运行
5. 满意后保存结果

保存会覆盖当前文件。多轮对话记录保存在当前项目的 `.workknacks/ai-logs/`。

需要先安装并配置 `claude` 命令。
