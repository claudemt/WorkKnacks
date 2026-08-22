# 配置与供应商

启动应用后，点击“配置”设置供应商凭据。

## 翻译

### DeepL

无需填写密钥。应用使用内置的 DeepL 翻译供应商。

### 腾讯 TMT

在腾讯云控制台创建 `SecretId` 和 `SecretKey`，然后在配置窗口填写：

- `TENCENT_SECRET_ID`
- `TENCENT_SECRET_KEY`

### 百度翻译

创建百度翻译应用后，在配置窗口填写：

- `BAIDU_APP_ID`
- `BAIDU_KEY`

## 文档解析

安装 MinerU CLI：

```powershell
pip install mineru-open-api
```

需要 precise 模式时填写 `MINERU_TOKEN`。没有 Token 时使用 flash 模式。

## 腾讯会议转写

在配置窗口选择一种登录方式：

- 从桌面客户端导入
- 网页扫码登录
- 手动粘贴 Cookie

转写需要账号拥有对应云录制的访问权限。

## AI 润色

安装 Claude Code CLI，并确保 `claude` 命令可以在终端执行。配置窗口会显示检测结果。

## 配置文件

本工具的密钥和腾讯会议登录态保存在仓库的 `config/` 中：

- `config/.env.local`
- `config/wemeet_cookies.json`

这些文件不会提交到 Git。
