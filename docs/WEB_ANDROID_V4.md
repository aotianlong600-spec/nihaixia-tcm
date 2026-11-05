# 网页与安卓共用工作台0.4：执行规范

2026-11-06，用户确认：继续现有个人项目；GitHub仓库nihaixia-tcm，最新选择公开源码；PC作中心供局域网网页和安卓使用；扶摇指Zhou-Shilin/Aether；启用Claude Code工作者，Codex控制范围与验收。

## 实现选择

复用现有Vue业务页面与FastAPI/SQLite/原文决策图，安卓采用独立包名的Java原生WebView容器，沿用已安装JDK17/Android35，不另造一套医学算法或更换全栈框架。APK不捆绑原件、病例、模型密钥或模型令牌。电脑须在线；首版不做离线病历与云端部署。

后端一个进程共享数据、会话和OAuth刷新锁：默认本机HTTP127.0.0.1:8765；显式局域网模式在同进程另提供TLS8766，局域网需要访问密码。手机只走HTTPS，APK信任本机生成CA公钥，绝不忽略SSL错误；生成叶证书包含当前LAN地址，私钥和运行配置只在gitignored data。电脑本机仍用loopback网页，避免要求修改系统根证书。脚本不自动开公网或修改系统防火墙；Windows如阻止入站，用户仅放行专用网络/本地子网。

## 账号与模型通道

应用访问会话和OpenAI授权分开。应用先由本机设置访问密码，盐化PBKDF2保护，仅本机可首次设置，登录限速，成功后轮换会话/CSRF，HttpOnly+SameSiteStrict，HTTPS会话Secure；医疗API未认证不可访问。未配置密码时本机个人模式兼容，远端无权读库。

保留API Key通道，新增Codex/ChatGPT授权通道，参考扶摇使用已安装Pi SDK的OAuth与openai-codex文本provider，不启用编码Agent工具。支持浏览器和设备码，密码只在OpenAI网页输入。仅保存本应用授权返回的凭据，Windows DPAPI；不复制~/.codex/auth.json或其它软件登录态。刷新在后端单进程锁内原子保存，手机只持应用会话，永不收到refresh/access token。登录状态与模型目录不是账户额度或权限证明，真实访问需用户授权后验证。网络错误不回显敏感供应商响应。

OAuth桥op login/refresh，前端仅看到auth_url/device_code/受限prompt/安全状态；原始凭据帧仅供父进程加密保存。模型推理子进程只收到显式access token，固定Codex服务端点，禁止环境凭据、工具调用、跨端点重定向、未完成输出。目录方和原文版本/断言、未知/反证/冲突和历史冻结保持原样。

## 交付和边界

生成网页生产构建及本机CA绑定的Android调试APK；不同包名不覆盖旧天纪项目。原文图像阅读和问诊使用共同后端，管理原件与大备份优先在电脑网页进行；移动端遇不支持的下载须明确提示，不静默假成功。断网提示电脑不可达，不把旧缓存处方当当前分析。

GitHub只发布通过扫描的代码、通用文档与许可数据；原件、病历、SQLite、API/OAuth凭据、TLS私钥、Android签名材料、实际LAN地址、agent运行日志、构建缓存不进仓库。保留本机原件与数据库、旧记录、备份格式，模型密钥仍不进入备份；访问密码与TLS证书是独立运行配置，重新部署要重新设置/配对。

## 最小接口和范围

新增app/access.py、app/lan.py、app/model_oauth.py、ai-bridge/oauth.mjs及相关测试；修改main/model/APIclient/Settings/App与run/start/stop/build脚本；新增android/原生壳、CI和文档。所有运行缓存、Gradle/Node缓存放D盘。Claude只改指定范围，不读data或任何账号文件，完成后由Codex检查diff、scope、secret-scan和测试。

验收：未授权访问被拒、只允许本机初始化、登录后轮换cookie/CSRF、过期/退出/限速、双端读写同库及revision冲突；TLS链/主机名验证、APK不忽略证书/不带密钥；OAuth开始/轮询/取消/失败/刷新并发/超时、凭据不回前端、不读其它authstore；推理成功/断流/取消/跨域泄漏防护；既有218后端24前端9桥接回归；公开仓库内容扫描及实际远端验证。医学映射仍仅首组，软件通过不代表医学有效性。
