# OAuth 登录排障说明

## 当前实际故障

原生 OAuth 流程在凭据校验成功之后失败，进程退出码为 `0xC0000409`（Windows原生进程快速失败状态）。该轮已有完整凭据返回，确认还发生了原生运行时退出崩溃。退出码本身不说明所有授权失败的原因；随后遇到的OpenAI网页403、HTML响应或网络中断应另行判断。

私有的 Node 运行时已被固定为 `24.22.2`，并包含官方修复（nodejs 61999）。请使用仓库内固定的这份运行时，不要改用系统 PATH 中的其它 Node 版本。

## 本次确认与未确认的内容

- 已确认：启动器路由可用（HTTP 200，经指定 DeepSeek provider 返回 `WORKER_OK`）。
- 已确认：全局 `settings.env` 中的 SenseNova 配置曾覆盖请求的 DeepSeek 路由；现改为仅按 worker 的 route-settings 提供私有 `APIkeyHelper` 返回值，全局 settings 权限未改动。
- 未确认：真实账号登录尚未验证通过。**不要**声称真实登录已验证。

## 容易混淆的概念

以下机制彼此不同，不能相互替代或等同：

- 浏览器回调（browser callback）
- 短设备码（short device code）
- 手动回调（manual callback）
- 请求中出现的 `request_id` / `accountId` 属于标识字段，**不是**授权码（auth code）。

## 正在独立推进的工作

- 手动回调（manual callback）支持
- 具名配置档（named config profiles）

以上两项由其它改动独立实现，本文档不声明其已完成或已验证。
