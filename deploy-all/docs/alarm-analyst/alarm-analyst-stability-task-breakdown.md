# Alarm Analyst 稳定性整改任务拆分

> 本文档基于《[Alarm Analyst 稳定性整改方案](./alarm-analyst-stability-remediation.md)》拆分为可执行任务清单，供后续实现、联调和验收直接使用。

## 1. 目标

本次整改的目标不是继续补零散 bug，而是把 `alarm-analyst` 从“尽量返回一些分析结果”收敛成“必须完整执行 RCA 链路，做不到就明确返回 partial / blocked”。

拆分后的任务要覆盖四件事：

1. 给整条链路增加真实执行状态
2. 去掉静默兜底和假成功语义
3. 把拓扑 fan-out 和指标链路变成可验证硬约束
4. 用测试锁住 Portal 解析、后端状态映射和整链路完整性

---

## 2. 任务边界

### 2.1 本次必须改动的文件

- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/analyze_alarm_context.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/tests/test_analyze_alarm_context.py`
- `src/qwenpaw/extensions/api/alarm_analyst_service.py`
- `tests/unit/extensions/api/test_alarm_analyst_service.py`

### 2.2 可能需要改动的文件

- `src/qwenpaw/extensions/api/portal_backend.py`
- `tests/unit/extensions/api/test_portal_backend.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/SKILL.md`

### 2.3 本次不在首轮范围内的内容

- 大规模前端重构
- `real-alarm` 和 `zgops-cmdb` 的协议重构
- 新增依赖
- 端到端自动化 UI 测试

---

## 3. 推荐执行顺序

建议严格按下面顺序推进，不要跳步：

1. 先补 `execution` 状态模型
2. 再去掉指标类型静默回退
3. 再固定拓扑 fan-out 的硬断言
4. 再切服务层 steps / logs 状态映射
5. 最后补入口解析和整链路测试

原因：

- 状态模型是后续所有严格性改造的基础
- 如果先改 UI 语义、后补状态模型，容易反复改口径
- 如果先补局部逻辑而不补状态，很难判断改动是否真的消除了“假成功”

---

## 4. 任务拆分

### Task 1：定义统一执行状态模型

**目标**

在聚合脚本中新增一个统一的 `execution` 结构，专门表达整条 RCA 链是否完整执行，以及失败点在哪里。

**修改文件**

- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/analyze_alarm_context.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/tests/test_analyze_alarm_context.py`

**实现内容**

1. 在 `analyze_alarm_context()` 返回结构中新增 `execution`
2. `execution` 至少覆盖以下字段：
   - `status`
   - `inputAnchors`
   - `rootResource`
   - `metrics`
   - `topology`
   - `relatedAlarmsRecent`
   - `relatedAlarmsPrevious`
3. `status` 仅允许：
   - `success`
   - `partial`
   - `blocked`

**建议结构**

```json
{
  "execution": {
    "status": "partial",
    "inputAnchors": {
      "resIdFound": true,
      "eventTimeFound": true,
      "deviceNameFound": false,
      "manageIpFound": true
    },
    "rootResource": {
      "resolved": true,
      "resId": "3094",
      "ciType": "mysql"
    },
    "metrics": {
      "metricTypeResolved": true,
      "selectedCount": 3,
      "queriedCount": 2,
      "failedCount": 1,
      "skippedReason": ""
    },
    "topology": {
      "resourceIdsExpected": 4,
      "resourceIdsCollected": 4,
      "resourceIds": ["3094", "5002", "6003", "7004"]
    },
    "relatedAlarmsRecent": {
      "expectedQueries": 4,
      "attemptedQueries": 4,
      "successIds": ["3094", "5002", "6003"],
      "failedIds": ["7004"]
    },
    "relatedAlarmsPrevious": {
      "expectedQueries": 4,
      "attemptedQueries": 4,
      "successIds": ["3094", "5002", "6003", "7004"],
      "failedIds": []
    }
  }
}
```

**验收标准**

- 结果里可以直接看出是 `success` / `partial` / `blocked`
- 可以明确看出 recent / previous 哪些 `resId` 成功、哪些失败
- 不再只能靠 `findings` 或 `rows` 间接猜测链路是否完整

---

### Task 2：去掉指标类型静默兜底

**目标**

消除 `resolved_metric_type or "mysql"` 造成的误导性指标链路。

**修改文件**

- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/analyze_alarm_context.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/tests/test_analyze_alarm_context.py`

**实现内容**

1. 删除根资源指标类型的静默默认值
2. 指标执行前必须满足：
   - 根资源存在
   - 根资源 `ciType` 已解析
3. 如果不满足，则：
   - 不执行指标查询
   - `execution.metrics.metricTypeResolved = false`
   - `execution.metrics.skippedReason = "missing_root_ci_type"`
   - 整体状态至少降级为 `blocked`

**验收标准**

- `ciType` 缺失时，不再返回伪造的 MySQL 指标分析结果
- 指标查询是否执行，可以从结构化结果直接看出来

---

### Task 3：固定拓扑 resourceIds 集合

**目标**

确保用于告警 fan-out 的 `resourceIds` 是一份固定、可验证的集合，而不是边查边猜。

**修改文件**

- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/analyze_alarm_context.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/tests/test_analyze_alarm_context.py`

**实现内容**

1. 拓扑摘要生成后，先冻结 `resourceIds`
2. 这份列表作为 recent 和 previous 两轮 fan-out 的唯一输入
3. 在 `execution.topology` 中记录：
   - `resourceIdsExpected`
   - `resourceIdsCollected`
   - `resourceIds`
4. 根资源 ID 必须保持首位

**验收标准**

- 拓扑返回多少个资源 ID，结果里就记录多少个
- fan-out 输入集合不再受后续流程隐式修改

---

### Task 4：把 fan-out 完整性变成硬约束

**目标**

让拓扑告警查询从“尽量查一些”变成“必须查完整，否则降级”。

**修改文件**

- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/analyze_alarm_context.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/tests/test_analyze_alarm_context.py`

**实现内容**

1. recent 查询必须基于固定 `resourceIds` 全量执行
2. previous 查询必须基于固定 `resourceIds` 全量执行
3. 在 `execution.relatedAlarmsRecent` / `execution.relatedAlarmsPrevious` 里记录：
   - `expectedQueries`
   - `attemptedQueries`
   - `successIds`
   - `failedIds`
4. 下面任一情况都不能判定为 `success`：
   - `attemptedQueries != expectedQueries`
   - `failedIds` 非空

**验收标准**

- 可以结构化地证明 recent / previous 都查齐了
- 任意一个 `resId` 漏查时，状态降级为 `partial`

---

### Task 5：服务层按 execution 映射步骤状态

**目标**

修复当前服务层“步骤写死 success”的问题。

**修改文件**

- `src/qwenpaw/extensions/api/alarm_analyst_service.py`
- `tests/unit/extensions/api/test_alarm_analyst_service.py`

**实现内容**

1. `_build_alarm_analyst_result()` 从 `execution` 读取真实状态
2. 不再硬编码：

```python
{"id": "root-resource", "status": "success"}
```

3. 建议映射规则：
   - `root-resource`
     - `resolved = true` -> `success`
     - 否则 -> `blocked`
   - `cmdb-topology`
     - 已收集且无缺失 -> `success`
     - 部分缺失 -> `partial`
     - 未完成 -> `blocked`
   - `related-alarms-recent`
     - 查询完整且无失败 -> `success`
     - 有失败 -> `partial`
   - `related-alarms-compare`
     - 查询完整且无失败 -> `success`
     - 有失败 -> `partial`
   - `metric-analysis`
     - 指标链路完整 -> `success`
     - 部分失败 -> `partial`
     - 未执行 / 被阻断 -> `blocked`

**验收标准**

- UI 返回的 steps 能真实反映脚本执行情况
- 不再出现“拓扑 0 个资源也显示 success”的情况

---

### Task 6：增强日志可观测性

**目标**

让 `logEntries` 能帮助定位失败点，而不是只报汇总数字。

**修改文件**

- `src/qwenpaw/extensions/api/alarm_analyst_service.py`
- `tests/unit/extensions/api/test_alarm_analyst_service.py`

**实现内容**

1. 根资源日志明确记录：
   - `resId`
   - 根资源是否解析成功
   - `ciType`
2. 拓扑日志明确记录：
   - `resourceCount`
   - `resourceIds`
3. 关联告警日志明确记录：
   - expected / attempted 数
   - failedIds
4. 指标日志明确记录：
   - `metricTypeResolved`
   - `selectedCount`
   - `queriedCount`
   - `failedCount`
   - `skippedReason`

**验收标准**

- 排查时无需重新翻源码即可知道卡在哪一步
- 单看日志就能知道是拓扑漏资源、告警漏查，还是指标链路被阻断

---

### Task 7：增强 Portal 文本解析兼容性

**目标**

降低 Portal 铃铛文本格式轻微变化对 RCA 主链的影响。

**修改文件**

- `src/qwenpaw/extensions/api/alarm_analyst_service.py`
- `tests/unit/extensions/api/test_alarm_analyst_service.py`
- 视情况补 `src/qwenpaw/extensions/api/portal_backend.py`
- 视情况补 `tests/unit/extensions/api/test_portal_backend.py`

**实现内容**

1. 扩展 `resId` 标签兼容：
   - `资源 ID（CI ID）`
   - `资源ID`
   - `资源 ID`
   - `CI ID`
2. 扩展时间提取兼容
3. 明确记录输入锚点提取状态，便于判断问题出在入口还是聚合阶段

**验收标准**

- 文本格式有轻微变化时，不会直接丢失 `resId` / `eventTime`
- 入口解析失败时，结果能明确告诉使用者缺了什么

---

### Task 8：补齐整链路回归测试

**目标**

用自动化测试把“链路完整性”锁住。

**修改文件**

- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/tests/test_analyze_alarm_context.py`
- `tests/unit/extensions/api/test_alarm_analyst_service.py`
- 视情况补 `tests/unit/extensions/api/test_portal_backend.py`

**必须新增的测试场景**

1. 拓扑返回 4 个 `resourceIds`
   - 断言 recent 查询执行 4 次
   - 断言 previous 查询执行 4 次
2. 其中 1 个 `resId` 查询失败
   - 断言 `execution.status == partial`
   - 断言失败 ID 出现在结果中
3. 根资源 `ciType` 缺失
   - 断言不执行指标查询
   - 断言 `metric-analysis == blocked`
4. 服务层步骤状态映射
   - 断言 steps 不再默认 success
5. Portal 输入文本变体
   - 断言 `resId` / `eventTime` 都能解析

**验收标准**

- 回归测试可以防止未来再次引入“假成功”
- 未来如果有人恢复 `or "mysql"` 之类兜底，测试会直接失败

---

## 5. 依赖关系

任务之间存在明确依赖，不建议乱序并行：

- Task 1 是 Task 2、Task 4、Task 5、Task 6 的前置条件
- Task 3 是 Task 4 的前置条件
- Task 5 依赖 Task 1、Task 2、Task 4
- Task 8 应贯穿任务推进，但最终应在 Task 5 到 Task 7 完成后补齐

---

## 6. 建议交付批次

为了降低回归风险，建议分三批提交。

### 批次 A：状态模型与硬约束基础

- Task 1
- Task 2
- Task 3
- Task 4

**目标**

先让脚本层拥有真实执行状态，先把“做没做完”说清楚。

### 批次 B：服务层状态映射与日志

- Task 5
- Task 6

**目标**

把脚本层真实状态传递到服务层和 UI 结果中，消除假成功。

### 批次 C：入口解析与回归测试

- Task 7
- Task 8

**目标**

把入口稳定性和未来回归风险一起收口。

---

## 7. 最终验收口径

最终交付时，至少要满足下面这些判断：

- 根资源未解析时，`root-resource` 不再显示 success
- 根资源 `ciType` 缺失时，不再默认按 mysql 查指标
- 拓扑里有多少个 `resourceIds`，recent / previous fan-out 就各执行多少次
- 任意一个 `resId` 的告警查询失败时，整体状态降级为 `partial`
- `metric-analysis` 的状态能真实反映执行情况
- `logEntries` 能指出失败点，而不只是汇总条数
- Portal 文本格式轻微变化时，不会直接打断 RCA 主链

---

## 8. 执行建议

后续实际做代码整改时，建议按本文档逐 task 推进，不要把所有问题揉成一次性大改。

推荐方式：

1. 先完成 Task 1 到 Task 4
2. 跑脚本层测试，确认 `execution` 语义稳定
3. 再完成 Task 5 到 Task 6
4. 跑服务层测试，确认 steps / logs 状态稳定
5. 最后完成 Task 7 到 Task 8
6. 做一次 Portal 入口联调

如果需要继续细化，下一步可以再把本文档拆成“按文件的改动清单”或“按 commit 粒度的执行清单”。
