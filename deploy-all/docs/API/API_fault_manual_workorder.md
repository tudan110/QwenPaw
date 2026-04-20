# 故障处置人工工单闭环 API 文档

本文档描述 QwenPaw 后端为 **人工处理场景** 提供的两条接口：

1. **派单接口**：当 AI 无法直接完成处置时，把当前会话、资源和告警上下文提交给外部工单系统
2. **闭单通知接口**：当人工处理完成后，由工单系统回调 QwenPaw，继续在原会话展示处理结果，并按 `resId` 做恢复验证

相关后端代码位于：

- `src/qwenpaw/extensions/api/fault_manual_workorder_models.py`
- `src/qwenpaw/extensions/api/fault_manual_workorder_service.py`
- `src/qwenpaw/extensions/api/portal_backend.py`

## 概述

- **QwenPaw 后端基础路径**: `http://127.0.0.1:8088`
- **接口路径**:
  - `POST /api/portal/fault-disposal/manual-workorders/dispatch`
  - `POST /api/portal/fault-disposal/manual-workorders/notify-closed`

## 设计目标

这两条接口围绕下面的人工闭环路径工作：

1. AI 对告警做初步根因分析
2. 若 AI 判断当前不适合自动处置，则调用派单接口
3. QwenPaw 保存 `chatId`、`resId`、告警信息、AI 分析摘要，并生成一份可直接发给工单系统的派单请求体
4. 人工处理完成后，工单系统调用闭单通知接口
5. QwenPaw 根据 `chatId` 找回原会话，根据 `resId` 重新查询最新指标和指标值
6. QwenPaw 评估是否恢复正常，并把“人工处理结果 + 恢复验证结果”继续写回原会话

## 关键字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `chatId` | `string` | Portal / CoPAW 当前会话 ID，用于回到原会话继续展示结果 |
| `resId` | `string` | CMDB 返回的 CI ID，用于恢复验证时查询最新指标 |
| `metricType` | `string` | 资源类型，例如 `mysql`，默认可传 `mysql` |
| `alarm` | `object` | 当前告警信息快照 |
| `analysis` | `object` | AI 根因分析摘要、候选指标、处置建议 |
| `ticket` | `object` | 派单时的工单属性，如标题、优先级、分类 |
| `processing` | `object` | 人工处理完成后的处理摘要、处理详情 |

---

## 一、派单接口

### 接口路径

```http
POST /api/portal/fault-disposal/manual-workorders/dispatch
```

### 用途

当 AI 已经分析出根因方向和建议，但当前不适合直接自动处置时，调用该接口：

- 保存当前人工工单上下文
- 把一条“已转人工处理”的消息写回原 `chatId` 会话
- 返回一份可直接转发给外部工单系统的派单请求体

### 请求体

```json
{
  "chatId": "82bd7e8c-6940-414b-a59e-aede36f713ad",
  "resId": "3094",
  "metricType": "mysql",
  "alarm": {
    "alarmId": "alarm-001",
    "title": "数据库锁异常",
    "visibleContent": "数据库锁异常（db_mysql_001 10.43.150.186）",
    "deviceName": "db_mysql_001",
    "manageIp": "10.43.150.186",
    "assetId": "db_mysql_001",
    "level": "critical",
    "status": "active",
    "eventTime": "2026-04-20 15:00:00"
  },
  "analysis": {
    "summary": "AI 无法直接止血，转人工处理",
    "rootCause": "疑似 MySQL 锁等待 / 长事务 / 死锁",
    "suggestions": [
      "排查长事务",
      "检查阻塞链",
      "确认是否存在热点更新"
    ]
  },
  "ticket": {
    "title": "数据库锁异常人工处置",
    "priority": "P1",
    "category": "database-lock",
    "source": "portal-fault-disposal",
    "externalSystem": "manual-workorder"
  }
}
```

### 字段说明

#### 顶层字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `chatId` | 是 | 原故障会话 ID |
| `resId` | 是 | CMDB CI ID |
| `metricType` | 否 | 资源类型，默认建议传 `mysql` |
| `alarm` | 是 | 当前告警快照 |
| `analysis` | 否 | AI 当前分析结果 |
| `ticket` | 否 | 派单属性 |

#### `alarm` 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `alarmId` | 否 | 告警唯一标识 |
| `title` | 否 | 告警标题 |
| `visibleContent` | 否 | 对用户展示的告警摘要 |
| `deviceName` | 否 | 设备名 / 资源名 |
| `manageIp` | 否 | 管理 IP |
| `assetId` | 否 | 资产编号 |
| `level` | 否 | 告警级别 |
| `status` | 否 | 告警状态 |
| `eventTime` | 否 | 告警时间 |

#### `analysis` 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `summary` | 否 | AI 当前分析摘要 |
| `rootCause` | 否 | 根因描述，可为字符串或对象 |
| `suggestions` | 否 | AI 给出的人工处置建议 |

#### `ticket` 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `title` | 否 | 派单标题 |
| `priority` | 否 | 工单优先级，默认 `P1` |
| `category` | 否 | 工单分类，默认 `database-lock` |
| `source` | 否 | 来源系统，默认 `portal-fault-disposal` |
| `externalSystem` | 否 | 外部工单系统标识，默认 `manual-workorder` |

### 响应体

```json
{
  "status": "pending_manual",
  "chatId": "82bd7e8c-6940-414b-a59e-aede36f713ad",
  "resId": "3094",
  "manualWorkorder": {
    "chatId": "82bd7e8c-6940-414b-a59e-aede36f713ad",
    "resId": "3094",
    "metricType": "mysql",
    "status": "pending_manual",
    "alarm": {
      "title": "数据库锁异常",
      "visible_content": "数据库锁异常（db_mysql_001 10.43.150.186）"
    },
    "analysis": {
      "summary": "AI 无法直接止血，转人工处理"
    },
    "ticket": {
      "title": "数据库锁异常人工处置",
      "priority": "P1",
      "category": "database-lock",
      "source": "portal-fault-disposal",
      "external_system": "manual-workorder"
    },
    "dispatchPayload": {
      "chatId": "82bd7e8c-6940-414b-a59e-aede36f713ad",
      "resId": "3094",
      "metricType": "mysql",
      "alarm": {},
      "analysis": {},
      "ticket": {},
      "context": {
        "source": "portal-fault-disposal",
        "externalSystem": "manual-workorder",
        "callback_url": "http://127.0.0.1:8088/api/portal/fault-disposal/manual-workorders/notify-closed"
      }
    },
    "callbackUrl": "http://127.0.0.1:8088/api/portal/fault-disposal/manual-workorders/notify-closed",
    "createdAt": "2026-04-20T07:15:00+00:00",
    "updatedAt": "2026-04-20T07:15:00+00:00"
  },
  "dispatchRequest": {
    "chatId": "82bd7e8c-6940-414b-a59e-aede36f713ad",
    "resId": "3094",
    "metricType": "mysql",
    "alarm": {},
    "analysis": {},
    "ticket": {},
    "context": {
      "source": "portal-fault-disposal",
      "externalSystem": "manual-workorder",
      "callback_url": "http://127.0.0.1:8088/api/portal/fault-disposal/manual-workorders/notify-closed"
    }
  }
}
```

### 响应说明

| 字段 | 说明 |
|------|------|
| `status` | 固定为 `pending_manual`，表示已转人工处理 |
| `manualWorkorder` | QwenPaw 内部持久化后的工单上下文 |
| `dispatchRequest` | 可直接发给外部工单系统的派单请求体 |

### 行为说明

调用成功后，QwenPaw 会：

1. 以 `chatId + resId` 为键保存人工工单上下文
2. 在原会话历史里追加一条“已转人工处理”的 agent 消息
3. 返回一份标准化的派单请求体，供外部工单系统消费

---

## 二、闭单通知接口

### 接口路径

```http
POST /api/portal/fault-disposal/manual-workorders/notify-closed
```

### 用途

当人工处理完成后，由外部工单系统回调该接口：

- 带回 `chatId` 和 `resId`
- 补充人工处理结果
- 触发 QwenPaw 按 `resId` 重新查询最新指标和指标值
- 评估是否恢复正常
- 把“处理完成 + 恢复验证结果”写回原会话

### 请求体

```json
{
  "chatId": "82bd7e8c-6940-414b-a59e-aede36f713ad",
  "resId": "3094",
  "metricType": "mysql",
  "workorder": {
    "workorderNo": "WO-20260420-001",
    "status": "resolved",
    "handler": "alice",
    "completedAt": "2026-04-20T15:30:00+08:00"
  },
  "processing": {
    "summary": "已释放阻塞事务",
    "details": "人工终止长事务后恢复写入，观察 10 分钟无新增阻塞"
  }
}
```

### 字段说明

#### 顶层字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `chatId` | 是 | 原故障会话 ID |
| `resId` | 是 | CMDB CI ID |
| `metricType` | 否 | 资源类型，不传则优先使用派单时保存的值 |
| `workorder` | 否 | 工单处理元信息 |
| `processing` | 否 | 人工处理内容摘要 |

#### `workorder` 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `workorderNo` | 否 | 工单号 |
| `status` | 否 | 人工处理后工单状态，如 `resolved` |
| `handler` | 否 | 处理人 |
| `completedAt` | 否 | 完成时间 |

#### `processing` 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `summary` | 否 | 处理摘要 |
| `details` | 否 | 处理详情 |

### 响应体

```json
{
  "status": "recovered",
  "chatId": "82bd7e8c-6940-414b-a59e-aede36f713ad",
  "resId": "3094",
  "manualWorkorder": {
    "chatId": "82bd7e8c-6940-414b-a59e-aede36f713ad",
    "resId": "3094",
    "metricType": "mysql",
    "status": "manual_recovered",
    "workorder": {
      "workorder_no": "WO-20260420-001",
      "status": "resolved",
      "handler": "alice"
    },
    "processing": {
      "summary": "已释放阻塞事务",
      "details": "人工终止长事务后恢复写入，观察 10 分钟无新增阻塞"
    },
    "verification": {
      "status": "recovered",
      "summary": "最新关键指标未见锁等待/慢 SQL 类异常，可初步判定已恢复"
    }
  },
  "verification": {
    "status": "recovered",
    "summary": "最新关键指标未见锁等待/慢 SQL 类异常，可初步判定已恢复",
    "usedMock": false,
    "checkedMetrics": [
      {
        "code": "mysql_global_status_innodb_row_lock_time",
        "name": "InnoDB 总锁等待时长"
      }
    ],
    "abnormalMetrics": [],
    "metricDataResults": [
      {
        "metricCode": "mysql_global_status_innodb_row_lock_time",
        "latestValue": "0",
        "avgValue": "0",
        "source": "live"
      }
    ],
    "source": "live"
  }
}
```

### 响应说明

| 字段 | 说明 |
|------|------|
| `status` | 恢复验证状态：`recovered` / `unrecovered` / `unknown` |
| `manualWorkorder` | 更新后的人工工单上下文 |
| `verification` | 基于 `resId` 做出的恢复验证结果 |

### 行为说明

调用成功后，QwenPaw 会：

1. 根据 `chatId` 找到原会话
2. 根据 `resId` 找到对应的人工工单记录
3. 重新执行 `alarm-analyst` 指标脚本，查询当前最新指标和指标值
4. 评估是否恢复正常
5. 把人工处理内容和恢复验证结果继续写回原会话历史

若未找到对应的人工工单记录，返回：

```json
{
  "detail": "manual workorder not found for chatId=82bd7e8c-6940-414b-a59e-aede36f713ad, resId=3094"
}
```

HTTP 状态码为 `404`。

---

## 三、恢复验证规则

闭单通知后，QwenPaw 会按 `resId` 做恢复验证。

当前实现逻辑：

1. 调用 `alarm-analyst/scripts/get_metric_definitions.py`
2. 基于 `metricType + resId` 查询关键指标及其最新值
3. 若关键锁/等待/慢 SQL 指标仍大于 0，则判定为 **未恢复**
4. 若关键指标未见异常，则判定为 **已恢复**
5. 若指标接口回退到 mock，当前返回 **unknown**，并在结果里标记 `usedMock = true`

### 当前状态枚举

| 状态 | 说明 |
|------|------|
| `recovered` | 最新关键指标未见明显异常 |
| `unrecovered` | 最新关键指标仍显示锁等待 / 慢 SQL 类异常 |
| `unknown` | 指标查询失败或已回退到 mock，无法确认恢复状态 |

---

## 四、推荐接入方式

### 1. AI 转人工时

QwenPaw 先调用派单接口，拿到 `dispatchRequest` 后，把它发给外部工单系统。

### 2. 人工完成时

外部工单系统回调闭单通知接口，至少带：

```json
{
  "chatId": "82bd7e8c-6940-414b-a59e-aede36f713ad",
  "resId": "3094",
  "processing": {
    "summary": "已处理完成"
  }
}
```

### 3. Portal 展示

Portal 侧继续通过：

```http
GET /api/portal/fault-disposal/history/{chatId}
```

读取原会话消息流，即可看到：

1. 已转人工处理
2. 人工处理完成
3. 恢复验证结果

---

## 五、curl 示例

### 派单接口

```bash
curl -X POST "http://127.0.0.1:8088/api/portal/fault-disposal/manual-workorders/dispatch" \
  -H "Content-Type: application/json" \
  -d '{
    "chatId": "82bd7e8c-6940-414b-a59e-aede36f713ad",
    "resId": "3094",
    "metricType": "mysql",
    "alarm": {
      "title": "数据库锁异常",
      "visibleContent": "数据库锁异常（db_mysql_001 10.43.150.186）"
    },
    "analysis": {
      "summary": "AI 无法直接止血，转人工处理"
    }
  }'
```

### 闭单通知接口

```bash
curl -X POST "http://127.0.0.1:8088/api/portal/fault-disposal/manual-workorders/notify-closed" \
  -H "Content-Type: application/json" \
  -d '{
    "chatId": "82bd7e8c-6940-414b-a59e-aede36f713ad",
    "resId": "3094",
    "workorder": {
      "workorderNo": "WO-20260420-001",
      "status": "resolved"
    },
    "processing": {
      "summary": "已处理完成",
      "details": "人工释放阻塞事务后恢复写入"
    }
  }'
```
