# 公共模型转发服务

先从目标服务器用自己的账号做一次真实的最小 Codex 请求，确认得到
`response.completed`。登录成功、健康检查成功和假令牌的 401 都不能代替此验证。

1. 安装 Node.js 20+，将 `scripts/codex_relay_worker.mjs` 与
   `scripts/run_public_codex_relay.mjs` 放入 `/opt/tcm-codex-relay/scripts/`，文件由 root
   所有、普通用户可读。不要复制任何 `data/`、本机配置或用户凭证。
2. 将 `tcm-codex-relay.service` 放入 `/etc/systemd/system/`，运行
   `systemctl daemon-reload` 和 `systemctl enable --now tcm-codex-relay`。
   服务使用临时低权限用户，只监听 `127.0.0.1:18769`，开机自动运行。
3. 将 `nginx-rate-limits.conf` 放入 `/etc/nginx/conf.d/tcm-relay-limits.conf`，
   将 `nginx-locations.conf` 放入 `/etc/nginx/tcm-relay-locations.conf`，
   在已有的 HTTPS `server` 块添加
   `include /etc/nginx/tcm-relay-locations.conf;`。先备份原配置并执行
   `nginx -t`，通过后用 `systemctl reload nginx` 平滑加载。
   两份 nginx 文件需同时更新；本次共享限流区改名为 `_v2`，避免改变 key 表达式
   后复用旧共享内存区导致平滑 reload 失败。
   不替换现有监听端口、域名证书或其他服务配置。
4. 验证公网 HTTPS、真实 GitHub Pages Origin 的预检、未允许来源/目标拒绝、
   真实账号的模型连通测试、真实问诊逐步返回和取消请求，再发布前端默认地址。
   小请求成功不能代替长请求测试；响应开始后再发生的错误也必须能被前端识别。

现有 Reality 转发链没有传递客户端 IP，因此示例限制的是全站总量：
普通请求每秒 2 次（允许 40 次短时突发），nginx 最多同时接纳 24 个普通连接。
Node 在读取请求体前也限制最多接纳 24 个请求；读取完成后，最多 16 个生成请求
和 4 个控制请求同时运行，其余请求立即返回 503 与 `Retry-After`。
控制名额仅用于白名单中的设备码、令牌交换/刷新和精确的 Codex 模型列表请求；
分类复用 Worker 的完整请求校验，缺失模型 Bearer 头、无效头部/请求体或超时
字段的请求不能占用控制名额。账号凭证的实际有效性仍由官方上游判定。
生成名额占满时，控制请求仍有独立容量。OPTIONS 预检不占这些名额，也不计入
nginx 的请求/连接限额；无请求体的健康检查仍可使用。
CORS 不是身份认证。这些是全站容量保护，没有提供每位用户的公平配额；扩大
访问量前，需要保留真实客户端 IP 的入口及相应限流策略。

服务在内存中转发每位访客自己的凭证和问诊内容，不落盘，不记录请求体、
回复体或认证头。请求上限 2 MiB，回复上限 4 MiB，生成请求按网页设置等待
（最长 600 秒，另留 2 秒供浏览器先取消；旧客户端默认 600 秒）；控制接口最多
等待 30 秒，另留 2 秒取消余量，避免登录/模型列表长时间占住保留名额。
Codex SSE 按完整事件逐步转发，遇到结束事件停止读取，不等待上游关闭连接。
响应开始后的超时、断流或超限无法改写已经发送的 HTTP 200，会追加固定的
`event: error` 错误事件；前端必须识别它，不能把已有的半段回答当作成功完成。
浏览器仍独立保存各自账号和病例，服务器不会给访客使用项目所有者的账号。

服务器本机可执行 `curl --fail --silent http://127.0.0.1:18769/status` 查看容量、
当前已接纳/生成/控制数量、完整 HTTP 应答数量以及固定类别的失败计数。
`completed` 统计已接纳请求的完整 HTTP 传输，`http_4xx`/`http_5xx` 统计这些
应答的状态类别；HTTP 200 中的模型流错误需同时看 `worker` 的失败计数。
`terminal_cancel_failed` 仅表示已完成回复后的上游清理失败，不推翻已完成回答。
`worker.streams_started` 为开始转发的 SSE 数，`first_frame_count` 为已返回首个
完整事件的数量；`first_frame_total_ms / first_frame_count`（数量大于零时）和
`first_frame_max_ms` 可查看首事件平均与最长等待。这里统计事件就绪，不保证首个
事件已经包含可见正文。
计数仅保存在进程内存，重启归零，不包含提示词、回复、凭证、账号/请求 ID、
地址或单次请求的时间记录。此接口拒绝 Origin 请求、不提供 CORS，nginx 的公网
`/status` 路径固定返回 404，不要再为它添加代理入口。

更新或停止服务前，先查看 `/status` 的 `active`；当前停机流程最多等待 10 秒，
超过后会取消在途请求，故应在生成/控制请求均为空时安排维护。
确认域名证书自动续期以及续期后的 nginx reload。撤回时先恢复原 nginx 配置，
`nginx -t` 通过后 reload，再停用这个独立 systemd 服务；不操作现有代理服务。
