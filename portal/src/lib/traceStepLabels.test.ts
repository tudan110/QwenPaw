import assert from "node:assert/strict";
import test from "node:test";
import { traceStepDisplay, getToolActionCategory } from "./traceStepLabels.ts";

test("thinking blocks show a generic analysis label (no raw reasoning)", () => {
  assert.deepEqual(traceStepDisplay({ kind: "thinking", content: "secret chain of thought" } as never), {
    icon: "fa-brain",
    text: "思考分析",
  });
});

test("skill invocations are generalized to 调用技能 (name hidden)", () => {
  assert.equal(traceStepDisplay({ kind: "tool", title: "Skill" }).text, "调用技能");
  assert.equal(traceStepDisplay({ kind: "tool", title: "real-alarm-skill" }).text, "调用技能");
  assert.equal(traceStepDisplay({ kind: "tool", title: "" }).text, "调用技能");
});

test("all non-skill tools are generalized to 调用工具 on the step header", () => {
  assert.equal(traceStepDisplay({ kind: "tool", title: "web_search" }).text, "调用工具");
  assert.equal(traceStepDisplay({ kind: "tool", title: "query_alarms" }).text, "调用工具");
  assert.equal(traceStepDisplay({ kind: "tool", title: "list_hosts" }).text, "调用工具");
  assert.equal(traceStepDisplay({ kind: "tool", title: "generate_report" }).text, "调用工具");
  assert.equal(traceStepDisplay({ kind: "tool", title: "execute_shell_command" }).text, "调用工具");
  assert.equal(traceStepDisplay({ kind: "tool", title: "run_python" }).text, "调用工具");
  assert.equal(traceStepDisplay({ kind: "tool", title: "cmdb-query__listCiTypes" }).text, "调用工具");
});

test("getToolActionCategory provides fine-grained action descriptions inside tool body", () => {
  assert.equal(getToolActionCategory("read_file"), "读取数据");
  assert.equal(getToolActionCategory("list_hosts"), "读取数据");
  assert.equal(getToolActionCategory("cmdb-query__listCiTypes"), "读取数据");
  assert.equal(getToolActionCategory("web_search"), "检索数据");
  assert.equal(getToolActionCategory("query_alarms"), "检索数据");
  assert.equal(getToolActionCategory("execute_shell_command"), "执行脚本");
  assert.equal(getToolActionCategory("run_python"), "执行脚本");
  assert.equal(getToolActionCategory("generate_report"), "生成内容");
  assert.equal(getToolActionCategory("real-alarm-skill"), "调用技能");
  assert.equal(getToolActionCategory("frobnicate_widget"), "调用工具");
});

test("unknown tools never leak the raw name — fall back to 调用工具", () => {
  const out = traceStepDisplay({ kind: "tool", title: "frobnicate_widget_v2" });
  assert.equal(out.text, "调用工具");
  assert.doesNotMatch(out.text, /frobnicate|widget/);
});

test("unknown block kinds are a neutral 处理中", () => {
  assert.equal(traceStepDisplay({ kind: "misc" }).text, "处理中");
  assert.equal(traceStepDisplay(null).text, "处理中");
});
