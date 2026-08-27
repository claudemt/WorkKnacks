---
name: polish
description: Conservatively repair MinerU LaTeX or academic translations while preserving scientific meaning, equations, numbers, citations and the author's level of certainty.
allowed-tools: Read,Write,Edit,Glob,Grep
---
# Polish

用于**解析后整理**与**翻译后校对**。

## 总原则

1. 忠实优先：不改变事实、结论强度、因果、假设与不确定性。
2. 数学与引用是硬约束：方程、变量、上下标、正负号、数值、单位、`label/ref/cite`、图表编号保持一致。
3. 最小改动、只做可证实的修复；无法从原文或上下文确认的歧义保留原样并做最短标记，不凭常识补造。

## 解析后整理

对照 MinerU/OCR 高频噪音逐项检查，规则以规范为准：
- 页眉页脚重复、跨页断裂、双栏乱序、断词连字符、OCR 字符误识别、跨页表格、公式乱行、图片路径不统一。
- 保持原章节、公式、图表、论证顺序；图片只指向当前解析目录的 `figures/`；References/Bibliography 不改写。

## 翻译后校对

对照原文和译文检查：漏译、反译、指代错位、否定词丢失；正比/反比、增减趋势、正负号、量纲、单位、数值；`exact/approximate/asymptotic/perturbative/fitted/inferred/measured` 等证据强度是否被改动；正文引出公式→公式→解释是否连贯；同一物理量、材料、方法和现象术语是否前后一致。

## 输出方式

对已有文件直接做最小、可审计的编辑。遇到无法确认的 OCR/翻译歧义，保留原信息并做最短标记，不自行选一个看似合理的答案。
