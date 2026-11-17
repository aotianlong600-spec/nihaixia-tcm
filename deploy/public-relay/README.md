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
   不替换现有监听端口、域名证书或其他服务配置。
4. 验证公网 HTTPS、真实 GitHub Pages Origin 的预检、未允许来源/目标拒绝、
   真实账号的模型连通测试及取消请求，再发布前端默认地址。

现有 Reality 转发链没有传递客户端 IP，因此示例限制的是全站总量：
每秒 2 次请求（允许 40 次短时突发）、16 个同时连接。CORS 不是身份认证。
扩大访问量前，需要保留真实客户端 IP 的入口及相应限流策略。

服务在内存中转发每位访客自己的凭证和问诊内容，不落盘，不记录请求体、
回复体或认证头。请求上限 2 MiB，回复上限 4 MiB，上游总超时 95 秒；
当前版本汇集完整回复后返回，遇到 Codex 结束事件立即停止读取。
浏览器仍独立保存各自账号和病例，服务器不会给访客使用项目所有者的账号。

确认域名证书自动续期以及续期后的 nginx reload。撤回时先恢复原 nginx 配置，
`nginx -t` 通过后 reload，再停用这个独立 systemd 服务；不操作现有代理服务。
