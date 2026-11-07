# 离线中医工作台界面

Vue 3、TypeScript 和 Element Plus。桌面网页使用本机 `/api`，安卓使用应用内桥接接口。

```powershell
npm.cmd ci --ignore-scripts
npm.cmd test
npm.cmd run build
```

生产构建输出到 `dist/`。运行项目根目录的 `start.cmd` 后，可在浏览器打开 http://127.0.0.1:8767。开发时执行 `npm.cmd run dev`，Vite 会将 `/api` 请求转给同一端口。
