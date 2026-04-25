# Portal 前端优化待办

本文档用于记录当前 `portal/` 前端侧**已识别但暂未实施**的优化项，便于后续继续治理时直接接手。

> 说明
>
> - 当前以**记录问题和优化方向**为主，不包含本轮实现。
> - 优先级按“稳定性 / 性能收益 / 后续维护风险”综合排序。
> - 默认原则：**不改变现有功能与用户流程**，优先做行为保持型重构和性能治理。

## 当前结论

`DigitalEmployeePage.tsx` 已经从超大文件明显收敛，但 portal 前端当前最值得继续优化的重点，已经转移到以下三类：

1. **资源导入大组件**
2. **远端聊天流式大 hook**
3. **本地会话持久化热路径**

这三块处理完之后，portal 的可维护性、稳定性和页面响应感受都会再提升一个档次。

## 优先级清单

| 优先级 | 模块 / 文件 | 问题 | 风险 | 建议 |
| --- | --- | --- | --- | --- |
| P1 | `portal/src/pages/digital-employee/resourceImportConversationCard.tsx` | 文件过大，当前约 4500+ 行，资源导入流程、表格编辑、拓扑、结果展示高度耦合 | 最容易继续长成不可维护组件，后续 AI/人工改动都容易引入回归 | 先拆成 `上传`、`解析`、`结构确认`、`拓扑`、`导入结果` 等子组件，再抽共用 hook / helper |
| P1 | `portal/src/pages/digital-employee/useRemoteChatSession.ts` | 远端聊天、流式消息、历史记录、停止会话、增强卡片都堆在一个大 hook 里 | 核心链路复杂，回归风险高，定位问题成本高 | 拆成 `stream lifecycle`、`history/session`、`message merge`、`alarm analyst enhancement` 等更小的 hook |
| P1 | `portal/src/lib/conversationStore.ts` | 本地会话存储频繁 `JSON.stringify / JSON.parse`，并大量使用 `cloneJsonSafe()` | 流式聊天和频繁更新时容易阻塞主线程，拖慢前端响应 | 对 `saveConversationStore()` 做 debounce；减少全量序列化；尽量局部更新 |
| P2 | `portal/src/pages/digital-employee/usePortalAlerts.ts` | 告警固定轮询，页面隐藏时也继续请求 | 无效请求多，浪费前端和后端资源 | 加 `document.visibilityState` 判断；隐藏页暂停轮询，回前台补拉 |
| P2 | `portal/src/pages/digital-employee/usePortalDashboard.ts` | dashboard 远端请求没有真正 abort，只是用 `cancelled` 标记兜底 | 切页/切模式时仍会有旧请求跑完并尝试回写状态 | API 层支持 `AbortController`，在 effect cleanup 中取消 |
| P2 | `portal/src/pages/digital-employee/usePortalChatOrchestration.ts` / `usePortalSessionHistory.ts` / `DigitalEmployeePage.tsx` | 最近已拆分，但 chat/session 相关类型仍偏弱，`any` 仍较多 | 继续重构时容易再出现运行时错误或白屏 | 逐步补齐 `Message`、`SessionRecord`、资源导入 flow 等明确类型 |
| P3 | `portal/src/pages/digital-employee/pageFragments.tsx` | 仍然较大，且 fragment 组件较多 | 后续可能再次累积为新的大文件 | 按页面区域继续拆小，并对高频渲染片段做 memo 化评估 |
| P3 | `portal/src/pages/digital-employee/usePortalResourceImport.ts` | 资源导入中文件引用和流程状态还比较重 | 用户中途跳转、长时间停留时，状态同步和文件释放要更严谨 | 增加超时清理、unmount 回收、必要时做后端状态对齐 |

## 重点说明

### 1. `resourceImportConversationCard.tsx` 是当前最大的维护风险点

虽然 `DigitalEmployeePage.tsx` 已经明显瘦身，但资源导入卡片组件现在已经成为新的“巨型文件”。

这个文件的问题不只是“长”，而是它同时承载了：

- 文件上传与解析状态
- 结构化数据编辑
- 关系拓扑预览
- 导入执行结果
- 大量局部交互与展示细节

后续如果继续在这个文件里叠逻辑，回归概率会很高。  
**建议下一轮优先从这里继续拆。**

### 2. `useRemoteChatSession.ts` 是 portal 最核心的复杂逻辑之一

远端聊天目前是 portal 最核心、也最容易出隐蔽问题的链路之一。当前问题主要在于：

- hook 体量过大
- `Map` / `ref` 状态较多
- 流式消息合并逻辑分散
- 消息列表更新频繁且成本高

建议优先把“消息流处理”和“会话历史管理”分开，否则后续继续加能力时复杂度会持续上升。

### 3. `conversationStore.ts` 需要从“能用”升级到“更轻”

当前本地会话存储已经做了不少裁剪和安全处理，但在性能上还有优化空间，主要体现在：

- 频繁整仓序列化
- 多处 `cloneJsonSafe()`
- 多个 hook 在直接触发持久化

这块不一定马上重写，但建议下一轮至少先做：

1. `saveConversationStore()` debounce
2. 尽量避免每次都全量 stringify
3. 对热点路径补充性能观察日志

## 建议实施顺序

后续如果继续优化，建议按下面顺序推进：

1. **拆 `resourceImportConversationCard.tsx`**
2. **拆 `useRemoteChatSession.ts`**
3. **优化 `conversationStore.ts` 持久化热路径**
4. **给 alert / dashboard 请求补 visibility + abort**
5. **逐步补齐 chat/session/resource-import 类型**

## 实施约束

后续继续做这些优化时，建议保持以下边界：

- 仅改 `portal/`，不要误动 `console/`
- 优先做**行为保持型重构**
- 每轮拆分后都重新构建 portal
- 对 chat / session / resource import 这三条链路，优先防止白屏和状态错乱
- 对用户可见流程，不做无必要的交互改版

## 备注

本文件是 portal 前端优化 backlog。  
后续真正开始实施时，可以按本文件优先级逐项落地，而不是再次从头梳理。
