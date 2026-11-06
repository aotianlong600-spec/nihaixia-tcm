# Web, Android and Codex login Implementation Plan

> Codex controls scope; Claude Code implements/reviews scoped tasks through orchestrator.

**Goal:** 在PC中心模式交付认证网页、可安装Android壳和Codex授权通道，并同步公开源码。

**Architecture:** 共享FastAPI/SQLite与Vue页面；一个后端进程loopback HTTP及LAN TLS；应用访问权限与模型OAuth独立；不重复医学引擎。

**Spec:** docs/WEB_ANDROID_V4.md。

## Global constraints

不修改医学原件/病例；不读其它软件认证；不在Git发布数据/令牌/私钥；不绕过TLS；缓存放D；不加医师审核；不假装模型额度/医学效果验证。

## Review focus

远端未认证可读、Host/Origin/CSRF绕过、本机bootstrap被伪造、取消后存令牌/并发刷新回退、Android证书/导航泄漏和公开历史敏感文件。

## Tasks

- [x] 接入Claude Code治理、GitHub建仓与代码扫描（已建公开仓库；禁止资料入仓）。
- [x] app/access.py + tests/test_access.py：先红后绿访问密码、会话、远端边界及两端同库。
- [x] app/lan.py + run/start-lan脚本：私CA/证书及双监听、明确用户初始化；TLS回归。
- [x] OAuth Node/Python桥与model路由：login/status/cancel/logout/refresh、固定provider流；合成HTTP/协议回归。
- [x] Vue登录与通道设置、移动适配，保留临床约束和历史；前端回归。
- [x] android原生壳、URL/证书安全与D盘构建脚本、真实assembleDebug产物。
- [ ] 独立review/测试、GitHub公开内容/远端核对、可复现交付；真实认证与手机实机未验则明示。
