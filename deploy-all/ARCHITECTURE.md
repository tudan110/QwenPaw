# Portal / CoPAW 当前架构说明

## 当前落地架构

- `portal` 是纯前端，只负责页面渲染和调用 CoPAW API。
- `copaw` 是统一后端基座，承载：
  - 原生 `/api/*`
  - Portal 扩展路由 `/api/portal/*`
  - skills
  - MCP / 外部系统接入

## 关键目录

| 路径 | 作用 |
|------|------|
| `src/copaw/agents/skills/` | skills 主目录 |
| `src/copaw/extensions/api/` | Portal 等业务扩展 API |
| `src/copaw/extensions/integrations/` | MCP / 外部系统集成目录 |
| `deploy-all/portal/nginx.conf` | Portal 反向代理配置 |
| `deploy-all/copaw/data/copaw/custom_channels/portal_api.py` | 把 Portal 扩展路由挂到 CoPAW 主应用 |

## 请求链路

- 前端请求 `/copaw-api/*` → nginx 代理 → `copaw:8088/*`
- 前端请求 `/portal-api/*` → nginx 代理 → `copaw:8088/api/portal/*`

## 当前结论

- 故障速应已经切到 CoPAW 标准聊天 / skill 调度链路
- Portal 扩展路由仅保留告警工单桥接接口
- 外部系统接入统一收口到 `src/copaw/extensions/integrations/`
