# 目标环境鉴权验证报告

- 验证时间：2026-11-18，Asia/Shanghai；HTTP 矩阵采集于 09:10–09:11。
- 环境：http://171.43.135.133:30083/
- 代码基线：`dev@f2eb4c30c1f60359a844f48485b19999cd175988`。已用 `git ls-remote` 核对远端，并确认用户切换后的工作区 HEAD 一致。
- 部署版本：响应行为与 dev 的 SSO 契约吻合，但未取得运行镜像摘要/部署 commit，不能证明线上已部署该 HEAD。
- 范围：匿名读取、虚构无效凭据、无效登录请求、浏览器入口跳转；未修改环境配置或业务数据，未使用真实账号。

## 结论

本轮 25 个 HTTP 用例中，2 个公开端点返回 200，其余 23 个请求均返回 401、403 或 502，未取得受保护业务数据。所测路径未发现匿名或伪造凭据绕过。该结论不覆盖有效账号的角色授权与用户间隔离，不能作为完整鉴权验收通过结论。

浏览器访问门户自动跳转至 `http://171.43.135.133:30081/login?redirect=http%3A%2F%2F171.43.135.133%3A30083%2F`。观察到登录目标 URL 和“正在加载系统资源”页面，未完成真实登录。

## 实测矩阵

| 用例 | 路径 | HTTP | 返回码/说明 |
| --- | --- | --- | --- |
| portal_health | `/portal-api/health` | 200 OK | {"status":"healthy"} |
| portal_sso_status | `/portal-api/sso/status` | 200 OK | {"configured":true,"authorization_code_ready":false,"sso_required":true,"login_url":""} |
| portal_business | `/portal-api/alarm-workorders` | 401 Unauthorized | SSO_TOKEN_REQUIRED |
| canonical_business | `/api/portal/alarm-workorders` | 401 Unauthorized | SSO_TOKEN_REQUIRED |
| copaw_alias | `/copaw-api/api/doctor/runtime` | 401 Unauthorized | SSO_TOKEN_REQUIRED |
| invalid_inoe | `/portal-api/alarm-workorders` | 502 Bad Gateway | SSO_VALIDATION_UNAVAILABLE |
| invalid_local | `/portal-api/alarm-workorders` | 401 Unauthorized | SSO_TOKEN_INVALID |
| invalid_cookie | `/portal-api/alarm-workorders` | 502 Bad Gateway | SSO_VALIDATION_UNAVAILABLE |
| fake_proxy_identity | `/portal-api/alarm-workorders` | 401 Unauthorized | SSO_TOKEN_REQUIRED |
| query_token | `/portal-api/alarm-workorders?token=auth-verification-invalid-20261118` | 401 Unauthorized | SSO_TOKEN_REQUIRED |
| bearer_invalid | `/portal-api/alarm-workorders` | 401 Unauthorized | SSO_TOKEN_INVALID |
| empty_header_cookie | `/portal-api/alarm-workorders` | 401 Unauthorized | SSO_TOKEN_REQUIRED |
| login_missing | `/portal-api/sso/token-login` | 401 Unauthorized | 缺少 INOE 登录凭证 |
| login_invalid | `/portal-api/sso/token-login` | 502 Bad Gateway | SSO 用户信息服务返回异常状态 |
| invalid_inoe_repeat | `/portal-api/alarm-workorders` | 502 Bad Gateway | SSO_VALIDATION_UNAVAILABLE |
| encoded_path | `/portal-api/%61larm-workorders` | 401 Unauthorized | SSO_TOKEN_REQUIRED |
| double_slash | `/portal-api//alarm-workorders` | 401 Unauthorized | SSO_TOKEN_REQUIRED |
| login_evil_origin | `/portal-api/sso/token-login` | 403 Forbidden | 登录或 Cookie 写请求来源不被允许 |
| login_null_origin | `/portal-api/sso/token-login` | 403 Forbidden | 登录或 Cookie 写请求来源不被允许 |
| login_same_origin | `/portal-api/sso/token-login` | 401 Unauthorized | 缺少 INOE 登录凭证 |
| session_noauth | `/portal-api/sso/session` | 401 Unauthorized | SSO_TOKEN_REQUIRED |
| admin_settings | `/portal-api/sso/sso-settings` | 401 Unauthorized | SSO_TOKEN_REQUIRED |
| identity_forgery | `/api/agents/gateway?user_id=admin` | 401 Unauthorized | SSO_TOKEN_REQUIRED |
| envs_noauth | `/api/envs` | 401 Unauthorized | SSO_TOKEN_REQUIRED |
| invalid_token_format | `/portal-api/alarm-workorders` | 401 Unauthorized | SSO_TOKEN_INVALID |

无效凭据均为固定测试字符串 `auth-verification-invalid-20261118` 或 `qp1.auth-verification-invalid`，不含真实密钥。完整响应见同目录 `auth-environment-20261118-evidence.json`。空头测试使用 curl 的 `-H 'X-Inoe-Token;'`，确保实际发送空值。

## 代码与现象对应

- `src/qwenpaw/extensions/api/sso_token_middleware.py:38`：健康、SSO 状态和三个登录辅助 POST 是公开入口；普通 API 受保护。路径别名、百分号编码和双斜线测试均被拦截。
- 同文件第 55 行起：区分 INOE token、本地 qp1 token 和 Cookie；URL query 不作为凭据，显式空头不回退 Cookie。实测吻合。
- `src/qwenpaw/extensions/api/access_policy.py:12`：浏览器来源校验。恶意 Origin、null Origin 均为 403；同源缺凭据为 401。无 Origin 且无 Cookie/浏览器来源标记的 CLI 请求允许进入凭据检查，这是代码明确行为。
- `src/qwenpaw/extensions/api/access_session.py:40` 与 `access_policy.py:141`：管理员由可信用户 ID 与服务端配置决定；匿名伪造身份不能通过认证。但普通用户是否正确得到 403，仍需有效账号实测。
- `src/qwenpaw/extensions/api/sso_auth.py:61`：明确无效身份映射 401，上游通用业务错误映射 502。

## 发现与限制

### INOE 无效凭据被归类为上游异常

普通无效字符串通过 header、Cookie 和 token-login 均得到 502，重复请求复现。返回为 `SSO_VALIDATION_UNAVAILABLE` / “SSO 用户信息服务返回异常状态”。系统保持拒绝访问，没有错误放行。

代码中非 200/401/403 业务码及未知 error 会进入该分支；本次没有服务器日志或上游响应，不能断言本次一定是业务码 500。仓库已有 11/13 报告记录类似上游业务 500，可作为排查线索而非本次证据。建议核对对应时间的 `SSO userinfo rejected` 日志，确保上游对过期/无效 token 返回明确认证错误。不要将所有 502 改为 401，以免掩盖真实故障。

### HTTP 传输边界

指定入口以明文 HTTP 提供页面和 API，未重定向 HTTPS；登录跳转地址也为 HTTP。真实凭据经此地址传输时缺乏 TLS 保护，应在正式使用前提供 HTTPS 入口。没有使用真实凭据验证会话 Cookie 的实际属性。

### 尚未覆盖

- 有效登录、token 换发及会话 Cookie 属性。
- 普通用户业务允许、管理接口 403，管理员正常访问。
- 多用户会话/数据隔离及越权。
- 过期、撤销、注销后重放，以及缓存窗口内外行为。
- WebSocket/SSE 长连接、模型服务 key 和真实工具执行边界。
- 上游故障注入、有效缓存失效、线上管理权限开关及部署镜像核对。

需专用普通用户、管理员测试会话，以及可控过期/撤销条件才能完成上述验证。当前 Python 缺少 pytest，本次未运行本地单元测试；在线 HTTP 结果与代码审阅分别记录，不以代码测试替代线上验收。

## 复核命令

```sh
curl -i http://171.43.135.133:30083/portal-api/sso/status
curl -i http://171.43.135.133:30083/portal-api/alarm-workorders
curl -i -H 'X-QwenPaw-Access-Token: qp1.auth-verification-invalid' http://171.43.135.133:30083/portal-api/alarm-workorders
curl -i -H 'X-Inoe-Token: auth-verification-invalid-20261118' http://171.43.135.133:30083/portal-api/alarm-workorders
curl -i -X POST -H 'Origin: https://auth-check.invalid' -H 'Content-Type: application/json' --data '{}' http://171.43.135.133:30083/portal-api/sso/token-login
```
