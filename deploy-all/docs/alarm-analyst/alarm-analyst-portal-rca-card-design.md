# Alarm Analyst Portal RCA 卡片化展示设计文档

## 1. 文档目的

本文档用于定义 `alarm-analyst` 技能在 **Portal 对接 QwenPaw 标准对话链路** 下的卡片化展示方案。

当前用户是在 Portal 页面中与 QwenPaw 对话，QwenPaw 仍然负责：

- 工具调用
- 思考过程
- 最终 AI 文本响应

本次设计的目标不是改造 QwenPaw 核心聊天框架，而是：

1. 保持 QwenPaw 作为能力基座不变
2. 在 Portal 前端对 `alarm-analyst` 的最终结果做结构化增强
3. 把长篇 RCA 报告升级为更友好的业务卡片
4. 保证历史会话回放时仍能看到同样的卡片

---

## 2. 约束边界

### 2.1 可改范围

允许修改：

- `portal/` 前端代码
- `src/qwenpaw/extensions/` 下的扩展后端代码

### 2.2 不可改范围

本方案**不修改**以下内容：

- QwenPaw 核心聊天页通用渲染逻辑
- QwenPaw 核心消息模型
- QwenPaw 核心历史会话存储结构
- QwenPaw 核心 `app/` 主链路代码

### 2.3 工程原则

必须遵循以下原则：

1. **QwenPaw 原始对话不受影响**
2. **Portal 增强失败时可完全降级为原始文本展示**
3. **历史会话的卡片展示不依赖“重新跑一次 RCA”**
4. **拓扑图使用结构化节点边数据，不直接执行 skill 输出的前端代码**

---

## 3. 当前现状

当前 `alarm-analyst` 在 Portal 对话中的可见链路为：

1. 用户在 Portal 页面发起对话
2. QwenPaw 输出工具调用、思考、执行日志
3. 最终返回一大段 markdown / 文本报告
4. Portal 页面按通用消息方式展示整段内容

当前问题：

- 关键信息埋在长文里，阅读成本高
- 用户要手动从报告中抽取结论、影响范围、建议
- 拓扑信息虽然可能已被采集，但没有以直观图形呈现
- 历史会话里只能看到原文，不便快速回顾 RCA 结论

---

## 4. 目标与非目标

## 4.1 目标

本次方案要实现：

1. 在最终 AI 回复上方增加结构化 RCA 卡片层
2. 默认优先展示卡片，完整原文折叠显示
3. 支持展示：
   - 根因分析结论
   - 影响范围
   - 应用 / 资源拓扑图
   - 处置建议
   - 证据摘要
4. 历史会话回放时，Portal 仍能恢复对应卡片
5. 整体方案不侵入 QwenPaw 核心

## 4.2 非目标

本次不做：

- 改造 QwenPaw 通用 Chat 页为通用卡片引擎
- 修改 QwenPaw 核心消息 schema
- 修改 skill 必须输出前端可执行图表代码
- 把全部技能统一接入结构化卡片框架

---

## 5. 总体方案

本次采用 **“原始对话 + Portal 增强卡片”** 双层展示方案。

### 5.1 核心思路

1. QwenPaw 继续按现有方式产出原始消息流
   - 工具调用
   - 思考内容
   - 最终长文 RCA 报告
2. Portal 在识别到 `alarm-analyst` 最终结果后，调用 `src/qwenpaw/extensions/` 中的增强接口
3. 增强接口把原始报告和关键上下文转换成结构化 `alarmAnalystCard`
4. Portal 将卡片插入最终 AI 回复区域上方展示
5. Portal 将增强结果按 `chatId + messageId` 持久化
6. 加载历史会话时，Portal 再把增强结果 merge 回原始消息

### 5.2 展示形态

一条 `alarm-analyst` 最终消息由两层组成：

1. **增强卡片层**
2. **原始分析报告层（默认折叠）**

工具调用与思考区保持现状，不做强制卡片化。

---

## 6. 页面交互设计

## 6.1 消息展示顺序

对 `alarm-analyst` 的最终 AI 回复，Portal 展示顺序为：

1. 工具调用 / 过程日志（保持现状）
2. RCA 总览卡
3. 影响范围卡
4. 拓扑图卡
5. 处置建议卡
6. 证据摘要卡
7. “查看完整分析”折叠区

## 6.2 默认交互

- 卡片默认展开
- 原始 markdown 默认折叠
- 用户可点击“查看完整分析”展开全文
- 拓扑图默认展示关键链路
- 提供“展开全部拓扑”切换

## 6.3 降级行为

如果增强失败：

- 不影响原始 QwenPaw 回复展示
- 不影响工具日志与思考内容展示
- Portal 仅展示原始完整分析内容

---

## 7. 结构化卡片模型

建议定义 Portal 专用结构化协议 `AlarmAnalystCardV1`。

```ts
type AlarmAnalystCardV1 = {
  type: "alarm-analyst-card";
  version: "v1";
  source: {
    chatId: string;
    messageId: string;
    skillName: "alarm-analyst";
    contentHash: string;
  };
  summary: {
    title: string;
    conclusion: string;
    severity?: string;
    confidence?: "high" | "medium" | "low";
    status?: "identified" | "suspected" | "unknown";
  };
  rootCause: {
    resourceId?: string;
    resourceName?: string;
    ciId?: string | number;
    reason: string;
  };
  impact: {
    affectedApplications: Array<{ id?: string; name: string }>;
    affectedResources: Array<{ id?: string; name: string; type?: string }>;
    blastRadiusText?: string;
  };
  topology: {
    nodes: Array<Record<string, unknown>>;
    edges: Array<Record<string, unknown>>;
    highlightedNodeIds?: string[];
  };
  recommendations: Array<{
    title: string;
    priority: "p0" | "p1" | "p2";
    description: string;
    risk?: string;
    actionType?: "manual" | "script" | "observe";
  }>;
  evidence: Array<{
    kind: "alarm" | "metric" | "cmdb" | "tool";
    title: string;
    summary: string;
  }>;
  rawReportMarkdown: string;
};
```

### 7.1 字段说明

#### summary

用于第一屏快速回答：

- 这是什么故障
- 根因是什么
- 严重程度如何
- 结论是否已经确定

#### rootCause

用于明确根因锚点：

- 根资源
- 根因对象
- 根因解释

#### impact

用于告诉用户“影响到谁”：

- 哪些应用受影响
- 哪些资源受影响
- 影响面总结

#### topology

用于图形化展示：

- 节点
- 边
- 高亮根因路径

#### recommendations

用于指导下一步处置：

- 建议动作
- 优先级
- 风险提示

#### evidence

用于证明结论：

- 告警证据
- 指标证据
- CMDB 关系证据
- 工具输出摘要

#### rawReportMarkdown

用于保留完整原始报告，保证可追溯与完整信息展示。

---

## 8. 前端设计

## 8.1 Portal 前端职责

Portal 前端负责：

1. 识别 `alarm-analyst` 最终消息
2. 调用增强接口
3. 渲染结构化卡片
4. 保存增强结果
5. 历史回放时把增强结果 merge 到消息上

## 8.2 推荐组件拆分

建议新增以下组件：

- `AlarmAnalystCardContainer`
- `AlarmAnalystSummaryHero`
- `AlarmAnalystImpactCard`
- `AlarmAnalystTopologyCard`
- `AlarmAnalystRecommendationsCard`
- `AlarmAnalystEvidenceCard`
- `AlarmAnalystRawReportCollapse`

## 8.3 推荐接入点

建议在 Portal 当前消息渲染链路中，对“最终 AI 回复消息”做增强判断，而不是改工具调用和思考消息的基础渲染行为。

推荐接入方式：

1. 保持原始消息列表不变
2. 在消息组件中检测 `message.enhancement?.type === "alarm-analyst-card"`
3. 若命中，则在最终回复 bubble 内插入增强卡片

## 8.4 识别策略

推荐满足以下任一条件时，触发增强：

1. 当前会话是 `fault` 数字员工 / `alarm-analyst` 场景
2. 最终回复里包含结构化 RCA 报告明显特征
3. 后端已明确返回 `skillName = alarm-analyst`

优先推荐以后端标记为主，文本规则为辅。

---

## 9. 拓扑图设计

## 9.1 原则

拓扑图必须使用结构化数据，而不是直接执行 skill 输出的前端图表代码。

### 原因

- 保证 Portal 样式统一
- 保证历史会话可回放
- 避免 skill 输出与前端实现强耦合
- 避免执行任意图表代码带来的安全和兼容问题

## 9.2 输出格式

增强接口输出：

- `nodes`
- `edges`
- `highlightedNodeIds`

Portal 前端再统一转换为 ECharts 配置。

## 9.3 默认渲染策略

一期默认：

- 只显示关键根因链路
- 高亮根资源、告警集中节点、受影响应用节点
- 提供“展开全部拓扑”按钮

---

## 10. 扩展后端设计

扩展代码放在：

- `src/qwenpaw/extensions/api/`

## 10.1 推荐接口

### `POST /api/portal/alarm-analyst/enhance`

输入：

- `chatId`
- `messageId`
- `skillName`
- `finalReportMarkdown`
- `toolTraceSummary`
- `sessionContext`

输出：

- `AlarmAnalystCardV1`

### `GET /api/portal/alarm-analyst/enhancements/{chatId}`

返回：

- 当前聊天下所有消息的增强结果列表

### `POST /api/portal/alarm-analyst/enhancements/persist`

功能：

- 保存单条或批量增强结果

---

## 11. 结构化提取策略

本次建议采用两阶段策略。

## 11.1 Phase A：规则提取

优先通过规则从最终报告中抽取：

- 一句话结论
- 根资源 / CI ID
- 告警集中点
- 受影响应用
- 处置建议
- 关键证据

优点：

- 落地快
- 可控性高
- 不依赖额外模型

## 11.2 Phase B：增强提取

当规则提取不足时，引入扩展层“结构化总结器”：

- 输入：原始报告 + 关键工具输出摘要 + 会话上下文
- 输出：固定 schema 的结构化 JSON

要求：

- 只在扩展层使用
- 不改 QwenPaw 核心技能消息流
- 必须带严格 schema 校验

---

## 12. 历史会话方案

## 12.1 设计原则

历史会话卡片展示必须：

1. 不依赖重新执行 skill
2. 不修改 QwenPaw 核心历史结构
3. 能在 Portal 加载聊天记录时稳定恢复

## 12.2 推荐方案：侧边增强存储

额外维护一份增强结果存储，使用以下键关联：

- `chatId`
- `messageId`
- `contentHash`

加载历史时：

1. Portal 先取原始聊天记录
2. Portal 再取增强结果
3. 按 `messageId` merge
4. 如 `contentHash` 不一致，则忽略旧增强结果并允许重算

## 12.3 推荐存储内容

每条增强记录至少保存：

- `chatId`
- `messageId`
- `contentHash`
- `skillName`
- `cardPayload`
- `createdAt`
- `updatedAt`

---

## 13. 一期实施范围

一期建议只做以下内容：

1. 仅支持 `alarm-analyst`
2. 卡片展示：
   - 结论
   - 影响范围
   - 拓扑图
   - 处置建议
   - 原文折叠
3. 增强结果持久化
4. 历史会话回放可见
5. 增强失败自动降级

### 一期不做

- 通用技能卡片协议
- Console 通用聊天页复用
- 拓扑节点钻取详情
- 建议动作直接联动自动处置

---

## 14. 二期方向

二期可以扩展：

1. 支持更多技能的结构化卡片
2. 证据链可视化
3. 拓扑交互增强
4. 建议动作与 Portal 工作流联动
5. 统一的 Portal 消息增强框架

---

## 15. 风险与应对

## 15.1 报告格式不稳定

风险：

- 不同版本 skill 输出格式变化导致字段提取失败

应对：

- 规则提取必须容错
- 缺字段允许局部降级
- 不允许整条消息完全失效

## 15.2 历史增强结果与原文不一致

风险：

- 原文变化但卡片仍是旧版本

应对：

- 使用 `contentHash`
- hash 不一致时不复用旧增强结果

## 15.3 拓扑过大导致前端卡顿

风险：

- 节点和边过多时图表性能差

应对：

- 默认只展示关键路径
- 提供“展开全部”
- 必要时做节点裁剪

## 15.4 增强接口失败影响主流程

风险：

- 卡片增强异常导致主对话异常

应对：

- 增强接口失败必须完全隔离
- 原始文本回复必须继续可见

---

## 16. 验收标准

交付时至少满足以下标准：

### 16.1 当前会话展示

- `alarm-analyst` 最终回复可展示结构化卡片
- 工具调用和思考过程仍正常显示
- 原始完整报告可折叠查看

### 16.2 卡片内容

- 至少包含根因结论
- 至少包含影响范围
- 至少包含一版拓扑图
- 至少包含处置建议

### 16.3 历史会话

- 历史会话重新打开后仍能看到卡片
- 没有重复跑 RCA 也能恢复展示

### 16.4 降级能力

- 增强失败时，原始完整分析仍可正常查看
- 不影响 Portal 现有对话流程

---

## 17. 推荐落地顺序

建议按以下顺序推进：

1. 定义 `AlarmAnalystCardV1` schema
2. 在 `src/qwenpaw/extensions/api/` 实现增强接口
3. 在 Portal 前端增加卡片渲染组件
4. 在最终 AI 回复接入增强逻辑
5. 实现增强结果持久化与历史 merge
6. 再做拓扑图交互与样式优化

---

## 18. 待确认事项

后续正式实现前，仍建议确认以下问题：

1. `alarm-analyst` 最终结果的稳定识别标记由谁提供
   - skill 明确输出
   - Portal 规则识别
   - 扩展后端判断
2. 增强结果持久化放在哪一层
   - Portal 本地存储
   - 扩展后端文件 / 会话态存储
   - 统一业务存储
3. 拓扑图一期采用何种视觉风格
   - 极简链路图
   - 全量关系图
   - 分层展开图

---

## 19. 结论

在“**只改 Portal + extensions，不改 QwenPaw 核心**”的前提下，最稳妥的方案是：

1. QwenPaw 继续输出原始对话流
2. Portal 对 `alarm-analyst` 最终结果做增强
3. 扩展后端把原始长文转换成结构化 RCA 卡片
4. Portal 展示“卡片优先，原文折叠”
5. 增强结果侧边持久化，保证历史会话可回放

该方案既满足当前展示诉求，也为后续把更多技能升级为结构化 Portal 卡片保留了扩展空间。
