# Android 原生 WebView 壳（0.4）

## 目标与边界

这是现有 Vue 工作台的 Android 原生 Java 容器，包名 `com.nihaixia.workbench`，不复制医学算法，也不内置原件、病例、模型密钥或令牌。电脑是唯一后端，必须在线；手机只通过 HTTPS 访问局域网 PC。断网时显示电脑不可达，不把旧缓存当当前分析。

技术基线：JDK 17、Android SDK Platform 35、AGP 8.7.3、Gradle 8.9、minSdk 26、compile/target 35。

## 源码结构

- `android/app/src/main/java/com/nihaixia/workbench/MainActivity.java`：地址输入、WebView、返回导航、外部链接、错误提示。
- `android/app/src/main/java/com/nihaixia/workbench/UrlPolicy.java`：唯一允许的服务器根地址策略。
- `android/app/src/test/java/com/nihaixia/workbench/UrlPolicyTest.java`：先写的 JUnit4 策略测试。
- `android/app/src/main/res/xml/network_security_config.xml`：只信任构建时生成的 `@raw/ca_cert`，无系统/用户/调试信任。
- `android/app/src/main/res/xml/data_extraction_rules.xml`：禁用云备份和换机迁移。
- `android/gradle/wrapper/gradle-wrapper.properties`：固定Gradle 8.9分发包及官方SHA256。
- `scripts/build_android.ps1`：校验公钥 CA、生成 raw 资源、配置项目内缓存并构建/测试。

## 构建

前提：电脑已安装 JDK 17 和 Android SDK Platform 35（含 build-tools）；不要求修改全局环境变量。脚本不会接受 SDK 许可，缺失组件请先在 Android Studio 中安装并手动确认许可。

仓库包含已核对官方SHA256的Gradle 8.9 wrapper JAR，构建脚本验证JAR和分发包校验和。初次构建联网获取官方Gradle、Google/Maven依赖。

```powershell
cd <仓库根目录>
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_android.ps1 `
  -CaCertificate D:\path\to\public-ca.pem `
  -SdkDirectory D:\android `
  -JavaHome D:\android\jdk-17
```

可选 `-OutputDirectory D:\somewhere` 会把 APK 复制为 `nihaixia-workbench-debug.apk`。脚本依次执行 `testDebugUnitTest assembleDebug`，并打印 APK 路径和 SHA-256。

脚本只接受 PEM `CERTIFICATE` 公钥块：拒绝任何 `PRIVATE KEY`、多个证书块、非 CA 证书（要求 `basicConstraints CA=true`）和已过期 CA。生成的 `android/app/src/main/res/raw/ca_cert.pem` 被 gitignore，不能提交。

缓存位置（均在 D 盘项目内，进程级环境变量，不改全局）：

- `android/.gradle-user-home`（`GRADLE_USER_HOME`）
- `android/.android-user-home`（`ANDROID_USER_HOME`）
- `android/.gradle`、`android/app/build`（Gradle/AGP 项目输出）

若 Gradle wrapper JAR 缺失，脚本会停止并给出明确提示，不会下载或执行来源不明的二进制。

## CA 配对与安装

1. 在电脑生成/轮换本机 CA，并用该 CA 签发包含当前局域网 IP 的服务器叶证书；私钥只留在 gitignored 的 `data/` 运行配置中，不能进入 APK 或仓库。
2. 仅把 **CA 公钥 PEM** 交给 `-CaCertificate` 构建 APK。手机不安装系统根证书，也不开启“信任用户证书”。
3. 安装 `app-debug.apk`（`adb install -r ...` 或文件管理器；不同包名不覆盖旧项目）。
4. APK 内只信任该 CA；服务器证书必须由同一 CA 签发、未过期、包含当前 LAN IP 的 SAN。CA 变化或地址变化后需重新构建/安装；同一 CA 下轮换叶证书无需重建。Android 正常执行主机名验证，应用不会忽略证书错误。

## 使用

首次启动输入形如 `https://192.168.1.20:8766` 的地址并连接。只接受：

- 显式 `https://`；
- 10/8、172.16/12、192.168/16 的规范点分十进制 IPv4；
- 显式 1–65535 端口；
- 根地址（可带一个结尾 `/`）。

拒绝 localhost、主机名、公共/保留地址、前导零/十六进制/缩写等异常 IPv4、账号信息、路径、查询、片段、缺失或越界端口。通过的地址会规范化为 `https://IPv4:port`，这是应用 SharedPreferences 中唯一保存的连接数据。

访问密码在电脑网页登录页输入，应用不保存密码、令牌或患者资料。返回键优先回退 WebView 历史；标题栏菜单可“重新加载”或“更改地址”。更改地址会清除 WebView 缓存、Cookie、表单与本地 Web 存储，并删除保存的服务器根地址。正常退出也会清理会话和缓存。

电脑必须在线；网络失败显示“无法连接电脑”，TLS/证书失败显示“安全连接失败”并停止加载。应用不会调用 `SslErrorHandler.proceed()`。若 Windows 防火墙阻止入站，只允许专用网络/本地子网访问该端口，不要开放公网。

## 链接、下载和登录

- 同源 HTTPS 页面在当前 WebView 内加载，启用 JavaScript 和同源 Cookie 以复用 Vue 会话；关闭 DOM 存储、第三方 Cookie 和离线缓存。
- 外部 HTTPS 链接（包括设备码 OpenAI 登录）交给系统浏览器，仅传递 URL，不转发应用 Cookie 或请求头；其他协议（`http`、`javascript`、`intent`、`file`、`content` 等）被拒绝。
- `target=_blank`/`window.open` 由隐藏的、禁用网络加载的临时 WebView 截获后按上述规则路由，不创建可导航的未受控窗口。
- 下载（含 blob/备份/原件）不落地：显示“请在电脑下载”的明确提示。需要下载或查看原件时请使用电脑网页。
- 源文本和图片正常显示；图片仍由同一后端提供。

## 隐私与安全不变量

- 无 JavaScript 原生桥（不调用 `addJavascriptInterface`）。
- WebView 只信任配对 CA，不信任公共 CA；Vue 生产构建的脚本、样式和图片应由电脑同源提供，不依赖公共 CDN。
- 无明文流量：`usesCleartextTraffic=false`、网络安全配置 `cleartextTrafficPermitted=false`，WebView 混合内容为 `NEVER_ALLOW`。
- 禁止 `file://`/`content://` 访问、通用文件 URL 访问、应用备份和换机迁移。
- 不保存/恢复 WebView 历史、页面状态或表单；缓存模式为 `LOAD_NO_CACHE`，退出和换址时清理 Cookie/WebStorage/缓存。
- 仅 `INTERNET` 权限；无存储、定位、相机、麦克风权限。
- 源码公开，但实际 LAN 地址、CA/叶证书私钥、访问密码、OAuth/API 凭据、患者数据和构建缓存不得提交。

## 测试与已知限制

JVM 单测覆盖 `UrlPolicy` 的私有网段、异常 IPv4、账号/路径/查询/片段、端口边界和同源判断。构建脚本会运行：

```powershell
android\gradlew.bat -p android testDebugUnitTest
android\gradlew.bat -p android assembleDebug
```

工作者没有命令权限；控制器已实际执行编译、11项JVM单测及assembleDebug，并核对APK内CA公钥。APK安装和真机运行未执行。尚未在真实手机上测试以下内容：自签 CA 配对、Android 各厂商 WebView 差异、软键盘/旋转/返回手势、设备码登录跳转浏览器、blob 下载提示的触发覆盖率、后台恢复后的会话行为。若页面通过非 anchor、非标准方式触发 blob 下载且不经过 `DownloadListener`，可能没有提示；仍不会在手机落盘。

医学映射与软件通过与否无关；真实模型访问仍需用户授权和联网验证。
