# 来源署名与开源组件说明（Attribution & Third-Party Notices）

## 1. 许可边界

- **程序代码与检索/构建脚本**：仓库中的应用程序源码（`app/`、`ai/`、`etl/`、`retrieval/`、`web/`、`scripts/`、`tests/`）按根目录 [LICENSE](LICENSE)（MIT）开放。
- **医书原文、课程讲记与原书文档（`books/`、`sources/`、`data/`）**：
  - 包含汉唐/人纪系列《针灸教程》《神农本草经》《黄帝内经·素问》《伤寒论》《金匮要略》《汉唐中医经典文章医案集》《跟诊过程》等讲解与原书资料，以及古籍辅注（《伤寒论辑义》《血证论》《石室秘录》《证因方论集要》《明清名医全书大成·徐灵胎医学全书》《黄帝外经》等）。
  - 所有医学条文、讲记摘要与原书页图仅作个人中医药学习、逐页考据与架构展示用途，保留原书及原讲者署名，**不按 MIT 协议授权再分发或商业使用**。
- **免责声明与构建版说明**：
  - 本项目当前为 **初版构建版（v0.1.0-build，持续构建与优化中）**。
  - 系统呈现的所有方剂剂量、针灸取穴、六经归属与“辨证论治”联机线索仅用于经典学习对照与条文溯源研究，**绝不能替代执业医师面对面四诊合参**。

## 2. 第三方开源依赖

- **[FastAPI](https://fastapi.tiangolo.com/)** & **[Uvicorn](https://www.uvicorn.org/)**：MIT / BSD 3-Clause（本地桌面运行服务端）。
- **[Pyodide](https://pyodide.org/)**（v0.29.3）：MPL-2.0（GitHub Pages 网页构建版内置浏览器端 Python 知识库运行时）。
- **[PDF.js](https://mozilla.github.io/pdf.js/)**（pdfjs-dist）：Apache-2.0（网页构建版按需渲染原书 PDF 扫描页对照）。
- **[OpenCC `TSCharacters.txt`](https://github.com/BYVoid/OpenCC)**：Apache-2.0（繁简对照字符表，预编译为 `retrieval/t2s_table.py`，用于跨繁简体中医文献检索归并）。
- **[pypdfium2](https://github.com/pypdfium2-team/pypdfium2)**：Apache-2.0 / BSD-3-Clause（本地服务端离线提取 PDF 文本及渲染 PNG 页图）。
- **[Pillow](https://python-pillow.org/)**：HPND / MIT-CMU（构建 GitHub Pages / PWA 静态分发包时生成应用图标）。
