# Alarm Analyst 稳定性整改 Commit 粒度执行清单

> 本文档基于《[Alarm Analyst 稳定性整改任务拆分](./alarm-analyst-stability-task-breakdown.md)》进一步细化为按 commit 粒度的执行清单，目标是把整改工作拆成小步、可验证、可回滚的提交序列。

## 1. 使用方式

执行时建议严格按本文档的 commit 顺序推进。

每个 commit 都应满足：

- 改动范围单一
- 目标明确
- 测试能证明该 commit 本身成立
- 失败时容易回滚，不会把多个语义混在一起

同时建议提交信息遵循仓库现有 Lore Commit Protocol，重点写“为什么改”，不要只写“改了什么”。

---

## 2. 总体顺序

推荐拆成 5 个 commit：

1. 引入脚本层 `execution` 状态骨架
2. 去掉指标类型静默兜底并收紧指标链路
3. 固定拓扑 fan-out 集合并记录 recent / previous 完整性
4. 服务层按 `execution` 映射步骤与日志
5. 增强 Portal 文本解析并补齐回归测试

这样拆分的好处是：

- 前 3 个 commit 专注脚本层，语义集中
- 第 4 个 commit 只处理服务层展示语义，不和脚本逻辑混改
- 第 5 个 commit 负责入口兼容和测试收口，便于单独验证回归

---

## 3. Commit 明细

### Commit 1：引入 execution 状态骨架

**目标**

先让 `analyze_alarm_context.py` 返回结构里具备统一的 `execution` 字段，为后续所有严格性改造建立数据基础。

**涉及任务**

- Task 1

**建议修改文件**

- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/analyze_alarm_context.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/tests/test_analyze_alarm_context.py`

**本 commit 只做这些事**

1. 新增 `execution` 基础结构
2. 填入：
   - `status`
   - `inputAnchors`
   - `rootResource`
   - `metrics`
   - `topology`
   - `relatedAlarmsRecent`
   - `relatedAlarmsPrevious`
3. 暂时不改变外层 steps 的组装逻辑
4. 暂时不改 Portal 解析逻辑

**不要在这个 commit 混入**

- 删除 `or "mysql"` 兜底
- 改 UI steps 语义
- 扩展 Portal 文本格式兼容

**建议验证**

- `test_analyze_alarm_context.py` 新增断言：
  - 返回结果包含 `execution`
  - `execution` 字段结构完整
  - 成功路径下 `status == success`

**建议提交意图**

```text
Expose execution state for alarm-analyst RCA completeness
```

**风险**

- 如果在这个 commit 就开始调整状态降级规则，后面会难以判断骨架问题和业务规则问题谁导致失败

---

### Commit 2：去掉指标类型静默兜底

**目标**

修掉“根资源 `ciType` 没解析出来时仍按 mysql 查指标”的假成功行为。

**涉及任务**

- Task 2

**建议修改文件**

- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/analyze_alarm_context.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/tests/test_analyze_alarm_context.py`

**本 commit 只做这些事**

1. 删除 `resolved_metric_type or "mysql"` 类似兜底
2. 调整指标执行前置条件：
   - 根资源已解析
   - 根资源 `ciType` 已解析
3. 在 `execution.metrics` 中补充：
   - `metricTypeResolved`
   - `skippedReason`
   - `failedCount`
4. 无法执行指标时，把状态明确降级为 `blocked`

**不要在这个 commit 混入**

- 拓扑 fan-out 查询完整性改造
- 服务层 step 映射

**建议验证**

- 新增测试：
  - 根资源 `ciType` 缺失时，不执行指标查询
  - `execution.metrics.metricTypeResolved == false`
  - `execution.metrics.skippedReason == "missing_root_ci_type"`
  - 总体状态降级为 `blocked`

**建议提交意图**

```text
Block metric analysis when root ciType cannot be resolved
```

**风险**

- 如果服务层仍旧把 `metric-analysis` 写死为 success，这个 commit 之后脚本层语义会正确，但 UI 仍会假成功
- 这是预期现象，后续由 Commit 4 收口

---

### Commit 3：固定拓扑 fan-out 输入并记录完整性

**目标**

把“拓扑 resourceIds -> recent / previous fan-out”做成一套固定输入、可验收的完整性逻辑。

**涉及任务**

- Task 3
- Task 4

**建议修改文件**

- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/analyze_alarm_context.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/tests/test_analyze_alarm_context.py`

**本 commit 只做这些事**

1. 在拓扑摘要生成后冻结 `resourceIds`
2. recent / previous 两轮 fan-out 都只能基于这份固定列表执行
3. 在 `execution.relatedAlarmsRecent` / `execution.relatedAlarmsPrevious` 中记录：
   - `expectedQueries`
   - `attemptedQueries`
   - `successIds`
   - `failedIds`
4. 只要存在：
   - 漏查
   - 查询失败
   就把整体状态降级为 `partial`

**不要在这个 commit 混入**

- 服务层 step / log 映射
- Portal 文本格式解析增强

**建议验证**

- 新增测试：
  - 拓扑返回 4 个 `resourceIds` 时，recent 调用 4 次，previous 调用 4 次
  - 任意 1 个 `resId` 查询失败时，`execution.status == partial`
  - 失败 `resId` 会出现在 `failedIds`

**建议提交意图**

```text
Enforce complete topology alarm fan-out accounting
```

**风险**

- 这个 commit 后，脚本层可能开始更频繁地返回 `partial`
- 这是正确行为，不应被视为回归

---

### Commit 4：服务层按 execution 映射 steps 与 logEntries

**目标**

把脚本层的真实执行状态传递到服务层响应中，消除“底层 partial，前端全绿”的假象。

**涉及任务**

- Task 5
- Task 6

**建议修改文件**

- `src/qwenpaw/extensions/api/alarm_analyst_service.py`
- `tests/unit/extensions/api/test_alarm_analyst_service.py`

**本 commit 只做这些事**

1. `_build_alarm_analyst_result()` 改为读取 `execution`
2. steps 改为按真实状态映射：
   - `root-resource`
   - `cmdb-topology`
   - `related-alarms-recent`
   - `related-alarms-compare`
   - `metric-analysis`
3. `logEntries` 改为显示：
   - 失败 `resId`
   - fan-out expected / attempted
   - 指标链跳过原因
   - 指标失败数

**不要在这个 commit 混入**

- Portal 文本格式解析
- Portal route 行为变化

**建议验证**

- 新增测试：
  - `execution` 为 partial 时，steps 至少有一个不是 success
  - 拓扑资源数 0 时，`cmdb-topology != success`
  - 指标被阻断时，`metric-analysis == blocked`
  - `logEntries` 包含失败信息而不是只有汇总数字

**建议提交意图**

```text
Map alarm-analyst UI steps to real execution outcomes
```

**风险**

- 这个 commit 是最容易引发“用户感知变化”的提交，因为 UI 状态会从全绿变成 partial / blocked
- 但这是修正误报，不是功能回退

---

### Commit 5：增强 Portal 解析兼容并补回归测试

**目标**

收口入口解析的不稳定性，并用测试把整条链路锁住。

**涉及任务**

- Task 7
- Task 8

**建议修改文件**

- `src/qwenpaw/extensions/api/alarm_analyst_service.py`
- `tests/unit/extensions/api/test_alarm_analyst_service.py`
- `src/qwenpaw/extensions/api/portal_backend.py`
- `tests/unit/extensions/api/test_portal_backend.py`
- 视情况补 `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/SKILL.md`

**本 commit 只做这些事**

1. 扩展 Portal 告警文本兼容：
   - `资源 ID（CI ID）`
   - `资源ID`
   - `资源 ID`
   - `CI ID`
2. 补强时间字段提取兼容
3. 增加服务层和入口层回归测试
4. 如有必要，更新 `SKILL.md` 对“完整执行”的说明

**建议验证**

- 新增测试：
  - 多种文本变体都能提取出 `resId` 和 `eventTime`
  - 入口解析失败时，返回结果能明确说明缺失锚点
  - Portal 集成路径仍然能走通现有 `alarm-analyst` 入口

**建议提交意图**

```text
Harden portal alarm parsing and lock RCA completeness tests
```

**风险**

- 如果这个 commit 和前面的服务层映射混在一起，出了问题很难判断是入口解析导致，还是状态映射导致
- 因此不建议提前合并

---

## 4. 每个 Commit 后的建议验证序列

### Commit 1 后

- 跑脚本层结构测试
- 确认 `execution` 字段存在且不破坏现有返回结构

### Commit 2 后

- 跑脚本层指标链路测试
- 确认 `ciType` 缺失时不再查默认 mysql 指标

### Commit 3 后

- 跑脚本层 fan-out 测试
- 确认 recent / previous 查询次数与 `resourceIds` 一致

### Commit 4 后

- 跑服务层测试
- 确认 steps / logs 已按真实状态映射

### Commit 5 后

- 跑解析与回归测试
- 视情况做一次 Portal 入口联调

---

## 5. 建议的最小测试矩阵

为了避免每个 commit 都跑过多无关验证，建议最小测试矩阵如下：

### 脚本层

- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/tests/test_analyze_alarm_context.py`

### 服务层

- `tests/unit/extensions/api/test_alarm_analyst_service.py`

### Portal 入口层

- `tests/unit/extensions/api/test_portal_backend.py`

建议执行策略：

- Commit 1 到 Commit 3：以脚本层测试为主
- Commit 4：脚本层 + 服务层
- Commit 5：脚本层 + 服务层 + Portal 入口层

---

## 6. 提交时的注意事项

### 6.1 不要把这些内容混在同一次提交

- 状态模型引入 + Portal 文本解析增强
- 去静默兜底 + steps UI 语义切换
- fan-out 完整性 + 其它无关文档大改

### 6.2 推荐保留的小步风格

- 每个 commit 只修一个层次的问题
- 先补状态，再补规则，再补展示，再补入口兼容
- 每个 commit 都让测试结论清晰

### 6.3 推荐在提交说明里写清楚

- 这次提交改变的是“执行语义”还是“展示语义”
- 哪些旧行为是故意收紧，而不是意外回归
- 哪些测试证明了该收紧行为是正确的

---

## 7. 最终落地标准

这 5 个 commit 全部完成后，应达到以下状态：

- 脚本层具备统一 `execution` 状态模型
- 指标链路不再静默兜底为 mysql
- 拓扑 fan-out 的完整性可结构化验证
- 服务层 steps / logs 不再假成功
- Portal 输入格式轻微波动时，RCA 主链仍然稳定
- 回归测试可以防止未来再次引入“假成功”和“漏 fan-out”

---

## 8. 一句话执行建议

后续真正做代码整改时，直接按这 5 个 commit 顺序推进，不要试图把所有问题一次性合成“大修复提交”。

对 `alarm-analyst` 这类链路型逻辑来说，小步、可验证、可回滚，比一次性“全修完”更安全。
