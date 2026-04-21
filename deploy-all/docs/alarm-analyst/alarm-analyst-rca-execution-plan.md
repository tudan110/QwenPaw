# Alarm Analyst 根因分析流程执行计划

## 1. 文档目的

本文档基于《[Alarm Analyst 根因分析流程需求文档](./alarm-analyst-rca-requirements.md)》拆解出可执行的实施计划，用于指导 `alarm-analyst`、Portal、`real-alarm`、`veops-cmdb` 以及后端路由的联动改造。

目标不是重复需求，而是明确：

- 先做什么，后做什么
- 每个阶段需要改哪些模块
- 每个阶段的验收标准是什么
- 哪些风险需要提前控制

---

## 2. 总体实施原则

### 2.1 主流程原则

完整 RCA 链路必须围绕告警 `resId` 与 `eventTime` 作为锚点展开，并严格按以下顺序执行：

1. 根资源确认
2. 根资源指标定义与指标值采集
3. CMDB 拓扑扩散
4. 拓扑关联资源 ID 汇总
5. 拓扑关联资源告警采集
6. 当前窗口与环比窗口比较
7. AI 综合 RCA

### 2.2 工程原则

- 运行入口与 `SKILL.md` 描述必须一致
- 文档、后端、前端、脚本不可各自实现不同版本的流程
- 所有“必须步骤”都要有代码或测试锁定
- 对外接口路径、请求体字段、时间窗口逻辑必须以真实接口为准

---

## 3. 实施范围

本次实施涉及以下模块：

### 3.1 文档层

- `deploy-all/docs/alarm-analyst/alarm-analyst-rca-requirements.md`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/SKILL.md`

### 3.2 技能脚本层

- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/analyze_alarm_context.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/get_metric_definitions.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/real-alarm/scripts/get_alarms.py`
- `deploy-all/qwenpaw/working/workspaces/query/skills/veops-cmdb/scripts/*`

### 3.3 后端接口层

- `src/qwenpaw/extensions/api/alarm_analyst_service.py`
- `src/qwenpaw/extensions/api/portal_backend.py`
- `src/qwenpaw/app/_app.py`

### 3.4 前端入口层

- `portal/src/pages/DigitalEmployeePage.tsx`
- `portal/src/api/portalRealAlarms.ts`
- `portal/src/api/faultScenario.ts`

### 3.5 测试层

- `tests/unit/extensions/api/test_alarm_analyst_service.py`
- `tests/unit/extensions/api/test_portal_backend.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/alarm-analyst/scripts/tests/test_analyze_alarm_context.py`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/real-alarm/scripts/tests/test_ci_id_support.py`
- `deploy-all/qwenpaw/working/workspaces/query/skills/veops-cmdb/scripts/tests/test_http_fallback.py`

---

## 4. 分阶段执行计划

## Phase 1：统一输入锚点

### 目标

确保 Portal 进入故障处置员时，`alarm-analyst` 能稳定拿到：

- `resId`
- `eventTime`
- `alarmTitle`
- `deviceName`
- `manageIp`

### 改动项

1. Portal 右上角铃铛点击文本必须补充：
   - `资源 ID（CI ID）：<resId>`
   - `告警时间：<eventTime>`
2. 后端解析逻辑必须能从消息中提取：
   - `resId`
   - `eventTime`
   - `manageIp`
   - 标题 / 设备名
3. 如果缺少 `resId` 或 `eventTime`，明确退回脚手架 / 错误提示，不允许静默降级成不完整 RCA

### 验收标准

- 点击一条告警后，后端收到的内容里能稳定解析出 `resId`
- 能稳定解析出 `eventTime`
- 没有 `resId` 时，系统能明确报错或退回脚手架，而不是继续跑半套流程

---

## Phase 2：根资源确认与指标链路

### 目标

在做拓扑扩散前，先明确根资源本身，并基于根资源 `ciType` 完成指标链路。

### 改动项

1. `alarm-analyst` 聚合脚本必须先查根资源详情
2. 从根资源详情中确认 `ciType`
3. `getMetricDefinitions` 必须使用根资源 `ciType`
4. `getMetricData` 必须使用根资源 `resId`
5. 指标定义接口与指标值接口路径必须按真实接口修正：
   - `POST /resource/resource/threshold/getMetricDefinitions`
   - `POST /resource/pm/getMetricData`

### 验收标准

- RCA 链路中，根资源 `ciType` 不是从拓扑“猜”出来的
- MySQL 告警场景下，根资源类型能明确为 `mysql`
- 指标定义和指标值查询的入参都与真实接口一致

---

## Phase 3：CMDB 拓扑扩散与资源 ID 汇总

### 目标

保证从 `veops-cmdb` 拿到的拓扑关系里，**全部**相关资源 ID 都被识别并参与后续告警 fan-out。

### 改动项

1. 先以根资源 `resId` 调用 `ci_relations/s`
2. 从返回中提取：
   - 节点 ID
   - 关系边两端 ID
   - 嵌套对象中的资源 ID
3. 构建去重后的 `resourceIds`
4. 根资源 ID 必须保留在集合首位

### 验收标准

- 不再只从每个拓扑节点取一个 ID
- `src_ci_id / dst_ci_id / parent / child / source / target` 等结构都能提取
- 测试中能证明拓扑中的所有相关资源都会进入集合

---

## Phase 4：拓扑关联资源告警 fan-out

### 目标

完成“所有拓扑关联资源 ID -> 告警 fan-out”这一步，并把它作为必做步骤固定下来。

### 改动项

1. 对 `resourceIds` 中每个资源 ID 调用 `real-alarm`
2. 请求体必须满足：
   - `neId = 当前资源 ID`
3. 当前窗口默认使用：
   - `eventTime - 10 分钟`
   - `eventTime + 10 分钟`
4. 环比窗口支持：
   - AI 自定义时间范围
   - 未指定时自动使用前一等长窗口

### 验收标准

- 不再只查根资源自己的告警
- 每个拓扑关联资源 ID 都会查询一遍
- `realalarm/list` 请求体里的 `neId` 正确映射为资源 ID
- 当前窗口与环比窗口都能生成结果

---

## Phase 5：运行入口接线

### 目标

让 qwenpaw / Portal 的真实运行入口走完整 RCA 链，而不是停留在脚手架或局部逻辑。

### 改动项

1. Portal RCA 主入口改为专用 `alarm_analyst_service`
2. Portal 后端暴露专用接口：
   - `POST /api/portal/alarm-analyst/diagnose`
3. 主应用挂载 Portal 路由：
   - `/api/portal/employee-status`
   - `/api/portal/real-alarms`
   - `/api/portal/alarm-analyst/diagnose`
4. Portal 前端从 RCA 主流程中移除对 `fault_scenario_service` 的依赖

### 验收标准

- Portal 点击告警后，走的是专用 `alarm_analyst_service`
- 主应用中 `/api/portal/*` 不再 404
- 故障处置员对话里展示的是完整聚合分析结果，而不是脚手架占位文案

---

## Phase 6：运行稳定性和网络兼容

### 目标

解决在 macOS 或其他特定环境下，Python HTTP 客户端失败但系统 `curl` 可用的问题。

### 改动项

1. `veops-cmdb`：
   - 匿名优先
   - 401/403 再登录
   - Python 网络失败时回退到 `curl`
2. `real-alarm`：
   - Python `requests` 失败时回退到 `curl`
3. 保持回退前后请求体一致，避免 transport path 差异导致行为不一致

### 验收标准

- 在 Python HTTP 不可用但 curl 可用的环境下，技能仍能工作
- 回退后 `neId`、时间窗口、Header 不丢失
- `veops-cmdb` 与 `real-alarm` 都有对应回退测试

---

## 5. 交付顺序建议

推荐按下面顺序推进：

1. Portal 输入锚点
2. 根资源确认与指标链路
3. 拓扑扩散与资源 ID 汇总
4. 拓扑关联告警 fan-out
5. Portal / qwenpaw 运行入口接线
6. 网络兼容与回退机制
7. 文档、验收与端到端联调

原因：

- 先保证输入正确
- 再保证脚本逻辑正确
- 再保证运行入口真的走到这条逻辑
- 最后做兼容与联调

---

## 6. 验收检查清单

交付前至少完成以下检查：

### 6.1 输入侧

- [ ] Portal 点击告警文本包含 `resId`
- [ ] Portal 点击告警文本包含 `eventTime`

### 6.2 技能侧

- [ ] 根资源详情查询成功
- [ ] 根资源 `ciType` 确认成功
- [ ] 拓扑关系查询成功
- [ ] 全部相关资源 ID 提取成功
- [ ] 拓扑 fan-out 告警查询成功
- [ ] 当前窗口时间范围正确
- [ ] 环比窗口时间范围正确
- [ ] 指标定义接口调用成功
- [ ] 指标值接口调用成功

### 6.3 入口侧

- [ ] `/api/portal/employee-status` 可访问
- [ ] `/api/portal/real-alarms` 可访问
- [ ] `/api/portal/alarm-analyst/diagnose` 可访问
- [ ] Portal 点击告警后能展示 RCA 结果

### 6.4 质量侧

- [ ] 单元测试通过
- [ ] Python 语法检查通过
- [ ] 关键 curl 示例与真实接口一致
- [ ] 文档与实际行为一致

---

## 7. 风险与注意事项

### 风险 1：入口和文档脱节

现象：
- `SKILL.md` 写的是完整 RCA
- 实际运行入口却只走脚手架或半套逻辑

处理：
- 入口和技能脚本必须一起验收

### 风险 2：拓扑关系返回结构不稳定

现象：
- 某些环境返回平铺节点
- 某些环境返回关系边
- 某些环境返回嵌套结构

处理：
- 提取逻辑必须按“图结构”而不是“单层列表”处理

### 风险 3：时间窗口偏离告警锚点

现象：
- 查询告警用了太宽时间窗
- 或者完全没围绕 `eventTime`

处理：
- 当前窗口必须固定锚定 `eventTime ± 10 分钟`

### 风险 4：只查根资源，不查拓扑关联资源

这是当前最容易漏掉的关键步骤。  
必须通过测试和文档双重锁定。

### 风险 5：网络兼容性导致假失败

现象：
- Python HTTP 客户端失败
- curl 正常

处理：
- 保留 curl 回退
- 回退逻辑必须有测试

---

## 8. 完成标志

当且仅当以下条件全部满足，视为该需求完成：

1. Portal 点击一条告警后，能把 `resId + eventTime` 送到 RCA 链路
2. 系统能先确认根资源与根资源 `ciType`
3. 系统能拿到拓扑里全部相关资源 ID
4. 系统能按这些资源 ID 查当前窗口与环比窗口告警
5. 系统能按根资源 `ciType` 查指标定义和指标值
6. 系统能把告警与指标上下文一起交给 AI 做 RCA
7. Portal 最终能展示结构化 RCA 结果
