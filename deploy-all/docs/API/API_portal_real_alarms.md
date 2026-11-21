# Portal 实时告警接口文档（铃铛）

本文档描述 Portal 页面右上角铃铛所使用的实时告警查询接口及相关告警台账接口。

相关后端代码位于：

- `src/qwenpaw/extensions/integrations/portal_real_alarms.py`
- `src/qwenpaw/extensions/portal_real_alarm_registry.py`
- `src/qwenpaw/extensions/api/portal_backend.py`

## 概述

- **Portal API 基础路径**: `http://<host>:8088/api/portal`
- **鉴权**: 无（与 QwenPaw 同机部署时无需 Token）
- **上游数据源**: INOE 网关 `POST /resource/realalarm/list`（端口 30080）

铃铛的核心交互分两个阶段：

1. **轮询阶段** — 前端每 30 秒调用 `GET /real-alarms`，将 INOE 活跃告警拉取并展示在铃铛列表中
2. **派发阶段** — 用户点击某条告警后，前端调用 `POST /alarm-registry/register` 登记该告警，随后跳转至对应数字员工发起 AI 分析对话

---

## 接口一：获取实时告警列表

### GET /api/portal/real-alarms

从 INOE 网关拉取当前活跃告警，并过滤掉已被接管（分析中/已处理）的告警，返回需要在铃铛上展示的条目。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `limit` | integer | 否 | 最多返回条数；省略时取设置页 `alarm_list_limit`（默认 20，最大 200） |

#### 响应体（HTTP 200）

```json
{
  "total": 3,
  "source": "live",
  "items": [
    {
      "id": "ALM-0001",
      "alarmId": "ALM-0001",
      "resId": "dev-123",
      "title": "CPU 利用率超阈值",
      "level": "critical",
      "status": "active",
      "eventTime": "2026-06-17 10:00:00",
      "timeLabel": "2026-06-17 10:00:00",
      "deviceName": "core-switch-01",
      "manageIp": "10.0.0.1",
      "employeeId": "fault",
      "dispatchContent": "CPU 利用率超阈值 / core-switch-01",
      "visibleContent": "CPU 利用率超阈值（core-switch-01 10.0.0.1）",
      "levelName": "紧急",
      "statusName": "活跃",
      "className": "设备告警",
      "speciality": "",
      "region": "",
      "ciId": "dev-123",
      "eventLastTime": "",
      "message": "【紧急】CPU 利用率超阈值｜core-switch-01 10.0.0.1｜活跃",
      "count": 5
    }
  ]
}
```

#### 响应字段说明

**核心字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` / `alarmId` | string | 告警唯一标识，来自 INOE 的 `alarmuniqueid` |
| `resId` | string | 设备资源 ID（来自 INOE 的 `devId`） |
| `title` | string | 告警标题（来自 `alarmtitle`） |
| `level` | string | 告警级别，见下方映射表 |
| `status` | string | 固定为 `"active"` |
| `eventTime` / `timeLabel` | string | 告警发生时间，格式 `YYYY-MM-DD HH:MM:SS` |
| `deviceName` | string | 设备名（来自 `devName`） |
| `manageIp` | string | 管理 IP |
| `employeeId` | string | 固定为 `"fault"`，派发至故障处置数字员工 |
| `dispatchContent` | string | 发送给 AI 的指令文本（内部用） |
| `visibleContent` | string | 对话中展示给用户的告警摘要 |

**展示增强字段**（与大屏告警流保持一致）

| 字段 | 类型 | 说明 |
|------|------|------|
| `levelName` | string | 告警级别中文名：紧急 / 严重 / 普通 / 预警 |
| `statusName` | string | 告警状态中文名：活跃 / 自动清除 / 同步清除 / 手工清除 |
| `className` | string | 告警类型：设备告警 / 性能告警 / 衍生告警 |
| `speciality` | string | 专业分类 |
| `region` | string | 地区 |
| `ciId` | string | CI 资源标识 |
| `eventLastTime` | string | 告警最后更新时间 |
| `message` | string | 富文本摘要，供大屏告警流组件渲染 |
| `count` | integer | 告警累计触发次数（可选，有时 INOE 不返回） |

#### INOE severity → level 映射

| INOE `alarmseverity` | 前端 `level` | `levelName` |
|---|---|---|
| `"1"` | `critical` | 紧急 |
| `"2"` | `urgent` | 严重 |
| `"3"` | `warning` | 普通 |
| `"4"` / 其他 | `info` | 预警 |

#### 背后的 INOE 上游请求

本接口内部向 INOE 网关发出如下请求（关键参数见注释）：

```
POST http://gateway:30080/resource/realalarm/list
Content-Type: application/json
Authorization: Bearer <inoe_token>

{
  "pageNum": 1,
  "pageSize": 20,           // 对应 limit 参数
  "alarmstatus": "1",       // 固定取活跃告警；"1" = 活跃，"0" = 已清除
  "alarmseverity": "",
  "alarmseveritys": [],
  "params": {
    "beginEventtime": null,  // 无时间范围限制
    "endEventtime": null
  },
  // 其余过滤字段均为 null / []，不做额外筛选
  ...
}
```

> **说明**：`alarmstatus` 是此接口最核心的参数，铃铛场景固定传 `"1"`（活跃），后端不对外暴露该参数，由 QwenPaw 统一控制。

#### curl 示例

```bash
# 取默认条数
curl http://<host>:8088/api/portal/real-alarms

# 指定最多返回 50 条
curl "http://<host>:8088/api/portal/real-alarms?limit=50"
```

---

## 接口二：登记告警（手动派发）

### POST /api/portal/alarm-registry/register

用户点击铃铛列表中的某条告警后触发。将该告警写入台账，状态初始化为 `analyzing`，随后前端跳转至故障处置数字员工发起对话。

#### 请求体

```json
{
  "alarmId": "ALM-0001",
  "resId": "dev-123",
  "title": "CPU 利用率超阈值",
  "deviceName": "core-switch-01",
  "manageIp": "10.0.0.1",
  "eventTime": "2026-06-17 10:00:00",
  "visibleContent": "CPU 利用率超阈值（core-switch-01 10.0.0.1）",
  "status": "analyzing",
  "source": "manual-bell"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `alarmId` | string | **是** | 告警唯一标识，与 INOE `alarmuniqueid` 对应；同 ID 重复调用为 upsert |
| `resId` | string | 否 | 设备资源 ID |
| `title` | string | 否 | 告警标题 |
| `deviceName` | string | 否 | 设备名 |
| `manageIp` | string | 否 | 管理 IP |
| `eventTime` | string | 否 | 告警发生时间 |
| `visibleContent` | string | 否 | 对话展示文本 |
| `status` | string | 否 | 初始状态，默认 `analyzing` |
| `source` | string | 否 | 来源标识，默认 `manual-bell` |

#### 响应体（HTTP 200）

```json
{
  "ok": true,
  "record": { /* AlarmRegistryRecord */ }
}
```

---

## 附：告警台账 CRUD 接口

以下接口用于告警台账的查看与管理（Portal 告警台账页面使用）。

### GET /api/portal/alarm-registry/records

分页查询台账记录。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `status` | string | `""` | 按状态过滤，逗号分隔，如 `analyzing,analyzed` |
| `page` | integer | `1` | 页码（≥1） |
| `page_size` | integer | `20` | 每页条数（1–200） |
| `search` | string | `""` | 搜索 title / deviceName / manageIp / alarmId / resId |

### PATCH /api/portal/alarm-registry/records/{alarm_id}/status

更新台账状态或关联的 chatId。

```json
{ "status": "analyzed", "chatId": "chat-xxx" }
```

**`status` 合法值**：`new` · `taken_over` · `analyzing` · `analyzed` · `manual_pending` · `manual_recovered` · `manual_unrecovered` · `manual_unknown` · `resolved` · `ignored`

### GET /api/portal/alarm-registry/stats

```json
{ "total": 42, "byStatus": { "analyzing": 5, "analyzed": 30, "resolved": 7 } }
```

### 告警明细导出（Portal）

此上限只适用于结构化告警明细的单次文件下载，不限制查询、统计或台账翻页。台账与智能体实时告警共用同一上限，默认 **10 条**；智观 AI 管理员可在「设置 → 安全与审计 → 导出管控」配置 **1–200 条**。

- `GET /api/portal/alarm-export-settings`：读取 `{"max_rows": 10}`，仅管理员可用。
- `PUT /api/portal/alarm-export-settings`：传入 `{"max_rows": 10}` 保存，仅管理员可用。
- `POST /api/portal/alarm-export/preview`：核对完整筛选范围，不限于当前页。台账请求示例为 `{"source":"registry","status":"analyzed","search":"路由器"}`；实时告警请求使用 `source: "live"`，必填 `begin_time`、`end_time`（告警平台时间，`YYYY-MM-DD HH:mm:ss`）及 `is_clear`（`"0"` 未清除、`"1"` 已清除），可携带 `severity`、`keyword` 或 `manage_ip`、`resource_type`。实时告警使用当前账号的告警平台权限。
- 预览返回 `count`、`max_rows` 和 `message`。仅有记录且未超限时返回一次性 `ticket`（有效期 5 分钟）。例如请求 100 条、上限 10 条时，响应不含 `ticket`，不会导出，也不会截断为前 10 条。
- `POST /api/portal/alarm-export/download`：用户确认后提交 `{"selection": <与预览相同的筛选条件>, "ticket": "<预览返回的凭证>"}`。服务端重新检查上限和记录内容；通过后返回包含 `total`、`items` 的 `alarms.json`。记录变化需重新预览确认，超限时无文件。
- 旧 `GET /api/portal/alarm-registry/export` 不再直接返回文件：超限返回 422，否则提示使用台账确认流程（409）。

后端记录上限变更、超限拦截和放行等审计元数据，不记录告警正文。当前功能不包含累计配额、超限例外审批，也不是报告或其他文件类型的通用内容管控。

---

## AlarmRegistryRecord 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `alarmId` | string | 告警唯一标识 |
| `resId` | string | 设备资源 ID |
| `title` | string | 告警标题 |
| `deviceName` | string | 设备名 |
| `manageIp` | string | 管理 IP |
| `eventTime` | string | 告警发生时间 |
| `visibleContent` | string | 对话展示文本 |
| `status` | string | 当前台账状态 |
| `sessionId` | string | 关联 AI 会话 ID |
| `chatId` | string | 关联 Chat ID（对话创建后回填） |
| `source` | string | `manual-bell`（手动）/ `auto-takeover`（自动接管） |
| `verificationStatus` | string | 恢复核验结果 |
| `createdAt` | string | 创建时间 |
| `updatedAt` | string | 最近更新时间 |
| `takenOverAt` | string | 被 AI 接管时间 |
| `handledAt` | string | 处理完成时间 |
| `resolvedAt` | string | 标记已解决时间 |

---

## 整体数据流

```
INOE 网关 POST /resource/realalarm/list（alarmstatus=1）
        ↓ 后端过滤已登记告警
GET /api/portal/real-alarms  ←── 前端每 30 s 轮询
        ↓ 铃铛红点 + 弹出列表
用户点击某条告警
        ↓
POST /api/portal/alarm-registry/register  (status=analyzing, source=manual-bell)
        ↓
跳转故障处置数字员工对话页，发起 AI 分析
        ↓
PATCH /api/portal/alarm-registry/records/{id}/status  (status=analyzed, chatId=xxx)
```
