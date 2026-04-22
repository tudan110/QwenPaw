# Alarm Analyst 稳定性整改方案

## 1. 文档目的

本文档用于落地 `alarm-analyst` 当前“不稳定、易漏步骤”的整改方案。

这里的重点不是重复《需求文档》或《执行计划》，而是针对当前实现的实际问题，明确：

- 为什么 `alarm-analyst` 会表现出“有时漏拓扑资源告警、有时漏指标”的不稳定行为
- 哪些问题属于现有实现的结构性缺陷，而不是单点 bug
- 应该按什么顺序修复，才能把链路从“尽量返回结果”收敛成“必须执行完整步骤，否则明确报 partial / blocked”
- 每一阶段的验收口径是什么

---

## 2. 当前问题定义

当前 `alarm-analyst` 的主要问题，不是“完全没有这条逻辑”，而是：

1. 链路已经具备根资源、拓扑、关联告警、指标等步骤
2. 但实现风格偏向 fail-open
3. 某一步拿得不完整时，流程仍会继续向后执行
4. 最终又经常把结果包装成“像是完整成功”的样子返回给 UI

因此用户看到的症状会是：

- 有时候没有收集完整的拓扑相关 `resourceIds`
- 有时候没有对全部 `resourceIds` 执行告警 fan-out
- 有时候没有真正按根资源类型查询指标
- 有时候 UI 上步骤是成功，但实际上下文并不完整

---

## 3. 已确认的问题根因

以下问题基于当前仓库实现确认。

### 3.1 结果构造层把步骤状态硬编码为 success

当前服务层在组装 `alarm-analyst` 结果时，直接把多个步骤写成 `success`，没有根据真实执行结果映射状态。

这会导致：

- 拓扑资源数是 0，也可能显示拓扑成功
- 关联告警只查到一部分，也可能显示成功
- 指标值为空，也可能显示成功

这类问题会掩盖真正的漏步骤和失败点，让前端和排查者误以为链路完整执行了。

### 3.2 聚合脚本整体是 fail-open

`analyze_alarm_context.py` 当前更像是“尽量搜集一些上下文并返回”，而不是“必须完成整条链”。

这意味着如果出现下面任一情况：

- 拓扑只提取到部分资源 ID
- 某些 `resId` 的告警查询失败
- 指标分析结果不完整

脚本通常仍然返回成功语义的聚合结果，而不是明确标记为 `partial` 或 `blocked`。

### 3.3 根资源指标类型存在静默回退

当前指标分析存在类似 `resolved_metric_type or "mysql"` 的兜底逻辑。

这会导致：

- 根资源 `ciType` 没有真实解析出来时，流程仍会继续执行
- 指标链路看上去“执行了”
- 但查到的可能是默认猜测的 MySQL 指标，而不是根资源真实类型的指标

这类行为不应该被视为成功，应该明确标记为阻断。

### 3.4 输入解析对 Portal 告警文本格式仍然偏脆弱

当前 Portal 铃铛告警上下文解析依赖较固定的文本格式。

一旦发生下面这类变动：

- `资源 ID` 标签形式变化
- 时间字段展示变化
- 标题行格式变化

解析得到的锚点就可能不完整，后续根资源、拓扑、告警 fan-out、指标链路都会受影响。

### 3.5 缺少“整链路完整性”测试

当前测试主要覆盖：

- 资源 ID 提取
- 拓扑摘要中的多个 ID 提取
- 查询顺序

但还没有把下面这些关键事实锁死：

- 如果拓扑里有 N 个 `resourceIds`，则 recent 告警查询必须执行 N 次
- 如果拓扑里有 N 个 `resourceIds`，则 compare 告警查询必须执行 N 次
- 根资源指标定义必须基于真实根资源 `ciType`
- 根资源指标值查询次数必须与选中的指标数对齐
- 任意一个 fan-out 查询失败时，整体状态必须降级为 `partial`

---

## 4. 整改目标

整改后的 `alarm-analyst` 应该从“尽量给结果”切换到“严格执行并显式暴露状态”。

具体目标如下：

1. 每一步是否真正完成，必须可观测
2. 任一关键步骤未完成时，结果不能再伪装成 success
3. 根资源指标类型必须来自真实根资源，而不是静默兜底猜测
4. 拓扑 fan-out 必须可验证地覆盖全部相关 `resourceIds`
5. Portal / 后端 / 技能脚本对“完整执行”的语义必须一致

---

## 5. 方案总览

建议采用“先补执行状态，再切换 UI 步骤语义，最后补强入口解析和测试”的三层收敛方案。

### 5.1 原则

- 先增加可观测性，再增强严格性
- 先保持对外返回结构兼容，再切换前端状态判断
- 先锁测试，再逐步收紧失败语义

### 5.2 不建议的做法

不建议继续打零散补丁，例如只修一条拓扑提取逻辑、或只补一个默认值判断。

原因是：

- 这不是单点 bug
- 问题来自“执行契约缺失”
- 如果没有显式执行状态，局部补丁很快还会被其它 fail-open 分支绕开

---

## 6. 分阶段整改方案

## Phase 1：补执行状态模型

### 目标

让 `alarm-analyst` 不再只有一份“汇总结果”，而是同时返回一份能描述整条链执行完整性的状态对象。

### 改动建议

在 `analyze_alarm_context.py` 的返回结果中新增 `execution` 块，至少包含：

```json
{
  "status": "success | partial | blocked",
  "inputAnchors": {
    "resIdFound": true,
    "eventTimeFound": true,
    "deviceNameFound": true,
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
    "queriedCount": 3,
    "failedCount": 0,
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
    "successIds": ["3094", "5002", "6003", "7004"],
    "failedIds": []
  },
  "relatedAlarmsPrevious": {
    "expectedQueries": 4,
    "attemptedQueries": 4,
    "successIds": ["3094", "5002", "6003", "7004"],
    "failedIds": []
  }
}
```

### 关键约束

- 顶层 `code` 可以暂时继续保持传输层成功语义
- 但“链路完整性”必须由 `execution.status` 表达
- 后续服务层和 UI 层都要依赖这个状态，而不是猜测 `findings` 或 `rows` 是否为空

### 验收标准

- 单看聚合结果，就能判断是 `success`、`partial` 还是 `blocked`
- 可以明确看出是哪个 `resId` 告警查询失败
- 可以明确看出指标链路是没查、查了部分，还是全部成功

---

## Phase 2：去掉静默兜底，改为显式阻断

### 目标

消除“根资源 `ciType` 不明仍默认按 mysql 继续查指标”的假成功行为。

### 改动建议

1. 删除 `resolved_metric_type or "mysql"` 这类静默兜底
2. 指标链路改成：
   - 根资源 `ciType` 成功解析 -> 继续执行指标定义和指标值查询
   - 根资源 `ciType` 缺失 -> `metric-analysis = blocked`
3. 在 `execution.metrics.skippedReason` 中记录明确原因，例如：
   - `missing_root_ci_type`
   - `metric_definition_query_failed`
   - `metric_data_partial_failure`

### 验收标准

- 没有根资源 `ciType` 时，不会再出现伪造的 MySQL 指标分析结果
- 指标分析失败时，结果会清晰降级为 `blocked` 或 `partial`

---

## Phase 3：固定 fan-out 输入集合并增加硬断言

### 目标

把“拓扑关联资源 ID -> 告警 fan-out”从软约定变成硬约束。

### 改动建议

1. 在拓扑摘要生成后，先冻结 `resourceIds`
2. 后续 recent 和 compare 两轮告警查询都严格基于这份固定列表执行
3. 在执行结果里显式记录：
   - `expectedQueries`
   - `attemptedQueries`
   - `successIds`
   - `failedIds`
4. 如果出现下列任一情况，整体不能是 `success`：
   - `attemptedQueries != expectedQueries`
   - `failedIds` 非空

### 验收标准

- fan-out 是否完整，不再依赖人工猜测
- 任何资源漏查都能从结构化结果中直接看出来

---

## Phase 4：服务层步骤状态按真实执行结果映射

### 目标

修复“底层不完整，UI 仍显示步骤 success”的假象。

### 改动建议

服务层 `_build_alarm_analyst_result()` 不再硬编码：

```python
{"id": "...", "status": "success"}
```

而是按 `execution` 状态映射：

- `root-resource`
  - `rootResource.resolved == true` -> `success`
  - 否则 -> `blocked`
- `cmdb-topology`
  - `resourceIdsCollected > 0` 且无明显缺失 -> `success`
  - 否则 -> `partial` 或 `blocked`
- `related-alarms-recent`
  - `failedIds` 为空且查询数完整 -> `success`
  - 否则 -> `partial`
- `related-alarms-compare`
  - 同 recent
- `metric-analysis`
  - 指标类型未解析 -> `blocked`
  - 部分指标失败 -> `partial`
  - 全部成功 -> `success`

### 配套要求

- `logEntries` 也要从“只报条数”升级为“能看出失败点”
- 至少要展示失败 `resId`、跳过原因、指标失败数

### 验收标准

- UI 不能再出现“步骤全绿但上下文不完整”
- 查看返回结果时，可以直接定位漏在哪一步

---

## Phase 5：统一重复实现，避免双份语义漂移

### 目标

避免不同服务层各自维护一套相似但不完全一致的状态映射逻辑。

### 改动建议

如果项目内还存在与 `alarm_analyst_service.py` 相近的结果组装逻辑，应统一成共享 helper 或明确保留单一入口。

原因：

- 重复逻辑会导致一处修了，另一处仍然假成功
- 文档、脚本、服务层的“完整执行”语义必须一致

### 验收标准

- 相同聚合上下文在不同入口下得到的步骤状态一致
- 不再存在一套返回 `partial`、另一套仍然返回 `success` 的情况

---

## Phase 6：补齐入口解析和整链路测试

### 目标

把“Portal 文本格式变化”和“整链路执行缺口”都纳入自动测试保护。

### 改动建议

#### 6.1 入口解析增强

Portal 告警上下文解析至少支持：

- `资源 ID（CI ID）`
- `资源ID`
- `资源 ID`
- `CI ID`
- `告警时间`
- 标题首行里的设备名 / 管理 IP 解析

#### 6.2 新增关键测试

至少补以下测试：

1. 拓扑返回 4 个 `resourceIds`
   - 断言 recent 告警查询执行 4 次
   - 断言 compare 告警查询执行 4 次
2. 其中 1 个 `resId` 查询失败
   - 断言 `execution.status == partial`
   - 断言失败 ID 出现在结果里
3. 根资源 `ciType` 缺失
   - 断言不执行指标查询
   - 断言 `metric-analysis == blocked`
4. Portal 文本格式多个变体
   - 断言都能稳定提取 `resId` 和 `eventTime`

### 验收标准

- 解析格式轻微变化不再直接打断主链
- fan-out 漏查、指标误查、状态误报都有测试守住

---

## 7. 推荐实施顺序

建议按下面顺序推进，而不是并行打补丁：

1. 先加 `execution` 状态模型
2. 再去掉 `metric_type` 的静默 mysql 回退
3. 再固定 `resourceIds` fan-out 的硬断言
4. 再切服务层步骤状态映射
5. 最后补入口解析和整链路测试

原因：

- 没有 `execution`，后面的严格性改造缺少判断依据
- 先补状态，再切换成功/失败语义，回归风险更低
- 测试应在状态模型确定后补齐，否则容易反复改口径

---

## 8. 验收清单

交付前至少满足以下条件：

- 根资源未解析时，`root-resource` 不再显示 success
- 根资源 `ciType` 缺失时，不再默认按 mysql 查指标
- 拓扑里有多少个 `resourceIds`，recent 和 compare fan-out 就各执行多少次
- 任意一个 `resId` 的告警查询失败时，整体状态降级为 `partial`
- `metric-analysis` 的 success / partial / blocked 能反映真实执行情况
- Portal / 服务层 / 技能脚本对“完整执行”语义一致
- UI 不再出现“步骤看起来全成功，但实际漏步骤”的情况

---

## 9. 一句话结论

`alarm-analyst` 当前不稳定，不是因为缺少某一条查询逻辑，而是因为整条 RCA 链缺少“必须完整执行”和“真实执行状态可观测”的硬约束。

整改的关键不是继续补单点逻辑，而是：

- 给整条链加显式执行状态
- 去掉静默兜底
- 把 fan-out 和指标链路的完整性变成硬断言
- 让服务层和 UI 只根据真实执行状态展示结果

只有这样，`alarm-analyst` 才能从“尽量返回一些分析”收敛成“稳定执行完整 RCA，做不到就明确告诉你卡在哪一步”。
