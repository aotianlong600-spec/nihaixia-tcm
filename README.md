# 倪氏本地中医工作台 0.5 · 公开源码版

离线中医库、原文溯源、方证及经方加减算法，加按需调用的云端模型。电脑版网页使用本机数据；安卓在手机内独立运行，不需要电脑开机、同一局域网或固定电脑证书配对。

## 使用

- 电脑：双击“启动离线网页.cmd”，打开 http://127.0.0.1:8767 。默认使用开源经方索引，病例保存在本机 `data/`。可在启动前把自备知识包放入 `knowledge/`。
- 新电脑：安装 Python 3.11，运行 setup.cmd，再运行启动脚本。Node为项目内固定运行时，不修改全局安装。
- 安卓：按下文构建并安装 `nihaixia-local-debug.apk`。首次启动会把随构建提供的知识包装入设备私有目录。
- AI：在“模型与数据”新增/选择配置，填写自己的兼容API地址和密钥，或使用Codex设备码授权；启用外发后点击发送。模型选择和思考档位在问诊页可直接应用。

云模型目前支持OpenAI兼容Chat Completions及Codex文本通道。自定义HTTPS地址和模型ID可以配置；账号权限、网络和供应商额度以实际请求为准。安卓不复制电脑的登录令牌。

## 数据

本仓库随源码提供原有开源经方索引 `app/resources/open_formula_library.json`。原件、私有知识数据库、病例及内置私有知识包的 APK 不随公库分发。`knowledge/` 用于存放本地生成或自备的知识包。

设备运行时会把知识事务性装入本机 SQLite，并独立保存记录。重复启动不覆盖用户本地数据库修订。各端病例分别保存在设备上。

同一知识包的原件、字节哈希、物理页、印刷页和原文锚点跨端保持一致。查阅原件和执行来源图规则需要包内包含相应资料。源量与个人日剂量分开呈现。

问诊调用云端时发送本次问诊单、最近最多12条对话、候选及图谱、选取书证文字。不会自动上传整份PDF文件；自由文本尚无自动脱敏保证。

## 数据库维护

可直接编辑、迁移、更新、建索引或重建本地数据库。修订内容时同步维护版本、引用和完整性清单。

允许引入外部数据，包括其他典籍、公开数据集、开源项目医学条目及中医参考资料，不限于当前已选书目。外部资料只需标记“第三方”，不强制逐条填写出处、作者、版本、原文定位或许可字段，已有元数据可保留。第三方数据可用于检索、知识整理和算法建设，不冒称倪师观点；AI推演单独标记。既有倪师原文溯源保留，仅标“第三方”的条目不能据此逐条回查原文。

第三方资料导入后合并进入同一中医库，统一参与检索、辨证、方证鉴别和经方加减；以倪海厦学术体系为主线、第三方为补充。保留“第三方”分类；存在差异时保留差异，不静默覆盖倪氏内容或拼成新的倪氏规则。

```powershell
python scripts/export_knowledge_pack.py --data-dir data --destination knowledge-new
python scripts/export_knowledge_pack.py --verify knowledge-new
```

导出目录须为新目录，避免半成品覆盖现有包。校验通过后可将新包放入 `knowledge/` 供本机使用。

## 构建安卓

需要 JDK 17、Android SDK 35、Python 3.11。先将自备知识包放入 `knowledge/`，或运行下列第一条命令生成空包。空包带开源经方索引，语料和来源图均为空。已有自备包时跳过生成命令。

```powershell
python scripts/create_empty_knowledge_pack.py
python scripts/export_portable_schemas.py
cd frontend
npm ci --ignore-scripts
npm run build
cd ..
./scripts/build_android_offline.ps1 -JavaHome <JDK17目录> -SdkDirectory D:/android -BuildPython <Python3.11路径> -OutputDirectory <输出目录>
```

安卓内置共享Python核心（Chaquopy），不移植另一套医学判断；原生层处理系统HTTPS、Keystore与PDF页面。构建/签名缓存在项目.cache内，不提交Git。保留本机debug签名文件，便于升级安装保留记录。

## 验证与范围

公开 CI 使用空包校验导出格式，运行 Python、前端、模型桥及安卓 JVM 测试，并编译安卓 APK。设备仪器测试中的原件与来源图场景需要对应的本地资料包。药物风险库和全书语义映射仍在完善。

本版交付离线核心。旧电脑中心版说明归档在 `docs/legacy/`。
