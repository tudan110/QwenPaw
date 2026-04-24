---
name: monitoring-overview-query
description: 查询监控总览页数据。适用于用户询问告警对象 Top5、监控总览拓扑、建议拓扑图、资产总览、监控概况、应用健康概览时使用。监控页中的实时告警时间范围查询继续使用 real-alarm，而不是本技能。
---

# Monitoring Overview Query

这是 `query` 数字员工的监控总览查询技能，封装 `topo/monitoring` 路由页对应的总览接口。

## 边界

- 告警列表、实时告警、按时间范围查询告警：继续使用 `real-alarm`。
- 数据库状态总览、资源性能 Top、数据库指标清单：继续使用 `resource-insight-query`。
- CMDB count/group、模型分布、厂商分布：继续使用 `veops-cmdb`。

## 配置

配置从本技能目录 `.env` 读取，也支持同名环境变量：

```bash
INOE_API_BASE_URL=http://<host>:<port>/prod-api
INOE_API_TOKEN=your_jwt_token_here
INOE_ENABLE_CURL_FALLBACK=true
```

## 常用命令

查询告警对象 Top5：

```bash
cd skills/monitoring-overview-query
python3 scripts/monitoring_overview.py alarm-top5 --output markdown
```

查询监控拓扑图：

```bash
cd skills/monitoring-overview-query
python3 scripts/monitoring_overview.py topology --output markdown
```

查询监控资产总览：

```bash
cd skills/monitoring-overview-query
python3 scripts/monitoring_overview.py asset-overview --output markdown
```

## 自然语言映射

- “告警对象 top5 / 告警对象排行 / 最常见告警对象”：执行 `alarm-top5`。
- “监控拓扑 / 建议拓扑图 / 监控总览拓扑”：执行 `topology`，优先输出可渲染 `echarts`。
- “资产总览 / 监控资产总览 / 监控概况”：执行 `asset-overview`。
- “最近 24 小时实时告警 / 某时间段实时告警”：不要用本技能，改用 `real-alarm` 并传 `--begin_time/--end_time`。

## 已封装接口

- `GET /resource/alarm/statistics/statResTop`
- `GET /resource/monitor/overview/topology`
- `GET /resource/monitor/overview/asset/overview`
