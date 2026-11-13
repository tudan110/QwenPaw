# 智观鉴权改动核验报告

日期：2026-11-13。代码基线：`e1a24d1e3`，分支 `dev`。

结论：联邦认证方案的主方向可保留，当前实现仍有三个应按 P0 关闭的凭据读取入口，以及两个影响业务和退出流程的 P1 问题。现有鉴权测试通过不足以确认考试环境可以恢复开放；需要先补齐实际路由和文件出口的权限边界，再进行真实业务验收。本次只核验、补充 init 和留存复现脚本，没有修复业务代码或操作考试环境。

## 核验范围与证据边界

输入资料：

- [考试复盘报告](/Users/yukinoshitayukino/work_documents/智观考试系统问题全量复盘与整改报告-20261112.docx)。其中 SYS-01、SYS-02 是 P0；SYS-03、SYS-04 涉及恢复鉴权所必需的内部调用链。
- [当前鉴权方案](/Users/yukinoshitayukino/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/WenyongGod_f329/msg/file/2026-11/qwenpaw-authentication-20261113.md)。标注的基准提交与当前代码一致。
- 当前源码、部署模板、前端实现及相关测试。工作区原有四处已修改文件与未跟踪内容均予保留；未把它们当成本次修复。

运行验证使用本地 ASGI TestClient、临时运行目录、虚构用户、虚构凭据及合成备份；身份源在这些用例中被替换为返回稳定用户 ID 的测试对象。调用真实路由处理函数，未连接 INOE、模型或考试主机，未下载真实备份、读取真实设置或试用历史泄漏的凭据。

优先级根据当前代码可达性与影响判断。下面的 P0 不表示已经取得现场泄漏证据，而是已在隔离数据上复现同等权限路径。

## 已确认的问题

### AUTH-01 P0 备份路由名称不匹配导致普通用户能够下载备份

位置：`src/qwenpaw/extensions/api/access_policy.py:10`、`src/qwenpaw/app/routers/backup.py:47`、`src/qwenpaw/app/routers/backup.py:306`。

策略的管理员前缀为 `/api/backup`，真实路由为 `/api/backups`。前缀匹配要求完全相等或紧接 `/`，因此复数路径不匹配，随后 GET 被当作普通读取。列表、详情、导出处理函数均没有补充管理员检查。

复现结果：开启 SSO、生产守护开启、管理员名单为 `1` 时，身份源返回普通用户 `2`，`GET /api/backups` 和 `GET /api/backups/fixture-backup/export` 均为 200。导出的合成 ZIP 内可以读取 `data/secrets/.master_key` 的虚构内容。保持生产守护开启但关闭 SSO 时，这两个请求不带任何凭据也为 200。

影响：只要实例存在备份，普通用户可以先枚举 ID 再下载。含秘密的备份会带出密钥及认证材料；即使不包含秘密，也可能带出工作区、历史和配置。`backup/_ops/create_helpers.py:105` 会在选择 include_secrets 后把秘密目录文件加入 ZIP，签名不提供文件保密性。影响范围取决于已有备份内容，不要求攻击者先创建备份。

建议：按真实 `/api/backups` 注册管理员权限，覆盖列表、详情和导出；对实际注册的路由做权限矩阵测试，避免测试仅覆盖手写的假路径。

### AUTH-02 P0 文件预览绕过新的生产秘密文件策略

位置：`src/qwenpaw/app/routers/files.py:36`、`src/qwenpaw/extensions/security/execution_policy.py:61`、`src/qwenpaw/config/config.py:2004`。

工具和附件的新 `check_path` 明确拒绝 `settings.db`、认证材料和备份目录，但 `/api/files/preview/{filepath}` 仍使用独立的旧 FileGuardian，没有调用该策略。默认敏感目录主要保护 SECRET_DIR；业务设置数据库位于 WORKING_DIR/extensions/settings/settings.db。FileGuard 默认还允许预览工作区之外的文件，因此它也不是一个默认收敛的下载目录白名单。

复现结果：通过真实 settings_store 在临时工作区的 `extensions/settings/settings.db` 写入虚构 `inoe_api_token`，普通用户能用 GET 预览下载数据库，响应 200 且包含该虚构 Token。关闭 SSO 后匿名请求也为 200。同一个文件传给生产工具 `check_path` 则被拒绝。

影响：管理员设置页被限制访问后，低权限用户仍可能从文件出口取得服务凭据。`extensions/api/settings_store.py:136` 将设置值作为 JSON 字符串写入 SQLite；页面显示脱敏不等于数据库内容已加密。此漏洞在文件位于工作区内部时已经成立，关闭“允许工作区外预览”不足以修复。

建议：API 文件出口、工具与附件共用不可绕过的秘密路径策略；对公开给普通用户的下载采用明确的媒体/报告根目录范围，覆盖真实路径、符号链接、编码、HEAD 和备份文件。只给 `/api/files` 增加管理员限制仍不足以满足“秘密文件不能被文件预览绕过”的方案约束。

### AUTH-03 P0 完整智能体配置与频道配置仍向低权限用户返回凭据

位置：`src/qwenpaw/extensions/api/access_policy.py:104`、`src/qwenpaw/app/routers/agents.py:238`、`src/qwenpaw/app/routers/config.py:77`、`src/qwenpaw/app/routers/config.py:298`。

`/api/config` 不在管理员前缀内；`GET /api/agents/{id}` 归一后也会落入普通 GET 分支。完整智能体接口直接返回 AgentProfileConfig，包含 channels、MCP 和 tools 等配置；频道接口直接序列化 ChannelConfig，app_secret、bot_token、password 等字段使用普通字符串，没有响应脱敏。

复现结果：配置虚构飞书 app_secret 后，普通用户访问以下三个实际路径均为 200，并能拿到未脱敏的虚构 app_secret：

- `GET /api/agents/gateway`
- `GET /api/config/channels`
- `GET /api/agents/gateway/config/channels`

关闭 SSO 后，匿名请求也能读取。单频道接口以及其他配置读取入口应随修复一起检查，而不能只修这三个复现 URL。

建议：将完整配置读取纳入管理员权限，响应层对秘密做统一递归脱敏；向普通用户提供专用的最小摘要。保留正常智能体发现、聊天和安全元数据接口，避免简单封锁所有 `/api/agents` 使普通协同不可用。

### AUTH-04 P1 生产工具策略阻断官方只读技能与默认 MCP 调用

位置：`src/qwenpaw/extensions/security/execution_policy.py:38`、`:115`、`:224`、`:245`，`src/qwenpaw/drivers/handlers/mcp.py:110`。

默认种子授权分支只允许 `_READ_SCRIPT_NAMES` 中的十二个文件名。官方设备查询的 `get_devices.py`、`analyze_devices.py` 和概览的 `monitoring_overview.py` 不在名单中；CMDB 官方回退示例为 `.sh`，而生产检查只接受指定 Python 脚本或受控协同 CLI。

复现结果：构造完整、哈希一致的合成种子清单，以 `get_alarms.py` 作为对照可以通过；同条件下 `get_devices.py` 和 `monitoring_overview.py` 被拒绝。这不是缺种子文件或哈希不一致导致的误判。`scripts/zgops-cmdb.sh list-models` 则直接被解释器类型限制拒绝；管理员也没有在该分支审批放行的路径。

MCP 驱动又将实际工具名组合为 `<driver>__<tool>` 送入 check_tool。默认没有配置 `QWENPAW_READONLY_TOOL_NAMES`，这些调用不在内置只读集合，普通用户被拒绝；管理员通过身份验证后仍会因为返回 needs_approval 而被驱动以“未接入强制审批”拒绝。部署模板未提供这些业务只读工具的声明。

影响：修好入口 Token 不等于 gateway→fault 能完成查询。恢复生产守护后，资产、拓扑、指标等任务可能从凭据错误变为权限拒绝；MCP 不可用时的官方回退也不能正常工作。当前结论是默认策略与官方入口不相容，没有声称已在现场重放全部任务。

建议：按业务动作声明只读工具和固定参数 schema，将混合读写脚本拆分或按子命令授权，保持哈希和出站边界；给实际 Driver 工具名配置只读能力。不要通过关闭生产守护、放开任意 shell，或把混合读写工具整体声明只读来恢复功能。补普通用户、管理员与无身份后台任务的真实业务验收。

### AUTH-05 P1 Console 退出没有接入联邦会话撤销

位置：`console/src/layouts/Sidebar.tsx:170`、`:588`、`:600`，`console/src/api/ssoBootstrap.ts:15`，`src/qwenpaw/extensions/api/sso_backend.py` 的 logout/session 端点。

Console 的退出按钮仍只删除 localStorage 中的 Token 并跳到 `/login`，没有调用新的 `/sso/logout` 或 Cookie 清理接口。本地 HttpOnly Cookie 和数据库会话家族仍有效。下一次启动 bootstrap 会用 Cookie 调用 `/sso/session`，重新取回本地访问凭据。按钮的显示还依赖原生 `/auth/status.enabled`；只开 SSO、未开原生密码认证时，可能根本不显示退出入口。

隔离验证：删除前端本地 Token 所模拟的状态下，保留浏览器 Cookie，`/sso/session` 仍返回原凭据，旧会话还能成功续期。后端“显式调用 logout 后家族撤销及防续期复活”的测试已经通过，遗漏在前端调用路径。

建议：SSO 模式显示明确的退出入口，先携带当前本地凭据调用联邦 logout 撤销对应家族并清理 Cookie，再清空前端状态和导航；接口失败时明确区分“本地退出”和“服务端已撤销”。Portal 与 Console 同主机共享 Cookie 时也要验证两个前端各自持有的会话家族。

## 原复盘 P0 与内部凭据问题的闭环程度

| 复盘编号 | 本次确认 | 仍需完成 |
| --- | --- | --- |
| SYS-01 | SSO 默认开启；已分类的 envs、MCP、设置、审批等接口会要求管理员；关闭 SSO 时仍保留部分生产限制 | AUTH-01/02/03 表明管理读和文件出口仍有缺口；未核实 30 台实际开关与发布版本 |
| SYS-02 | 默认 INOE Token 常量已置空；取上一提交旧常量做不输出秘密内容的逐字节扫描，当前 Git 跟踪文件中匹配数为 0 | 旧 Token 是否吊销、持久设置/PVC/旧镜像和离线包是否清理，不能由当前源码证明；还要先关闭新的凭据读取入口 |
| SYS-03 | 本地 qp1、传统 X-Inoe-Token、请求上下文、受信内部转发和子进程环境均有实现与本地测试 | 按现场部署完成 CLI、SSE、gateway→fault、模型代理验收；AUTH-04/05 需要一并修复 |
| SYS-04 | 告警 execute 默认回退、显式凭据优先以及错误口径有相关测试 | 临时工作区热补丁、受管种子、升级后落盘与真实业务权限仍需现场核对 |

## 可以保留的实现

- 真实在线 userinfo 验证；客户端自报用户名、角色和 user_id 不授予管理员身份。
- qp1 签名、有效期、数据库映射与认证来源绑定共同校验；业务 INOE Token 加密保存在本地联邦会话中。
- 600 秒本地有效期、家族续期与撤销、注销和在途续期竞争保护。
- 显式凭据冲突、Cookie 写请求 Origin 检查、读缓存和写再验证策略。
- 内部模型能力 Key 的精确端点范围，以及内部协同凭据对 scheme/host/port 的约束。
- SSE 全生命周期 ContextVars 与只修改子进程环境的设计。

这部分通过定向测试支持，不能外推为所有接口、所有工具或真实生产配置均已覆盖。

## 方案已声明的限制与补充验收

以下属于方案明确保留的边界，应由部署和产品范围确认，不能当成本次新增发现：知识库 query 公开；会话、历史、记忆和部分业务缓存共享；本地读不会每次在线验证，最长 600 秒并非 INOE 即时吊销；本地注销并非 INOE 全局单点注销。

如果试用要求不同人员的数据彼此隔离，共享助手的边界就不满足要求，需要单独实现资源归属和数据过滤。后台服务凭据也要明确最小权限，不能用共享管理员 Token 抵消用户自身的权限。

现场还需核实：旧凭据吊销；TLS 终止后的 Cookie Secure 与真实 Origin；可信代理范围；网络策略实际 enforcement 与 INOE/模型/MCP 出站放行；Secret/PVC 权限和重建持久性；真实普通用户完整查询、审批、续期与退出。当前未连接现场，不能写成这些项目已通过。

还存在一个需要明确的配置差异：随包 `deploy-all/qwenpaw/working/config.json` 的 `security.delete_ops_disabled` 当前为 false；Helm values 没有强制覆盖为 true。方案示例中的 `QWENPAW_DELETE_OPS_DISABLED=true` 只有实际部署设置后才生效，不能默认认为该独立删除禁令已经开启。这不等于普通用户因此获得删除权限，但管理员操作边界必须按实际配置验收。

## 验证记录

- 后端鉴权/会话/执行边界/内部转发/部署安全的七个定向测试文件：209 通过。
- Portal 三个 SSO 测试文件：15 通过。
- Console `ssoBootstrap.test.ts`、`request.test.ts`：27 通过。
- 告警凭据、范围、真实告警集成层和概览集成层的四个测试文件：69 通过。后端两组合计 278 通过，连同前端共 320 项定向回归通过。
- 新增独立安全契约审计脚本：15 个检查中 14 个未满足预期；12 个涉及两种身份条件下的六条 API 路径，2 个涉及种子一致时仍被拒绝的官方查询脚本，1 个告警脚本对照通过。不是 14 个独立漏洞。

首次运行有测试被沙箱阻止创建运行锁或监听回环端口，已将运行状态隔离到临时目录并申请所需权限重跑；环境限制不计为业务缺陷。没有重跑作者宣称的全部 5773 个 Python 测试，也没有进行现场验收。

可重复执行：

```sh
.venv/bin/python scripts/verify/auth_review_20261113.py
```

该脚本只创建临时文件、虚构凭据和合成备份，通过本地 TestClient 请求真实处理函数，不连接外部服务。当前返回码为 1，表示安全预期仍有未满足项；修复后应逐项收敛到通过。退出按钮的前端路径另外通过源码核对和临时会话实验确认，没有把“清 localStorage 不自动通知后端”误报为后端 logout 缺陷。

## 建议实施顺序

1. 关闭 AUTH-01/02/03 的凭据读取路径，以真实注册路由和实际文件出口做低权限拒绝测试。
2. 修复 AUTH-04 的业务只读能力声明和 AUTH-05 的退出调用链，使用普通用户验收正常业务。
3. 在授权现场轮换旧凭据，准备 Secret、代理和网络覆盖配置，先单台灰度，再恢复其他试用环境的鉴权。
4. 将完整 P1/P2 问题继续单独跟踪；本次鉴权审查没有宣布原复盘的模型、知识库语料、性能、指标或输出异常全部关闭。
