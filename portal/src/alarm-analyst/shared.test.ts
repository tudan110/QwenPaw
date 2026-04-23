import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAlarmAnalystCardRequest,
  getAlarmAnalystReportMarkdown,
  mergeAlarmAnalystCards,
  shouldEnableAlarmAnalystCards,
} from "./shared";

test("builds alarm analyst card request from grouped response blocks", () => {
  const message = {
    id: "agent-1",
    enhancementSourceMessageId: "assistant-1",
    processBlocks: [
      { kind: "tool", toolName: "read_file", outputContent: "{\"series\":[]}" },
      { kind: "response", content: "## 根因分析结论\n- MySQL 锁等待放大" },
    ],
  };

  const payload = buildAlarmAnalystCardRequest({
    chatId: "chat-1",
    sessionId: "session-1",
    employeeId: "fault",
    message,
  });

  assert.ok(payload);
  assert.equal(payload?.messageId, "assistant-1");
  assert.equal(payload?.reportMarkdown, "## 根因分析结论\n- MySQL 锁等待放大");
  assert.equal(payload?.processBlocks[0].toolName, "read_file");
});

test("merges stored cards back into grouped messages by source message id", () => {
  const messages = [
    {
      id: "agent-1",
      enhancementSourceMessageId: "assistant-1",
      processBlocks: [{ kind: "response", content: "报告正文" }],
    },
  ];
  const cards = [
    {
      type: "alarm-analyst-card",
      version: "v1",
      source: {
        chatId: "chat-1",
        messageId: "assistant-1",
        skillName: "alarm-analyst",
        contentHash: "abc123",
      },
      summary: {
        title: "数据库锁异常",
        conclusion: "MySQL 锁等待放大",
      },
      rootCause: { reason: "MySQL 锁等待放大" },
      impact: { affectedApplications: [], affectedResources: [] },
      topology: { nodes: [], edges: [] },
      recommendations: [],
      evidence: [],
      rawReportMarkdown: "报告正文",
    },
  ] as any;

  const merged = mergeAlarmAnalystCards(messages, cards);

  assert.equal(getAlarmAnalystReportMarkdown(merged[0]), "报告正文");
  assert.equal(merged[0].alarmAnalystCard.summary.title, "数据库锁异常");
});

test("merges stored cards by raw report markdown when message id differs", () => {
  const messages = [
    {
      id: "agent-2",
      enhancementSourceMessageId: "history-assistant-1",
      processBlocks: [{ kind: "response", content: "报告正文-历史回放" }],
    },
  ];
  const cards = [
    {
      type: "alarm-analyst-card",
      version: "v1",
      source: {
        chatId: "chat-1",
        messageId: "stream-assistant-1",
        skillName: "alarm-analyst",
        contentHash: "hash-1",
      },
      summary: {
        title: "数据库锁异常",
        conclusion: "历史回放兜底匹配",
      },
      rootCause: { reason: "历史回放兜底匹配" },
      impact: { affectedApplications: [], affectedResources: [] },
      topology: { nodes: [], edges: [] },
      recommendations: [],
      evidence: [],
      rawReportMarkdown: "报告正文-历史回放",
    },
  ] as any;

  const merged = mergeAlarmAnalystCards(messages, cards);

  assert.equal(merged[0].alarmAnalystCard.summary.conclusion, "历史回放兜底匹配");
});

test("only enables alarm analyst cards for fault workorder sessions", () => {
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "fault",
      session: { meta: { source: "portal-fault-workorder" } },
    }),
    true,
  );
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "fault",
      session: { meta: { source: "portal-chat" } },
    }),
    false,
  );
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "fault",
      session: { title: "故障处置 · MySQL 告警 · WO-001" },
    }),
    true,
  );
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "fault",
      session: { detail: "工单：WO-001 · 状态：已完成" },
    }),
    true,
  );
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "query",
      session: { meta: { source: "portal-fault-workorder" } },
    }),
    false,
  );
});
