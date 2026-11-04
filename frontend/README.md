# 医师研究工作台（工程验证版）

Vue 3 + TypeScript + Element Plus，所有数据来自同源真实 `/api`。无静态病例/结果接口替身。

```powershell
npm.cmd ci
npm.cmd test
npm.cmd run build
```

构建命令先执行 `vue-tsc --noEmit`，输出 `dist/` 由 FastAPI 服务。开发时运行 `npm.cmd run dev`；Vite 将 `/api` 代理至 `http://127.0.0.1:8765`。通常直接打开后端 `http://127.0.0.1:8765` 使用已构建工作台。

首次接诊事实为空。独立“加载合成示例”按钮只载入标为算法演示的事实草稿；保存、分析及医生决定均需明确操作。规则、页校核、模型补充和加密备份遵循 `../docs/API.md`。

模型密钥只通过写请求传给本地后端；界面只接收 `has_key/key_hint`，不存入 localStorage。原文、规则审计及模型文字只通过 Vue 转义插值显示。模型只有 `completed && validated === true` 才显示为已校验补充。

前端测试使用 Node 24 内建 TypeScript 支持与测试运行器；HTTP边界测试运行真实本机HTTP服务器。依赖版本固定在 package.json 和 package-lock.json。
