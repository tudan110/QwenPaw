import assert from "node:assert/strict";
import test from "node:test";
import {
  approvalRemainingSeconds,
  approvalStorageKey,
  normalizeApprovalLevel,
  selectMainChatApprovals,
  withMainChatApprovalLevel,
  type MainChatApproval,
} from "./mainChatApproval.ts";

const pending: MainChatApproval = {
  request_id: "approval-1",
  session_id: "root",
  root_session_id: "root",
  agent_id: "agent-a",
  tool_name: "Write",
  severity: "INFO",
  findings_count: 1,
  result_summary: "STRICT mode",
  created_at: 100,
  timeout_seconds: 300,
};

test("default mode leaves the existing main-chat request untouched", () => {
  const body = { input: [], session_id: "root", request_context: { trace: "keep" } };
  assert.equal(withMainChatApprovalLevel(body, null), body);
  assert.deepEqual(body.request_context, { trace: "keep" });
});

test("explicit mode merges context without modifying the original request", () => {
  const body = { input: [], request_context: { trace: "keep" } };
  assert.deepEqual(withMainChatApprovalLevel(body, "STRICT"), {
    input: [],
    request_context: { trace: "keep", approval_level: "STRICT" },
  });
  assert.deepEqual(body.request_context, { trace: "keep" });
  for (const level of ["STRICT", "SMART", "AUTO", "OFF"] as const) {
    assert.deepEqual(withMainChatApprovalLevel({ stream: true }, level), {
      stream: true, request_context: { approval_level: level },
    });
  }
});

test("mode preferences isolate users, agents, sessions and new-chat drafts", () => {
  const scopes = [
    ["alice", "agent-a", "root"],
    ["bob", "agent-a", "root"],
    ["alice", "agent-b", "root"],
    ["alice", "agent-a", "other"],
    ["alice", "agent-a", ""],
    ["alice:agent-a", "root", ""],
  ];
  assert.equal(new Set(scopes.map(([user, agent, session]) =>
    approvalStorageKey(user, agent, session),
  )).size, scopes.length);
  for (const input of [undefined, null, "", "strict", "unexpected"]) {
    assert.equal(normalizeApprovalLevel(input), null);
  }
  assert.equal(normalizeApprovalLevel("STRICT"), "STRICT");
  assert.equal(normalizeApprovalLevel("OFF"), "OFF");
});

test("only the current root tree is shown, including owned sub-agent approvals", () => {
  const child = {
    ...pending, request_id: "child", session_id: "child-session",
    agent_id: "child-agent", owner_agent_id: "agent-a", created_at: 90,
  };
  const otherRoot = { ...pending, request_id: "other-root", root_session_id: "other" };
  const otherOwner = { ...pending, request_id: "other-owner", owner_agent_id: "agent-b" };
  const records = [pending, otherRoot, child, otherOwner];
  assert.deepEqual(selectMainChatApprovals(records, "agent-a", "root"), [child, pending]);
  assert.equal(records[0], pending);
  assert.deepEqual(selectMainChatApprovals(records, "agent-b", "missing"), []);
});

test("approval expiry uses server creation time, never goes negative and survives remount", () => {
  assert.equal(approvalRemainingSeconds(pending, 100000), 300);
  assert.equal(approvalRemainingSeconds(pending, 399500), 1);
  assert.equal(approvalRemainingSeconds(pending, 400000), 0);
  assert.equal(approvalRemainingSeconds(pending, 500000), 0);
});
