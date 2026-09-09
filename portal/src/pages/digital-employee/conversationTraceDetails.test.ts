import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

const componentsSource = readFileSync(
  fileURLToPath(new URL("./components.tsx", import.meta.url)),
  "utf8",
);
const settingsSource = readFileSync(
  fileURLToPath(new URL("./settingsPanel.tsx", import.meta.url)),
  "utf8",
);

test("chat trace steps restore expandable thinking and tool details", () => {
  assert.match(componentsSource, /detailsExpandable[\s\S]*?<details/);
  assert.match(componentsSource, /detailsExpandable[\s\S]*?<ToolTraceBlock block=\{block\}/);
  assert.match(componentsSource, /index === auxiliaryTraceBlocks\.length - 1/);
});

test("conversation settings expose a detail expandability control", () => {
  assert.match(settingsSource, />过程记录步骤详情</);
  assert.match(settingsSource, />允许展开</);
  assert.match(settingsSource, />仅显示概览</);
});
