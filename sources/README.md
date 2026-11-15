# 原文来源

## 伤寒论辑义

- 文件：`shanghan_juyi.txt`
- 本地原件：`C:\Users\longa\Desktop\倪海厦医学\伤寒论辑义--.txt`
- 编码：GB18030
- 用途：抽取伤寒论方名、组成、煎服法、校注和行号。
- 抽取结果：`data/formulas.json`。

## 神农本草经

- 文件：`data/herbs.json`
- 本地原件：`C:\Users\longa\Desktop\倪海厦医学\【倪海厦注解版】倪海厦注神农本草经(清晰版).pdf`
- 结构：每条保留 `page_start`、`page_end`、分段原文和倪注条目。
- 原件不复制进仓库；仓库只保留结构化读取结果与来源说明。

剂量和炮制均按来源文本保存。页面不会自动把古方剂量换算成现代克数。

## 倪海厦伤寒、金匮与视频文稿

- `ni_shanghan_pages.jsonl`：伤寒论 PDF 的页级文本，含倪注讲解。
- `ni_jinkui_pages.jsonl`：金匮要略 PDF 的页级文本，含倪注讲解。
- `ni_jinkui_transcript.jsonl`：金匮要略视频同步文稿。
- `jinkui_recipes_source.json`：金匮方剂抽取快照，保留原始组成、煎服法、页码和倪注。

逐方校对时，先看对应书本页，再对照视频文稿；找不到的文稿明确标为缺失。
