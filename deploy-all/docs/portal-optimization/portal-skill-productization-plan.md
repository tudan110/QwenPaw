# Portal 技能产品化卡片方案

## 1. 背景

当前 `zgops-cmdb-import` 在 portal 中呈现为较完整的产品化流程：有导入卡片、过程日志、确认表单、结果区和阶段状态；而 `alarm-analyst` 与 `inspection-analyst` 目前大多仍停留在“大模型回复文本 + Markdown 展示”的层面。

这会带来两个明显问题：

1. 页面观感更像“聊天记录”，不像“可交付的产品能力”
2. 历史会话回看时，结构化信息难以快速定位，领导更难一眼看到价值

本方案目标是把这两个 skill 从“AI 回复文本”升级为“少而精的主卡 + 折叠详情 + 历史可回放”的产品化技能。

---

## 2. 目标

### 必达目标

1. `alarm-analyst` 与 `inspection-analyst` 在实时会话中支持卡片展示
2. 历史会话回看时，优先以卡片展示，而不是只看到纯文本
3. 卡片内容以“模型提炼后的结构化结果”为主，而不是主要依赖规则拆 Markdown
4. 避免“卡片太多太乱”，每轮回复以 **1 张主卡** 为核心

### 设计原则

1. **后端统一调用模型**，前端不直接拿 provider key
2. **实时生成 + 历史缓存回放 + 缺失时懒生成**
3. **模型主提炼，规则兜底**
4. **主卡摘要化，原文保留在折叠区**
5. **延续当前懒加载优化，不把 portal 再做重**

---

## 3. 现状判断

### 3.1 `zgops-cmdb-import` 为什么更像产品

它不是因为“提示词更好”，而是因为它走的是完整的结构化协议和组件化渲染路线：

- skill 输出过程状态
- portal 识别 `resourceImportFlow`
- `ResourceImportConversationCard` 负责多阶段 UI
- 日志、表单、确认、结果都由前端组件表达

也就是说，它的优势本质上是 **前后端协议 + 状态机 + 专属组件**，不是单纯的大模型文案。

### 3.2 `alarm-analyst` 当前并非从零开始

现有链路里已经有一套半成品底座：

- `portal/src/alarm-analyst/shared.ts`
- `portal/src/api/alarmAnalystCards.ts`
- `portal/src/pages/digital-employee/alarmAnalystCardComponents.tsx`
- `portal/src/pages/digital-employee/useRemoteChatSession.ts`

当前缺口主要有两个：

1. `components.tsx` 还没有把 `message.alarmAnalystCard` 真正渲染出来
2. 后端 `alarm_analyst_card_service.py` 当前仍以规则/regex 提取为主，不是模型提炼主导

### 3.3 `inspection-analyst` 当前缺口更大

`inspection-analyst` 目前还没有完整的卡片协议、组件和 hydrate 链路，需要按 `alarm-analyst` 的思路补齐。

---

## 4. 总体方案

### 4.1 总体架构

#### 实时链路

1. assistant 回复完成
2. 后端判断该消息是否适合生成 skill card
3. 后端调用模型，将本轮文本、过程块、必要元数据提炼成结构化 JSON
4. 后端校验 schema 并持久化
5. portal 将消息与 card 合并渲染

#### 历史链路

1. 打开历史会话
2. 拉取消息列表
3. 同时拉取已缓存的 card 列表
4. 前端按 `messageId` 合并
5. 对“没有 card 的旧消息”触发后台懒生成
6. 首次补齐后，后续历史直接命中缓存

---

## 5. 为什么不让前端直接拿当前会话 key 调模型

不建议这么做，原因如下：

1. **安全性差**：provider key 不应暴露到 portal 前端
2. **一致性差**：前端难以统一做鉴权、限流、审计、重试
3. **缓存难做**：卡片生成和历史回放需要统一的后端缓存层
4. **回退困难**：模型失败时，后端更适合无缝降级到规则提取

正确做法是：

- 前端只请求“获取/生成这条消息的 skill card”
- 后端根据当前 agent / session 的 provider 配置统一调模型
- 后端持久化 card，再返回给前端

---

## 6. 卡片生成策略

建议使用三段式策略，而不是单一做法。

### 第一层：skill 专用 extractor 模型

默认优先使用专门用于“结构化摘要提炼”的模型或模型配置。它不一定和对话主模型完全相同，但应当更稳定、更便宜、更适合 JSON 输出。

### 第二层：继承当前会话模型（可选）

如果明确希望卡片风格与当前会话保持一致，可以允许继承当前会话正在使用的模型配置。

### 第三层：规则兜底

当出现以下情况时，回退到现有规则提取：

- provider 不可用
- 模型调用失败
- 输出 JSON 校验失败
- 超时或达到重试上限

这样既满足“尽量用模型提炼”，又不牺牲稳定性。

---

## 7. 卡片展示原则

### 7.1 一轮回复只保留 1 张主卡

不要把一个分析过程拆成很多碎卡片堆叠。主视图只展示一张高价值摘要卡，其余内容放入折叠区域或次级面板。

### 7.2 `alarm-analyst` 推荐主卡结构

1. 结论摘要
2. 根因锚点
3. 影响范围
4. 处置建议
5. 关键证据

折叠区可放：

- 完整分析 Markdown
- 过程日志
- 拓扑图
- 工单/处置记录

### 7.3 `inspection-analyst` 推荐主卡结构

1. 巡检摘要
2. 资源确认
3. 关键指标
4. 异常发现
5. 巡检结论

折叠区可放：

- 全量指标表
- 原始巡检报告
- 拓扑/关联资源信息

### 7.4 展示顺序

优先展示：

1. 业务结论
2. 关键证据
3. 可执行动作

不要优先展示程序化中间过程，更不要直接把代码/规则提取痕迹暴露到主卡。

---

## 8. 历史会话卡片化方案

这是本次方案的硬要求。

### 8.1 新消息

- 在实时消息完成后生成 card
- 立即落库
- 后续历史回放直接读取

### 8.2 老消息缺卡

- 打开历史时检查是否存在 card
- 对缺失项触发后端懒生成
- 前端显示轻量占位态，例如“正在整理摘要卡片”
- 生成完成后替换为正式卡片

### 8.3 缓存键建议

建议最少包含：

- `chatId`
- `sessionId`
- `messageId`
- `skillName`
- `schemaVersion`
- `contentHash`

这样可以支持：

- 历史稳定回放
- 原文变化后的失效重算
- 后续 schema 升级

---

## 9. 数据协议建议

### 9.1 `alarm-analyst`

保留并扩展 `AlarmAnalystCardV1`，字段收敛为：

- `summary`
- `rootCause`
- `impactScope`
- `recommendations`
- `evidence`
- `severity`
- `confidence`
- `topology`
- `rawReport`
- `processBlocks`

要求：

- 数组字段限制上限，避免卡片过长
- 不允许模型补造证据
- 不确定的信息返回空值，不要“猜”

### 9.2 `inspection-analyst`

新增 `InspectionAnalystCardV1`，建议字段：

- `summary`
- `resource`
- `inspectionItems`
- `keyMetrics`
- `findings`
- `conclusion`
- `recommendations`
- `rawReport`
- `processBlocks`

---

## 10. 分阶段落地

## Phase 1：接通 `alarm-analyst` 主卡渲染

目标：先把已有半成品链路真正跑通。

改动重点：

- `portal/src/pages/digital-employee/components.tsx`
  - 增加 `message.alarmAnalystCard` 渲染分支
- `portal/src/pages/digital-employee/alarmAnalystCardComponents.tsx`
  - 保持当前主卡组件与懒加载图表
- `portal/src/pages/digital-employee/useRemoteChatSession.ts`
  - 保持实时生成 + 历史 hydrate 逻辑

收益：

- `alarm-analyst` 立刻从“纯文本”升级为“主卡 + 详情”
- 改动范围小，最快出效果

## Phase 2：把 `alarm-analyst` card 生成改成模型主提炼

目标：解决“卡片太乱、像代码提取”的核心问题。

改动重点：

- `src/qwenpaw/extensions/api/alarm_analyst_card_service.py`
  - 新增模型提炼路径
  - 保留规则兜底
- `src/qwenpaw/extensions/api/alarm_analyst_card_models.py`
  - 收敛/补齐 schema
- `src/qwenpaw/extensions/api/portal_backend.py`
  - 挂接生成与查询接口，必要时支持历史补卡入口

## Phase 3：补齐历史缺卡懒生成

目标：满足“查看历史会话也必须卡片展示”。

改动重点：

- 后端查询 card 列表时支持缺失检测
- 对旧消息触发后台补生成
- 前端增加补卡占位态与刷新合并逻辑

## Phase 4：为 `inspection-analyst` 建立同类卡片协议

目标：复制 `alarm-analyst` 成功经验。

改动重点：

- 新建 `InspectionAnalystCardV1` 协议
- 新建对应后端 card service / API
- 新建 portal 卡片组件与渲染分支
- 接入历史 hydrate

## Phase 5：抽通用 skill card framework

目标：避免今后每个 skill 都重复写一套散落逻辑。

方向：

- 统一消息级 skill-card registry
- 统一 hydrate / merge / fallback 机制
- 统一主卡/折叠区交互模式

---

## 11. 需要修改的关键文件

| 文件 | 作用 |
| --- | --- |
| `portal/src/pages/digital-employee/components.tsx` | 给 `alarmAnalystCard`、后续 `inspectionCard` 增加消息渲染分支 |
| `portal/src/pages/digital-employee/useRemoteChatSession.ts` | 实时生成、历史 hydrate、懒补卡合并主链路 |
| `portal/src/pages/digital-employee/alarmAnalystCardComponents.tsx` | `alarm-analyst` 主卡组件 |
| `portal/src/alarm-analyst/shared.ts` | `alarm-analyst` card 协议与 merge 逻辑 |
| `portal/src/api/alarmAnalystCards.ts` | card create/list API |
| `src/qwenpaw/extensions/api/alarm_analyst_card_service.py` | `alarm-analyst` card 生成服务，后续升级为模型主提炼 |
| `src/qwenpaw/extensions/api/alarm_analyst_card_models.py` | card schema 约束 |
| `src/qwenpaw/extensions/api/portal_backend.py` | portal 侧 card 接口接入与历史补卡承载点 |

`inspection-analyst` 落地时，建议新增平行文件而不是把业务硬塞进现有 `alarm-analyst` 文件。

---

## 12. 性能与体验要求

已经有的懒加载优化应继续沿用：

- 重型卡片组件走 `lazy` / `Suspense`
- 图表组件继续使用延迟加载块
- 历史补卡应异步，不阻塞历史消息首屏
- 主卡只放高价值字段，减少首屏高度

换句话说，产品化不是把更多内容堆上去，而是 **更少但更值钱地展示**。

---

## 13. 风险与应对

| 风险 | 应对 |
| --- | --- |
| 模型输出不稳定 | 严格 schema 校验、字段长度限制、规则兜底 |
| 历史打开变慢 | 优先读缓存，缺卡异步补生成 |
| token 成本增加 | 默认使用 skill 专用 extractor 模型 |
| 前端再次变重 | 沿用现有懒加载和惰性图表策略 |
| 卡片重新变乱 | 一轮回复仅 1 张主卡，原文与过程折叠 |

---

## 14. 最终建议

建议按以下顺序推进：

1. 先把 `alarm-analyst` 真正接成主卡展示
2. 再把其 card 生成改为“模型主提炼 + 规则兜底”
3. 紧接着补历史缺卡懒生成
4. 再把同样模式复制到 `inspection-analyst`
5. 最后收敛成通用 skill card framework

这条路线的优点是：

- 最快能先做出一个“领导看得见变化”的结果
- 不需要推翻现有链路
- 能同时满足“产品化观感”和“历史可回放卡片化”
- 后续可复制到更多 skill

---

## 15. 一句话结论

最合适的路线不是“前端直接拿当前会话 key 再调一次模型”，而是：

**后端统一模型提炼 + 历史缓存回放 + 缺失时懒生成 + 单主卡摘要展示 + 规则兜底。**

这样既安全、稳定，也最接近真正的产品化技能形态。
