# 文档解析

文档解析使用 MinerU，将 PDF、图片、DOCX 或 PPTX 转换为 Markdown。解析结果直接写入源文件所在目录。

## 安装

```powershell
pip install mineru-open-api
```

在“配置”窗口填写 `MINERU_TOKEN`。没有 Token 时使用 flash 模式；配置 Token 后使用 precise 模式。

## 使用

1. 在项目工作台找到 PDF、图片或 Office 文档
2. 点击“解析”
3. 选择 MinerU
4. 开始处理

MinerU 生成的 Markdown 和可选 PDF 结果由供应商写入源文件所在目录。原始输入文件不会移动。
