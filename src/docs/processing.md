# 解析与翻译

解析和翻译是进阶流程。PDF 先解析成结构化 LaTeX，再翻译 LaTeX；这样数学、物理论文中的公式、图、引用和推导关系更不容易被破坏。

## 第一次使用：配置 MinerU 和翻译服务

主界面点击 **配置**。这个窗口只管理两类必要运行服务。

### MinerU

正式 PDF 解析使用 MinerU 标准 `extract`，需要安装 `mineru-open-api` 并完成鉴权。两种方式任选一种：

- 在 **配置** 中填写 MinerU Token；
- 或在终端执行 `mineru-open-api auth`，让 MinerU CLI 自己保存登录状态。

GUI 保存的 Token 位于本机：

```text
config/.env.local
```

发布包提供 `config/.env.local.example` 作为模板。常用字段：

```env
DEFAULT_PROVIDER_PARSE=mineru
MINERU_TOKEN=
```

如果完整论文超过 flash 接口限制，WorkKnacks 不会拿整篇 PDF 去走轻量接口；正式解析始终使用标准 `extract`。只有扫描件元数据复核时才可能把前几页先在本地切成小 PDF 做轻量识别。

### 翻译服务

**配置 → 默认服务** 可以选择：

- **DeepL**：当前内置通道无需填写 API Key；
- **本地翻译 API**：填写本地 HTTP 地址和超时；
- **腾讯 TMT**：填写 `SecretId`、`SecretKey`；
- **百度翻译**：填写 `APP ID`、`Key`。

也可以直接编辑 `config/.env.local`：

```env
DEFAULT_PROVIDER_TRANSLATE=deepl_oneshot

LOCAL_TRANSLATE_ENDPOINT=http://127.0.0.1:8000/translate
LOCAL_TRANSLATE_TIMEOUT=60

TENCENT_SECRET_ID=
TENCENT_SECRET_KEY=

BAIDU_APP_ID=
BAIDU_KEY=
```

保存后不需要重启程序。API 密钥只保存在本机配置中，不进入项目 AI 上下文。

## PDF：先解析，再翻译

点击 PDF 的 **翻译** 后，窗口里有两个明确的按钮：**解析** 和 **开始翻译**。

- 第一次处理论文时，先点 **解析**。
- 已有解析稿时，直接点 **开始翻译**。
- 如果尚未解析就点“开始翻译”，程序只会提醒你先解析，**不会偷偷自动触发 MinerU**。
- 想重新跑 MinerU，也可以再次点“解析”，确认后更新原解析结果。

解析产物直接放在文献文件夹：

```text
parsed/<附件名>/
├── main.tex
├── main.pdf
└── figures/
```

MinerU 完成后会自动进行一轮 AI 解析校对，重点修复双栏阅读顺序、跨页断裂、重复页眉页脚、OCR 符号、LaTeX 语法、表格和图片路径；不会根据模型常识补写原文没有的内容。

## 数学/物理论文的翻译

PDF 翻译以 `main.tex` 为输入。程序先保护公式、LaTeX 命令、引用、数值、单位、DOI/arXiv 和参考文献，再按科学语义分段。

特别是下面这种推导关系会尽量连续处理：

```text
正文引出 → 展示公式 → where / therefore / respectively / 在某个极限下的解释
```

这样可以减少把“公式”和“公式为什么成立”拆散后造成的误译。译后还会自动做一次忠实原文的校对，检查正负号、正比/反比、数量级、近似条件和术语一致性。

译文放在：

```text
translations/
```

Markdown、TXT、TeX 等文本文件不需要 MinerU，可以直接翻译。
