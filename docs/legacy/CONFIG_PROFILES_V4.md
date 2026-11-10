# 模型配置选择、删除与手动授权：执行约定

仅改模型连接配置，不改医学资料、病历或辨证规则。保留现有 /api/model/config 兼容接口。配置名称、通道、模型及外发选择分别保存，选择配置后只影响新请求，正在运行的请求不改道。

## 配置 API

- GET /api/model/profiles → {items: Profile[], active_id: string|null}。
- POST /api/model/profiles，PUT /api/model/profiles/{id}：输入现有 ModelConfig 全部字段加 name（1–80字符），api_key可选；响应保存的公开 Profile。新建不自动切换。
- POST /api/model/profiles/{id}/select → 当前公开 ModelConfig（另含profile_id/profile_name）。
- DELETE /api/model/profiles/{id} → {deleted_id,active_id}。删除配置及其专属API密钥，取消该配置的未完成任务；删除当前项后active_id=null，服务停止接收新模型请求，不自动选其他项。
- 原GET/PUT /api/model/config：仍读写当前配置；无当前项时PUT可创建并启用为当前项。返回字段新增profile_id/profile_name，其余兼容。

Profile={id,name,auth_mode,base_url,model,enabled,allow_external,allow_evidence,has_key}。所有接口继续受现有会话/CSRF保护，不能返回密钥或密文。ID由服务器生成，不得成为任意路径输入。Codex地址仍固定为官方端点。

## 保存与迁移

data/model-profiles.json保存version=1、revision、active_id、items，采用锁和唯一临时文件原子替换。首次读取时若有旧model-config.json则导入为id=legacy、name=原有配置，保持所有设置。legacy密钥仍用原model-secret.dpapi，不复制、不解密迁移；其他API密钥放data/model-keys/{profile_id}-{key_ref}.dpapi（私有引用随配置原子提交）。原配置文件保留，不因空列表或删除当前项重新导入。读损坏数据应报错，不静默清空。

Codex配置共用当前一份Codex账号授权（codex-secret.dpapi）；本次不增加多账号管理。删除配置不等于退出共享账号，界面必须说明；“退出Codex授权”仍是独立操作。保留已有凭据和既有备份格式。

发起模型任务时固定profile_id与配置快照；凭据获取/任务注册、配置更改/删除、OAuth退出均通过同一模型任务guard协调。快照构建期间若配置revision变化，返回409要求重新发送。不能把删除/切换前的旧输入发到另一提供方。历史结果保留原模型和配置身份。

## 前端

配置列表可选中编辑、命名新增、保存、设为当前、删除；编辑项与当前生效项分别显示。删除需用户确认，取消不执行请求；不影响问诊记录和医学原件。既有Codex模型下拉/自定义ID和已保存配置卡片继续工作。

## 手动授权回填

POST /api/model/codex/login/{login_id}/code 输入 {value: string}，返回{status: submitted}。仅接受当前未完成browser登录。用户只把当前授权成功/失败跳转后的完整localhost:1455/auth/callback网址填回工作台；不在聊天里发送。验证scheme/host/port/path、恰好一个code/state，state须与当前auth_url一致；不接受request_id、账号ID或旧会话链接。

Python CallbackInput位于model_oauth.py，OAuthManager.submit负责校验及私有stdin帧{type:authorization_input,value}；Node等待的manual_code prompt接收该值，由SDK按同一次PKCE交换。前端输入不入storage、日志或备份，提交成功/取消/离开设置后清空。设备码另有复制按钮，方向是工作台→OpenAI设备授权页。Backend配置工作者不修改model_oauth.py；父控制器补挂这一个回填路由。

## 验收

旧配置/密钥保留、创建不自动激活、两个API密钥隔离、空密钥更新保留、切换只影响新请求、删除当前不自动改道、删除取消对应任务、配置变更与发起请求竞态、路径穿越和损坏文件拒绝、无凭据泄露。手动回填须拒绝旧state/错误网址/已取消任务，真实令牌不进入测试或输出。
